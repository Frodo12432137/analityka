from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .legacy_excel import load_gams_workbook
from .model import SelectionConfig
from .report import validate_report_capacity, write_result_workbook
from .solver import NoFeasibleSolutionError, SolverUnavailableError, solve_selection


def _preflight_output_directory(path: Path, overwrite: bool) -> None:
    """Sprawdza możliwość zapisu przed potencjalnie wielogodzinnym solve."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, probe_name = tempfile.mkstemp(
        prefix=".representative-clients-write-test-", dir=path.parent
    )
    os.close(descriptor)
    Path(probe_name).unlink()
    if path.exists() and overwrite:
        # Na Windows Excel zwykle blokuje otwarty skoroszyt przed zapisem.
        descriptor = os.open(path, os.O_RDWR)
        os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wybór reprezentatywnych klientów — odpowiednik GAMS v8."
    )
    parser.add_argument("--input", required=True, type=Path, help="Wejściowy XLSX Marka.")
    parser.add_argument("--output", type=Path, help="Docelowy plik XLSX z wynikiem.")
    parser.add_argument("--branch", help="Nazwa oddziału, np. PGED_Zamosc.")
    parser.add_argument("--max-clients", type=int, default=50, help="Limit na grupę.")
    parser.add_argument("--groups", type=int, default=4, help="Liczba grup round-robin.")
    parser.add_argument(
        "--max-share",
        type=float,
        default=0.20,
        help=(
            "Maksymalny bezwzględny udział pojedynczego klienta względem "
            "średniego |bilansu| (domyślnie 0.20)."
        ),
    )
    parser.add_argument("--time-limit", type=float, default=14_400.0, help="Sekundy na grupę.")
    parser.add_argument(
        "--mip-gap",
        type=float,
        default=0.10,
        help="Dopuszczalna względna luka MIP (domyślnie 0.10 jak GAMS v8).",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Wyłącz wyłącznie numeryczne skalowanie równań bilansu.",
    )
    parser.add_argument(
        "--solver-log", action="store_true", help="Pokaż szczegółowy log HiGHS."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Wczytaj i sprawdź cały XLSX, ale nie uruchamiaj solvera ani eksportu.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Świadomie zastąp istniejący wynik; nigdy nie zastępuje wejścia.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = SelectionConfig(
        max_clients_per_group=args.max_clients,
        group_count=args.groups,
        max_contribution_share=args.max_share,
        time_limit_seconds=args.time_limit,
        mip_relative_gap=args.mip_gap,
        normalize_balance=not args.no_normalize,
        solver_display=args.solver_log,
    )
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))

    if not args.validate_only:
        if args.output is None:
            raise SystemExit("Przy uruchomieniu solvera wymagany jest parametr --output.")
        if args.output.suffix.lower() != ".xlsx":
            raise SystemExit("Plik wynikowy musi mieć rozszerzenie .xlsx.")
        if args.input.resolve() == args.output.resolve():
            raise SystemExit("Plik wejściowy i wynikowy nie mogą być tym samym plikiem.")
        if args.output.exists() and not args.overwrite:
            raise SystemExit(
                f"Plik {args.output} już istnieje. Wybierz inną nazwę albo użyj --overwrite."
            )
        try:
            _preflight_output_directory(args.output, args.overwrite)
        except (PermissionError, OSError) as exc:
            parser.exit(1, f"BŁĄD KATALOGU LUB PLIKU WYNIKOWEGO: {exc}\n")

    try:
        data = load_gams_workbook(
            args.input,
            branch=args.branch,
            on_stage=lambda message: print(f"Wejście: {message}", flush=True),
        )
    except MemoryError as exc:
        parser.exit(1, f"BŁĄD PAMIĘCI PODCZAS ODCZYTU: {exc}\n")
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"BŁĄD DANYCH: {exc}\n")
    print(
        f"Wczytano {data.branch}: {len(data.client_ids)} klientów, "
        f"{len(data.periods)} okresów, {len(data.excluded)} wykluczonych, "
        f"{len(data.required_weights)} wymaganych."
    )
    profile_gibibytes = np.asarray(data.client_balance).nbytes / 1024**3
    print(
        f"Macierz profili: {len(data.periods)} x {len(data.client_ids)}, "
        f"{profile_gibibytes:.3f} GiB w pamięci przed solverem."
    )
    try:
        validate_report_capacity(data, config)
    except ValueError as exc:
        parser.exit(1, f"BŁĄD FORMATU RAPORTU: {exc}\n")
    if args.validate_only:
        maximum_hours = config.group_count * config.time_limit_seconds / 3600.0
        print(
            f"Konfiguracja: {config.group_count} grup, do "
            f"{config.max_clients_per_group} klientów na grupę; maksymalny łączny "
            f"czas solvera {maximum_hours:g} h."
        )
        print("Walidacja danych zakończona poprawnie; solver nie został uruchomiony.")
        return 0

    maximum_hours = config.group_count * config.time_limit_seconds / 3600.0
    print(
        f"Start optymalizacji {config.group_count} grup. Maksymalny łączny "
        f"czas wynikający z limitów: {maximum_hours:g} h."
    )
    try:
        result = solve_selection(
            data,
            config,
            on_group_start=lambda name, position, total: print(
                f"Rozwiązywanie {name} ({position}/{total})...", flush=True
            ),
        )
    except (MemoryError, NoFeasibleSolutionError, SolverUnavailableError, ValueError) as exc:
        parser.exit(1, f"BŁĄD SOLVERA: {exc}\n")
    for group in result.groups:
        print(
            f"{group.group}: wybrano {len(group.selected_weights)}/"
            f"{len(group.candidate_ids)}, L1={group.objective_value:.6g}, "
            f"status={group.status_text}"
        )
    try:
        output = write_result_workbook(
            data, result, args.output, overwrite=args.overwrite
        )
    except (FileExistsError, PermissionError, OSError, ValueError) as exc:
        parser.exit(1, f"BŁĄD ZAPISU: {exc}\n")
    print(f"Zapisano wynik: {output}")
    if any(not group.optimal for group in result.groups):
        print(
            "UWAGA: co najmniej jedna grupa zakończyła się przed potwierdzeniem "
            "optymalności. Szczegóły są w arkuszu Diagnostyka."
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
