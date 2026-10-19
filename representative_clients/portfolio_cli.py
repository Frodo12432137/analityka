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
from .model import SelectionConfig, SelectionResult
from .allocation_plan import atomic_json, check_domain, create_plan, load_plan
from .quality import assess_quality, training_data
from .portfolio_data import (
    allocate_branch_targets,
    allocate_group_quotas,
    discover_workbook_branches,
    inspect_workbook_clients,
    merge_selection_data,
)
from .portfolio_report import BranchOutput, write_portfolio_workbook
from .replacement import ReplacementResult, choose_unique_reserves
from .solver import NoFeasibleSolutionError, SolverUnavailableError, solve_selection
from .runtime import MAX_RUN_SECONDS, RunBudget, RunTimeLimitError, TIMEOUT_EXIT_CODE, configured_seconds


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
        default=[],
        type=Path,
        help="Skoroszyt modelu głównego; parametr można podać wielokrotnie.",
    )
    parser.add_argument("--consents", required=True, type=Path, help="Aktualny plik zgód XLSX.")
    parser.add_argument("--osd-mapping", type=Path, help="Pierwotny plik zgód z PPE i OSD; tylko mapowanie dla nowej listy.")
    parser.add_argument("--no-reserves", action="store_true", help="Ocena małej puli bez rezerwowania PPE na zastępców.")
    parser.add_argument("--output", type=Path, help="Wynikowy skoroszyt XLSX.")
    parser.add_argument(
        "--total-clients",
        default=None,
        type=int,
        help="Dokładna łączna liczba klientów podstawowych: od 1 do 1100 (domyślnie 1100); ograniczona dostępną pulą.",
    )
    parser.add_argument("--groups", type=int, default=4, help="Liczba grup na OSD.")
    parser.add_argument("--max-share", type=float, default=0.20)
    parser.add_argument("--time-limit", type=float, default=None, help="Opcjonalny dodatkowy limit grupy w sekundach. Domyślnie automatyczny podział całego budżetu.")
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument("--total-time-limit", type=float, default=MAX_RUN_SECONDS, help="Limit całości w sekundach (maks. 24 h).")
    timing.add_argument("--finish-by", help="Termin raportu: RRRR-MM-DD GG:MM, czas lokalny komputera (do 24 h).")
    timing.add_argument("--no-time-limit", action="store_true", help="Bez limitu globalnego i limitu grup.")
    parser.add_argument("--branches", action="append", help="Wybrany OSD; można podać wielokrotnie. Pominięcie oznacza wszystkie.")
    parser.add_argument("--allocation-plan", type=Path, help="Stały plan JSON. Pierwsze utworzenie wymaga danych wszystkich 8 OSD.")
    parser.add_argument("--plan-only", action="store_true", help="Przygotuj/sprawdź plan przydziałów bez optymalizacji.")
    parser.add_argument("--holdout-days", type=int, default=0, help="Ostatnie N dostępnych dni do niezależnego testu (domyślnie brak).")
    parser.add_argument("--mip-gap", type=float, default=0.10)
    parser.add_argument("--reserve-shortlist", type=int, default=128)
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
    validation_run = args.validate_only or args.validate_full or args.plan_only
    started = time.monotonic()
    try:
        seconds = configured_seconds(args)
        budget = RunBudget(seconds, deadline)
        plan = load_plan(args.allocation_plan) if args.allocation_plan and args.allocation_plan.exists() else None
        selected_keys = tuple(dict.fromkeys(canonical_branch(key) for key in args.branches)) if args.branches else None
    except ValueError as exc:
        parser.error(str(exc))
    except OSError as exc:
        parser.error(f"Nie można odczytać planu: {exc}")
    args.total_clients = args.total_clients if args.total_clients is not None else (plan["total_clients"] if plan else 1100)
    if plan and args.total_clients != plan["total_clients"]:
        parser.error("Liczba klientów różni się od zapisanego planu. Wskaż nową nazwę planu dla nowego podziału.")
    if plan and (not args.no_reserves) != plan.get("with_reserves", True):
        parser.error("Tryb zastępców różni się od zapisanego planu. Użyj zgodnego trybu albo nowego planu.")
    if plan and args.osd_mapping is None and plan.get("osd_mapping"):
        args.osd_mapping = Path(plan["osd_mapping"])
    if (selected_keys or args.plan_only) and not args.allocation_plan:
        parser.error("Wybór oddziałów i tryb planu wymagają --allocation-plan.")
    if not args.input and plan:
        args.input = list(dict.fromkeys(Path(path) for key in (selected_keys or BRANCH_ORDER)
                                      for path in plan["branches"][key]["sources"]))
    if not args.input:
        parser.error("Dodaj pliki --input albo wskaż istniejący --allocation-plan.")
    if args.holdout_days < 0:
        parser.error("--holdout-days nie może być ujemne.")
    if not 1 <= args.total_clients <= 1100:
        parser.error("--total-clients musi należeć do przedziału 1–1100.")
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
        if args.osd_mapping:
            forbidden.add(args.osd_mapping.resolve())
        if args.output.resolve() in forbidden:
            parser.error("Wynik nie może zastąpić pliku wejściowego ani pliku zgód.")
        if args.allocation_plan and args.output.resolve() == args.allocation_plan.resolve():
            parser.error("Wynik nie może zastąpić planu.")
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
        consents = load_consent_workbook(args.consents, args.osd_mapping)
        print(f"Zgody: {consents.source_rows} wierszy, {consents.unique_count} unikalnych PPE, "
              f"{consents.corrected_rows} korekt, {consents.duplicate_rows} duplikatów.", flush=True)
        sources = _source_map(args.input)
        needed = selected_keys or BRANCH_ORDER
        missing = [key for key in (needed if plan else BRANCH_ORDER) if key not in sources]
        if missing and (not args.allow_partial or args.allocation_plan):
            raise ValueError(
                "Brakuje plików dla OSD: "
                + ", ".join(BRANCH_LABELS[key] for key in missing)
            )
        if plan and selected_keys:
            sources = OrderedDict((key, sources[key]) for key in selected_keys)
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
                print(f"Kontrola list: {path.name} ({BRANCH_LABELS[key]})...", flush=True)
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
        domains = {key: consent_clients[key] - exclusions[key] for key in sources}
        if plan:
            for key in sources:
                check_domain(plan, key, domains[key])
        elif args.allocation_plan:
            plan = create_plan(domains, args.total_clients, sources, args.consents,
                               with_reserves=not args.no_reserves, osd_mapping=args.osd_mapping)
            atomic_json(args.allocation_plan, plan)
            print(f"Zapisano stały plan podziału: {args.allocation_plan}", flush=True)
        branch_targets = ({key: row["target"] for key, row in plan["branches"].items()} if plan else
                          allocate_branch_targets(eligible_counts, args.total_clients,
                                                  with_reserves=not args.no_reserves))
        for key in sources:
            if len(required[key]) > branch_targets[key]:
                raise ValueError(
                    f"{BRANCH_LABELS[key]}: liczba klientów wymaganych przekracza "
                    "przydzielony limit."
                )
        print(
            "Podział celu: "
            + ", ".join(
                f"{BRANCH_LABELS[key]}={branch_targets[key]}" for key in branch_targets
            ),
            flush=True,
        )
        for key in sources:
            print(
                f"  {BRANCH_LABELS[key]}: {len(source_clients[key])} PPE w źródłach, "
                f"{len(consent_clients[key])} ze zgodą, {eligible_counts[key]} po wykluczeniach; "
                f"wybór {branch_targets[key]} + {0 if args.no_reserves else branch_targets[key]} zastępców.", flush=True,
            )
        if args.validate_only or args.plan_only:
            print("Kontrola list zakończona. Profile i formuły nie były sprawdzane; użyj --validate-full.")
            return 0

        if selected_keys:
            sources = OrderedDict((key, sources[key]) for key in selected_keys)
        scope_target = sum(branch_targets[key] for key in sources)
        uncovered = [key for key in sources if branch_targets[key] == 0]
        coverage = {BRANCH_LABELS[key]: {
            "PPE_w_aktualnej_liscie": len(consents.by_branch[key]),
            "PPE_z_profilem": len(consent_clients[key]),
            "PPE_po_wykluczeniach": eligible_counts[key],
            "cel": branch_targets[key],
            "status": "Brak kandydatów — bilans nie jest oceniony" if key in uncovered else "Objęty obliczeniami",
        } for key in sources}
        if uncovered:
            print("UWAGA: brak kandydatów dla OSD: " + ", ".join(BRANCH_LABELS[key] for key in uncovered)
                  + ". Raport nie ocenia pełnego portfela.", flush=True)
        sources = OrderedDict((key, entries) for key, entries in sources.items() if branch_targets[key] > 0)
        if not sources:
            raise ValueError("Wybrane OSD nie mają kandydatów; brak bilansu do oceny.")
        if not validation_run:
            print(
                f"Budżet solvera: {len(sources)} OSD × {args.groups} grup; "
                + ("bez limitu czasu." if seconds is None else f"całość do {seconds / 3600:.2f} h, z rezerwą na zastępców i raport.")
                + f" Cel tego przebiegu: {scope_target} podstawowych + {0 if args.no_reserves else scope_target} zastępców.", flush=True,
            )

        outputs = []
        checkpoint_dir = None
        completed_groups = 0
        total_groups = len(sources) * args.groups

        def group_time_limit():
            group_seconds = budget.group_seconds(args.time_limit, total_groups - completed_groups)
            print("  Solve bez limitu." if group_seconds is None else
                  f"  Limit tego solve: {group_seconds:.1f} s; do końca całości {budget.remaining() / 3600:.2f} h.", flush=True)
            return group_seconds

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
                "limit_calego_przebiegu_s": seconds if seconds is not None else "bez limitu",
                "maksymalny_limit_grupy_s": args.time_limit,
                "uplynelo_przed_zapisem_s": round(time.monotonic() - started, 2),
                "cel_calego_portfela": args.total_clients,
                "cel_wybranych_OSD": scope_target,
                "wybrane_OSD": ", ".join(BRANCH_LABELS[key] for key in sources),
                "plan_id": plan["plan_id"] if plan else "bez zapisanego planu",
                "termin_raportu": args.finish_by or "budżet od startu",
                "dni_testowe": args.holdout_days,
                "liczba_grup_na_OSD": args.groups,
                "kandydatow_na_zastepce": args.reserve_shortlist,
                "dobor_zastepcow": not args.no_reserves,
                "plik_aktualnych_zgod": str(args.consents),
                "plik_mapowania_OSD": str(args.osd_mapping) if args.osd_mapping else "OSD w aktualnych zgodach",
                "OSD_bez_kandydatow": ", ".join(BRANCH_LABELS[key] for key in uncovered),
                "pokrycie_OSD": coverage,
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
            fit_data, test_days = training_data(data, args.holdout_days)
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
                del fit_data
                gc.collect()
                continue
            completed = []
            group_dir = Path(tempfile.mkdtemp(prefix=f"{args.output.stem}_grupy_{key}_", dir=args.output.parent))

            def save_group(group):
                group_complete(group)
                completed.append(group)
                partial_selection = SelectionResult(
                    branch=fit_data.branch, periods=fit_data.periods, branch_balance=fit_data.branch_balance,
                    config=config, groups=tuple(completed), required_weights=fit_data.required_weights,
                    excluded=fit_data.excluded,
                )
                atomic_json(group_dir / f"{key}_{group.group}.json", {
                    "branch": key, "group": group.group, "plan_id": plan["plan_id"] if plan else None,
                    "selected_weights": dict(group.selected_weights), "objective_L1": group.objective_value,
                    "status": group.status_text, "reserves_complete": False,
                })
                empty = ReplacementResult(matches=(), diagnostics=())
                partial_output = BranchOutput(
                    selection=partial_selection, replacements=empty,
                    source_files=tuple(path.name for path, _ in entries),
                    source_clients=len(source_clients[key]), consent_clients=len(consent_clients[key]),
                    legacy_excluded=len(exclusions[key]), eligible_clients=eligible_counts[key],
                    target_clients=branch_total, quality=assess_quality(data, partial_selection, empty, test_days,
                                                                      with_reserves=not args.no_reserves),
                    with_reserves=not args.no_reserves,
                )
                saved = write_portfolio_workbook(
                    [partial_output], group_dir / f"{key}_{group.group}.xlsx", branch_total,
                    partial=True, run_metadata=run_metadata(), allocation_plan=plan,
                )
                print(f"  Zapis grupy: {saved} (podstawowi).", flush=True)

            selection = solve_selection(
                fit_data,
                config,
                on_group_start=lambda name, position, total: print(
                    f"  Solver {name} ({position}/{total})...", flush=True
                ),
                on_group_complete=save_group,
                time_limit_provider=group_time_limit,
            )
            if selection.selected_count != branch_total:
                raise RuntimeError(
                    f"{label}: wybrano {selection.selected_count}, oczekiwano {branch_total}."
                )
            budget.check()
            replacements = ReplacementResult(matches=(), diagnostics=())
            if not args.no_reserves:
                print(f"  Dobór {branch_total} unikalnych zastępców...", flush=True)
                replacements = choose_unique_reserves(
                    fit_data, selection, initial_shortlist=args.reserve_shortlist,
                    check_budget=budget.check,
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
                    quality=assess_quality(data, selection, replacements, test_days, with_reserves=not args.no_reserves),
                    with_reserves=not args.no_reserves,
                )
            )
            budget.check()
            if checkpoint_dir is None:
                checkpoint_dir = Path(tempfile.mkdtemp(prefix=f"{args.output.stem}_czesci_", dir=args.output.parent))
                print(f"  Raporty częściowe OSD: {checkpoint_dir}", flush=True)
            checkpoint = write_portfolio_workbook(
                [outputs[-1]], checkpoint_dir / f"{key}.xlsx", branch_total,
                partial=True, run_metadata=run_metadata(), allocation_plan=plan,
            )
            print(f"  Zapisano ukończony OSD (nie cały portfel): {checkpoint}", flush=True)
            del data
            del fit_data
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
            scope_target,
            overwrite=args.overwrite,
            run_metadata=run_metadata(),
            allocation_plan=plan,
        )
    except RunTimeLimitError as exc:
        print(f"STOP: {exc} Sprawdź raporty *_czesci_* i *_grupy_*; pełny wynik może nie istnieć.", flush=True)
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
