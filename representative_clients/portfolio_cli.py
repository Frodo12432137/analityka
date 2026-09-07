from __future__ import annotations

import argparse
import gc
import time
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .cli import _preflight_output_directory
from .consent import BRANCH_LABELS, BRANCH_ORDER, canonical_branch
from .legacy_excel import load_gams_workbook
from .model import SelectionConfig
from .portfolio_data import (
    allocate_branch_targets,
    allocate_group_quotas,
    discover_workbook_branches,
    inspect_workbook_clients,
    merge_selection_data,
)
from .portfolio_report import BranchOutput, write_portfolio_workbook
from .replacement import choose_unique_reserves
from .solver import NoFeasibleSolutionError, SolverUnavailableError, solve_selection
from .runtime import MAX_RUN_SECONDS, RunBudget, RunTimeLimitError, TIMEOUT_EXIT_CODE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Finalny model klientów reprezentatywnych dla 8 OSD, ze zgodami "
            "marketingowymi i unikalnymi zastępcami."
        )
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=Path,
        help="Skoroszyt modelu głównego; parametr można podać wielokrotnie.",
    )
    parser.add_argument("--consents", required=True, type=Path, help="Aktualny plik zgód XLSX.")
    parser.add_argument("--output", type=Path, help="Wynikowy skoroszyt XLSX.")
    parser.add_argument(
        "--total-clients",
        default=1100,
        type=int,
        help="Dokładna łączna liczba klientów podstawowych: od 500 do 1100 (domyślnie 1100).",
    )
    parser.add_argument("--groups", type=int, default=4, help="Liczba grup na OSD.")
    parser.add_argument("--max-share", type=float, default=0.20)
    parser.add_argument("--time-limit", type=float, default=1800.0, help="Maksimum sekund na grupę (domyślnie 1800 = 30 min); skracane przez budżet globalny.")
    parser.add_argument("--total-time-limit", type=float, default=MAX_RUN_SECONDS, help="Limit CAŁEGO przebiegu w sekundach, wraz z odczytem i zapisem: maksymalnie 86400 (24 h).")
    parser.add_argument("--mip-gap", type=float, default=0.10)
    parser.add_argument("--reserve-shortlist", type=int, default=32)
    parser.add_argument("--solver-log", action="store_true")
    validation = parser.add_mutually_exclusive_group()
    validation.add_argument("--validate-only", action="store_true", help="Szybka kontrola list i pojemności, bez profili.")
    validation.add_argument("--validate-full", action="store_true", help="Kontrola wszystkich profili i formuł, bez solvera.")
    parser.add_argument("--allow-partial", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _source_map(paths: Sequence[Path]) -> "OrderedDict[str, list[Tuple[Path, str]]]":
    mapping: "OrderedDict[str, list[Tuple[Path, str]]]" = OrderedDict()
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            raise ValueError(f"Ten sam plik wejściowy podano więcej niż raz: {path}.")
        seen.add(resolved)
        for raw_branch in discover_workbook_branches(path):
            key = canonical_branch(raw_branch)
            mapping.setdefault(key, []).append((path, raw_branch))
    return mapping


def main(argv: Optional[Sequence[str]] = None, *, deadline: Optional[float] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validation_run = args.validate_only or args.validate_full
    started = time.monotonic()
    try:
        budget = RunBudget(args.total_time_limit, deadline)
    except ValueError as exc:
        parser.error(str(exc))
    if not 500 <= args.total_clients <= 1100:
        parser.error("--total-clients musi należeć do przedziału 500–1100.")
    if args.groups <= 0:
        parser.error("--groups musi być dodatnie.")
    if args.reserve_shortlist <= 0:
        parser.error("--reserve-shortlist musi być dodatnie.")
    try:
        SelectionConfig(
            group_count=args.groups, max_contribution_share=args.max_share,
            time_limit_seconds=args.time_limit, mip_relative_gap=args.mip_gap,
        ).validate()
    except ValueError as exc:
        parser.error(str(exc))
    if not validation_run:
        if args.output is None:
            parser.error("Przy uruchomieniu modelu wymagany jest --output.")
        if args.output.suffix.lower() != ".xlsx":
            parser.error("Plik wynikowy musi mieć rozszerzenie .xlsx.")
        forbidden = {path.resolve() for path in args.input} | {args.consents.resolve()}
        if args.output.resolve() in forbidden:
            parser.error("Wynik nie może zastąpić pliku wejściowego ani pliku zgód.")
        if args.output.exists() and not args.overwrite:
            parser.error("Plik wynikowy już istnieje; użyj --overwrite albo innej nazwy.")
        try:
            _preflight_output_directory(args.output, args.overwrite)
        except OSError as exc:
            parser.exit(1, f"BŁĄD ZAPISU: {exc}\n")

    try:
        from .consent import load_consent_workbook

        budget.check()
        print("Wczytywanie aktualnego pliku zgód...", flush=True)
        consents = load_consent_workbook(args.consents)
        sources = _source_map(args.input)
        missing = [key for key in BRANCH_ORDER if key not in sources]
        if missing and not args.allow_partial:
            raise ValueError(
                "Brakuje plików dla OSD: "
                + ", ".join(BRANCH_LABELS[key] for key in missing)
            )
        source_clients: Dict[str, set[str]] = {}
        consent_clients: Dict[str, set[str]] = {}
        exclusions: Dict[str, set[str]] = {}
        required: Dict[str, set[str]] = {}
        file_candidates = {}
        for key, entries in sources.items():
            budget.check()
            source_clients[key] = set()
            consent_clients[key] = set()
            exclusions[key] = set()
            required[key] = set()
            for path, _ in entries:
                all_ids, allowed_ids, excluded_ids, required_ids = inspect_workbook_clients(
                    path, consents.by_branch[key]
                )
                file_candidates[key, path] = allowed_ids
                source_clients[key].update(all_ids)
                consent_clients[key].update(allowed_ids)
                exclusions[key].update(excluded_ids)
                required[key].update(required_ids)
        eligible_counts = {
            key: len(consent_clients[key] - exclusions[key]) for key in sources
        }
        branch_targets = allocate_branch_targets(eligible_counts, args.total_clients)
        for key in sources:
            if len(required[key]) > branch_targets[key]:
                raise ValueError(
                    f"{BRANCH_LABELS[key]}: liczba klientów wymaganych przekracza "
                    "przydzielony limit."
                )
        print(
            "Podział celu: "
            + ", ".join(
                f"{BRANCH_LABELS[key]}={branch_targets[key]}" for key in sources
            ),
            flush=True,
        )
        for key in sources:
            print(
                f"  {BRANCH_LABELS[key]}: {len(source_clients[key])} PPE w źródłach, "
                f"{len(consent_clients[key])} ze zgodą, {eligible_counts[key]} po wykluczeniach; "
                f"wybór {branch_targets[key]} + {branch_targets[key]} zastępców.", flush=True,
            )
        if args.validate_only:
            print("Kontrola list zakończona. Profile i formuły nie były sprawdzane; użyj --validate-full.")
            return 0

        budget_hours = len(sources) * args.groups * args.time_limit / 3600
        if not validation_run:
            print(
                f"Budżet solvera: {len(sources)} OSD × {args.groups} grup × "
                f"do {args.time_limit:g} s = do {budget_hours:g} h przed skróceniem. "
                f"Nadrzędny limit CAŁOŚCI: {args.total_time_limit / 3600:g} h, "
                "łącznie z odczytem, budową modeli, zastępcami i eksportem.", flush=True,
            )

        outputs = []
        checkpoint_dir = None
        completed_groups = 0
        total_groups = len(sources) * args.groups

        def group_time_limit():
            seconds = budget.group_seconds(args.time_limit, total_groups - completed_groups)
            print(f"  Limit tego solve: {seconds:.1f} s; do limitu całości {budget.remaining() / 3600:.2f} h.", flush=True)
            return seconds

        def group_complete(group):
            nonlocal completed_groups
            completed_groups += 1
            print(
                f"  {group.group}: {group.solve_seconds:.1f} s, "
                f"wybrano {len(group.selected_weights)}, L1={group.objective_value:.6g}, "
                f"luka={group.mip_gap}, status={group.status_text}", flush=True,
            )

        def run_metadata():
            return {
                "limit_calego_przebiegu_s": args.total_time_limit,
                "maksymalny_limit_grupy_s": args.time_limit,
                "uplynelo_przed_zapisem_s": round(time.monotonic() - started, 2),
                "cel_calego_portfela": args.total_clients,
            }

        report_rows = 1
        for branch_position, (key, entries) in enumerate(sources.items(), start=1):
            budget.check()
            branch_started = time.monotonic()
            label = BRANCH_LABELS[key]
            print(f"[{branch_position}/{len(sources)}] Wczytywanie OSD {label}...", flush=True)
            parts = []
            for path, raw_branch in entries:
                budget.check()
                if not file_candidates[key, path]:
                    print(f"  {path.name}: brak PPE ze zgodą dla {label}, pominięto profile tej części.", flush=True)
                    continue
                parts.append(
                    load_gams_workbook(
                        path,
                        branch=raw_branch,
                        allowed_client_ids=consents.by_branch[key],
                        on_stage=lambda message, prefix=path.name: print(
                            f"  {prefix}: {message}", flush=True
                        ),
                    )
                )
            data = merge_selection_data(parts)
            budget.check()
            del parts
            branch_total = branch_targets[key]
            quotas = allocate_group_quotas(data, branch_total, args.groups)
            config = SelectionConfig(
                max_clients_per_group=max(1, max(quotas)),
                group_count=args.groups,
                max_contribution_share=args.max_share,
                time_limit_seconds=args.time_limit,
                mip_relative_gap=args.mip_gap,
                solver_display=args.solver_log,
                exact_clients_per_group=quotas,
            )
            config.validate()
            report_rows += args.groups * len(data.periods)
            if report_rows > 1_048_576:
                raise ValueError("Bilans wszystkich OSD przekracza limit wierszy pojedynczego arkusza Excel.")
            print(
                f"  Dokładne limity grup: {', '.join(map(str, quotas))}.",
                flush=True,
            )
            if args.validate_full:
                print(
                    f"  Dane poprawne: {len(data.periods)} okresów, "
                    f"macierz {data.client_balance.nbytes / 1024**3:.3f} GiB. "
                    f"Odczyt i kontrola OSD: {time.monotonic() - branch_started:.1f} s.", flush=True,
                )
                del data
                gc.collect()
                continue
            selection = solve_selection(
                data,
                config,
                on_group_start=lambda name, position, total: print(
                    f"  Solver {name} ({position}/{total})...", flush=True
                ),
                on_group_complete=group_complete,
                time_limit_provider=group_time_limit,
            )
            if selection.selected_count != branch_total:
                raise RuntimeError(
                    f"{label}: wybrano {selection.selected_count}, oczekiwano {branch_total}."
                )
            print(f"  Dobór {branch_total} unikalnych zastępców...", flush=True)
            budget.check()
            replacements = choose_unique_reserves(
                data,
                selection,
                initial_shortlist=args.reserve_shortlist,
            )
            print(f"  Cały etap OSD {label}: {(time.monotonic() - branch_started) / 60:.1f} min.", flush=True)
            outputs.append(
                BranchOutput(
                    selection=selection,
                    replacements=replacements,
                    source_files=tuple(path.name for path, _ in entries),
                    source_clients=len(source_clients[key]),
                    consent_clients=len(consent_clients[key]),
                    legacy_excluded=len(exclusions[key]),
                    eligible_clients=eligible_counts[key],
                    target_clients=branch_total,
                )
            )
            budget.check()
            if checkpoint_dir is None:
                checkpoint_dir = Path(tempfile.mkdtemp(prefix=f"{args.output.stem}_czesci_", dir=args.output.parent))
                print(f"  Raporty częściowe OSD: {checkpoint_dir}", flush=True)
            checkpoint = write_portfolio_workbook(
                [outputs[-1]], checkpoint_dir / f"{key}.xlsx", branch_total,
                partial=True, run_metadata=run_metadata(),
            )
            print(f"  Zapisano ukończony OSD (nie cały portfel): {checkpoint}", flush=True)
            del data
            gc.collect()
        if args.validate_full:
            budget.check()
            print(
                f"Wszystkie pliki sprawdzone w {(time.monotonic() - started) / 60:.1f} min. "
                "Nie uruchomiono solvera ani nie utworzono wyniku XLSX. "
                "Wykonalność ograniczeń wyboru zostanie sprawdzona przez solver.", flush=True,
            )
            return 0
        budget.check()
        output = write_portfolio_workbook(
            outputs,
            args.output,
            args.total_clients,
            overwrite=args.overwrite,
            run_metadata=run_metadata(),
        )
    except RunTimeLimitError as exc:
        print(f"STOP: {exc} Sprawdź wcześniej zapisane raporty *_czesci_*; pełny wynik może nie istnieć.", flush=True)
        return TIMEOUT_EXIT_CODE
    except (
        FileExistsError,
        FileNotFoundError,
        MemoryError,
        NoFeasibleSolutionError,
        OSError,
        RuntimeError,
        SolverUnavailableError,
        ValueError,
    ) as exc:
        parser.exit(1, f"BŁĄD: {exc}\n")
    print(f"Gotowe. Zapisano wynik: {output}. Łączny czas: {(time.monotonic() - started) / 60:.1f} min.")
    if any(not group.optimal for item in outputs for group in item.selection.groups):
        print("UWAGA: część grup ma rozwiązanie dopuszczalne bez potwierdzonej optymalności.")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    from .runtime import run_portfolio
    raise SystemExit(run_portfolio())
