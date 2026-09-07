"""Otwórz ten plik w VS Code i kliknij ▶ Run Python File in Terminal.

Dane i tryb pracy wybierasz w oknie; nie trzeba edytować ścieżek w kodzie.
Instrukcja: START_KLIENCI_REPREZENTATYWNI.md obok tego pliku.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import struct
import sys
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent
MODES = ("Sprawdzenie wszystkich danych", "Próba: 60 sekund na grupę", "Pełne obliczenia")


def check_environment() -> None:
    if sys.version_info < (3, 10) or struct.calcsize("P") != 8:
        raise RuntimeError("Wybierz w VS Code interpreter Python 3.10+ w wersji 64-bitowej.")
    try:
        for name in ("numpy", "pandas", "openpyxl", "scipy.optimize", "tkinter"):
            importlib.import_module(name)
        from scipy.optimize import milp  # noqa: F401 — sprawdzenie dostępności solvera
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            f"Wybrany Python: {sys.executable}\n"
            f"Nie można załadować zależności: {exc}\n"
            "W terminalu PowerShell uruchom dla TEGO interpretera:\n"
            f'& "{sys.executable}" -m pip install -r "{PROJECT_DIR / "representative_clients" / "requirements.txt"}"\n'
            "Jeżeli brakuje tkinter, doinstaluj składnik Tcl/Tk w instalatorze Pythona.\n"
            "Instrukcja wyboru interpretera: START_KLIENCI_REPREZENTATYWNI.md."
        ) from exc


def choose_run() -> tuple[list[str], Path] | None:
    from tkinter import Tk, StringVar, Listbox, END, filedialog, messagebox, ttk

    input_dir = PROJECT_DIR / "Dane_in" / "Modele"
    consent_dir = PROJECT_DIR / "Dane_in" / "Zgody"
    output_dir = PROJECT_DIR / "Dane_out"
    for directory in (input_dir, consent_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)

    root = Tk()
    root.title("Klienci reprezentatywni — źródła i uruchomienie")
    root.geometry("900x700")
    root.minsize(820, 650)
    root.columnconfigure(0, weight=1)
    panel = ttk.Frame(root, padding=18)
    panel.grid(sticky="nsew")
    panel.columnconfigure(0, weight=1)
    sources: list[str] = []
    consent = StringVar()
    destination = StringVar(value=str(output_dir))
    total = StringVar(value="1100")
    mode = StringVar(value=MODES[0])
    minutes = StringVar(value="30")
    hours = StringVar(value="24")
    result = None

    ttk.Label(panel, text="1. Pliki źródłowe modelu głównego dla wszystkich 8 OSD").grid(sticky="w")
    ttk.Label(
        panel,
        text="XLSX: Klienci, Klienci_part_1, Klienci_part_2, Oddzial/Oddział, Ograniczenia.",
        wraplength=770,
    ).grid(sticky="w", pady=(2, 5))
    listing = Listbox(panel, height=7, selectmode="extended")
    listing.grid(sticky="ew")
    buttons = ttk.Frame(panel)
    buttons.grid(sticky="w", pady=5)

    def add_sources() -> None:
        paths = filedialog.askopenfilenames(
            parent=root, title="Dodaj pliki modeli głównych", initialdir=str(input_dir),
            filetypes=[("Skoroszyty Excel", "*.xlsx")],
        )
        for path in paths:
            resolved = str(Path(path).resolve())
            if resolved not in sources:
                sources.append(resolved)
                listing.insert(END, resolved)

    def remove_sources() -> None:
        for index in reversed(listing.curselection()):
            del sources[index]
            listing.delete(index)

    ttk.Button(buttons, text="Dodaj pliki…", command=add_sources).pack(side="left")
    ttk.Button(buttons, text="Usuń zaznaczone", command=remove_sources).pack(side="left", padx=8)

    def path_row(label: str, variable: StringVar, select) -> None:
        ttk.Label(panel, text=label).grid(sticky="w", pady=(8, 3))
        row = ttk.Frame(panel)
        row.grid(sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Wybierz…", command=select).grid(row=0, column=1, padx=(6, 0))

    def choose_consents() -> None:
        path = filedialog.askopenfilename(
            parent=root, title="Aktualny plik zgód", initialdir=str(consent_dir),
            filetypes=[("Skoroszyty Excel", "*.xlsx")],
        )
        if path:
            consent.set(path)

    def choose_output() -> None:
        path = filedialog.askdirectory(parent=root, title="Folder wyników", initialdir=str(output_dir))
        if path:
            destination.set(path)

    path_row("2. Aktualny plik zgód marketingowych (.xlsx)", consent, choose_consents)
    path_row("3. Folder wyników i dziennika uruchomienia", destination, choose_output)
    settings = ttk.Frame(panel)
    settings.grid(sticky="ew", pady=12)
    ttk.Label(settings, text="Klienci podstawowi łącznie (500–1100):").grid(row=0, column=0, sticky="w")
    ttk.Entry(settings, textvariable=total, width=9).grid(row=0, column=1, sticky="w", padx=10)
    ttk.Label(settings, text="Tryb pracy:").grid(row=1, column=0, sticky="w", pady=8)
    ttk.Combobox(settings, textvariable=mode, values=MODES, state="readonly", width=34).grid(row=1, column=1, sticky="w")
    ttk.Label(settings, text="Pełne obliczenia: limit minut NA GRUPĘ:").grid(row=2, column=0, sticky="w")
    ttk.Entry(settings, textvariable=minutes, width=9).grid(row=2, column=1, sticky="w", padx=10)
    ttk.Label(settings, text="Limit godzin CAŁEGO przebiegu (maks. 24):").grid(row=3, column=0, sticky="w", pady=8)
    ttk.Entry(settings, textvariable=hours, width=9).grid(row=3, column=1, sticky="w", padx=10)
    ttk.Label(
        panel,
        text="Całość maks. 24 h: odczyt + model + zastępcy + zapis. Może skończyć wcześniej.\n"
             "Domyślnie grupy do 30 min (łącznie do 16 h solvera); pozostałe etapy też w limicie.\n"
             "Sprawdzenie: bez solvera. Próba: grupy do 60 s. Raporty OSD zapisywane na bieżąco.\n"
             "Postęp zobaczysz w terminalu VS Code; dziennik trafi do folderu wyników.",
        wraplength=770,
    ).grid(sticky="w", pady=8)

    def start() -> None:
        nonlocal result
        try:
            number = int(total.get())
            full_minutes = float(minutes.get().replace(",", "."))
            total_hours = float(hours.get().replace(",", "."))
            if not 500 <= number <= 1100:
                raise ValueError("Liczba klientów musi należeć do przedziału 500–1100.")
            if not 0 < full_minutes <= 1440:
                raise ValueError("Limit grupy musi być większy od zera i nie większy od 1440 minut.")
            if not 0 < total_hours <= 24:
                raise ValueError("Limit całego przebiegu musi być większy od zera i nie większy od 24 godzin.")
            if not sources:
                raise ValueError("Dodaj skoroszyty modeli głównych dla 8 OSD.")
            for path in sources + [consent.get()]:
                if not Path(path).is_file() or Path(path).suffix.lower() != ".xlsx":
                    raise ValueError(f"Wskaż istniejący plik .xlsx: {path!r}.")
            if not destination.get().strip():
                raise ValueError("Wskaż folder wyników.")
            folder = Path(destination.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            arguments = []
            for path in sources:
                arguments.extend(("--input", path))
            arguments.extend(("--consents", str(Path(consent.get()).resolve()), "--total-clients", str(number)))
            arguments.extend(("--total-time-limit", str(total_hours * 3600)))
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            if mode.get() == MODES[0]:
                arguments.append("--validate-full")
                name = "walidacja"
            else:
                trial = mode.get() == MODES[1]
                name = "proba" if trial else "pelny"
                arguments.extend((
                    "--output", str(folder / f"Wyniki_{name}_{stamp}.xlsx"),
                    "--time-limit", str(60 if trial else full_minutes * 60),
                    "--solver-log",
                ))
            result = (arguments, folder / f"Przebieg_{name}_{stamp}.log")
            root.destroy()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Sprawdź ustawienia", str(exc), parent=root)

    ttk.Button(panel, text="Uruchom", command=start).grid(sticky="e", pady=6)
    root.mainloop()
    return result


def execute_run(arguments: list[str], log_path: Path) -> int:
    """Uruchamia ten sam Python, przekazuje też natywny log HiGHS do terminala."""
    from representative_clients.runtime import run_portfolio
    print(f"Dziennik: {log_path}\nPrzerwanie: Ctrl+C w terminalu.", flush=True)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"Start: {datetime.now().isoformat()}\nPython: {sys.executable}\n")
        log.write(f"Argumenty: {arguments!r}\n")
        log.flush()
        def record(line):
            print(line, end="", flush=True)
            log.write(line)
            log.flush()

        code = run_portfolio(arguments, on_line=record)
        has_output = (
            "--output" in arguments
            and Path(arguments[arguments.index("--output") + 1]).is_file()
        )
        message = {
            0: "Zakończono poprawnie.",
            124: "Osiągnięto budżet czasu całości. Sprawdź raporty ukończonych OSD w *_czesci_*; nie są pełnym wynikiem.",
            130: "Przerwano obliczenia. Sprawdź dziennik; pełny wynik może nie istnieć.",
        }.get(code, f"Błąd (kod {code}). Szczegóły powyżej i w dzienniku.")
        if code == 2 and has_output:
            message = "Wynik zapisany z zastrzeżeniem: osiągnięto limit solvera. Sprawdź arkusz Solver."
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
