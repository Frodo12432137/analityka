"""Otwórz w VS Code i kliknij ▶ Run Python File in Terminal.

W oknie wybierz dane, plan podziału, oddziały i termin. Instrukcja:
START_KLIENCI_REPREZENTATYWNI.md. Obliczenia wykonują się na tym komputerze.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import struct
import sys
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent


def check_environment() -> None:
    if sys.version_info < (3, 10) or struct.calcsize("P") != 8:
        raise RuntimeError("Wybierz w VS Code interpreter Python 3.10+ w wersji 64-bitowej.")
    try:
        for name in ("numpy", "pandas", "openpyxl", "scipy.optimize", "tkinter"):
            importlib.import_module(name)
        from scipy.optimize import milp  # noqa: F401
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            f"Wybrany Python: {sys.executable}\nNie można załadować zależności: {exc}\n"
            "W terminalu PowerShell uruchom dla TEGO interpretera:\n"
            f'& "{sys.executable}" -m pip install -r "{PROJECT_DIR / "representative_clients" / "requirements.txt"}"\n'
            "Jeżeli brakuje tkinter, doinstaluj składnik Tcl/Tk w instalatorze Pythona."
        ) from exc


def choose_run() -> tuple[list[str], Path] | None:
    from representative_clients.launcher_gui import choose_run as choose
    return choose(PROJECT_DIR)


def execute_run(arguments: list[str], log_path: Path) -> int:
    from representative_clients.runtime import run_portfolio
    print(f"Dziennik: {log_path}\nPrzerwanie: Ctrl+C w terminalu.", flush=True)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"Start: {datetime.now().isoformat()}\nPython: {sys.executable}\nArgumenty: {arguments!r}\n")
        log.flush()
        def record(line):
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        code = run_portfolio(arguments, on_line=record)
        has_output = "--output" in arguments and Path(arguments[arguments.index("--output") + 1]).is_file()
        message = {
            0: "Zakończono poprawnie.",
            124: "Osiągnięto budżet czasu. Sprawdź raporty OSD w *_czesci_* i grup w *_grupy_*. Nie wszystkie muszą być kompletne.",
            130: "Przerwano obliczenia. Ukończone grupy/OSD pozostają w *_grupy_* i *_czesci_*.",
        }.get(code, f"Błąd (kod {code}). Szczegóły powyżej i w dzienniku.")
        if code == 2 and has_output:
            message = "Wynik zapisany z zastrzeżeniem: osiągnięto limit solvera. Sprawdź Solver i Reprezentatywnosc."
        print(message, flush=True)
        log.write(f"\nKoniec: {datetime.now().isoformat()}\n{message}\n")
    return code


def run() -> int:
    try:
        check_environment()
        chosen = choose_run()
        if chosen is None:
            print("Anulowano wybór ustawień.")
            return 0
        return execute_run(*chosen)
    except (RuntimeError, OSError) as exc:
        print(f"Nie udało się uruchomić modelu:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
