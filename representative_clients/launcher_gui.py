"""Okno konfiguracji; nie wykonuje obliczeń przed naciśnięciem Uruchom."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .allocation_plan import load_plan
from .consent import BRANCH_ORDER, BRANCH_LABELS
from .launcher_options import TIME_MODES, build_run_arguments

MODES = ("Sprawdzenie danych", "Próba: 60 sekund na grupę", "Pełne obliczenia", "Przygotowanie / sprawdzenie planu")


def choose_run(project_dir):
    from tkinter import Tk, StringVar, BooleanVar, Listbox, END, filedialog, messagebox, ttk

    input_dir, consent_dir, output_dir = (project_dir / "Dane_in" / "Modele",
                                         project_dir / "Dane_in" / "Zgody", project_dir / "Dane_out")
    for directory in (input_dir, consent_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)
    root = Tk()
    root.title("Klienci reprezentatywni — oddziały, termin i jakość")
    root.geometry("940x800")
    root.minsize(830, 760)
    tabs = ttk.Notebook(root)
    tabs.pack(fill="both", expand=True, padx=12, pady=12)
    source_panel, run_panel, quality_panel = (ttk.Frame(tabs, padding=14) for _ in range(3))
    for panel, title in ((source_panel, "1. Dane i plan"), (run_panel, "2. Oddziały i czas"),
                         (quality_panel, "3. Ocena jakości")):
        tabs.add(panel, text=title)
        panel.columnconfigure(0, weight=1)
    sources = []
    consent = StringVar()
    osd_mapping = StringVar()
    with_reserves = BooleanVar(value=True)
    groups = StringVar(value="4")
    destination = StringVar(value=str(output_dir))
    plan_path = StringVar(value=str(output_dir / "Plan_1100.json"))
    total, mode = StringVar(value="1100"), StringVar(value=MODES[2])
    time_mode = StringVar(value=TIME_MODES[0])
    hours, minutes = StringVar(value="12"), StringVar(value="")
    tomorrow = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    if tomorrow <= datetime.now():
        tomorrow += timedelta(days=1)
    finish = StringVar(value=tomorrow.strftime("%Y-%m-%d %H:%M"))
    holdout, shortlist = StringVar(value="0"), StringVar(value="128")
    plan_note = StringVar(value="Pierwszy plan wymaga plików wszystkich 8 OSD. Później możesz liczyć oddziały osobno.")
    result = None

    ttk.Label(source_panel, text="Pliki modeli XLSX: Klienci / części profili, Oddzial i Ograniczenia.").grid(sticky="w")
    listing = Listbox(source_panel, height=7, selectmode="extended", exportselection=False)
    listing.grid(sticky="ew", pady=6)

    def add_sources():
        for path in filedialog.askopenfilenames(parent=root, initialdir=str(input_dir), filetypes=[("Excel", "*.xlsx")]):
            if path not in sources:
                sources.append(path)
                listing.insert(END, path)

    def remove_sources():
        for index in reversed(listing.curselection()):
            sources.pop(index)
            listing.delete(index)

    actions = ttk.Frame(source_panel)
    actions.grid(sticky="w")
    ttk.Button(actions, text="Dodaj pliki…", command=add_sources).pack(side="left")
    ttk.Button(actions, text="Usuń zaznaczone", command=remove_sources).pack(side="left", padx=8)

    def path_row(panel, label, variable, choose):
        ttk.Label(panel, text=label).grid(sticky="w", pady=(9, 2))
        row = ttk.Frame(panel)
        row.grid(sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Wybierz…", command=choose).grid(row=0, column=1, padx=6)

    def choose_consents():
        value = filedialog.askopenfilename(parent=root, initialdir=str(consent_dir), filetypes=[("Excel", "*.xlsx")])
        if value:
            consent.set(value)

    def choose_output():
        value = filedialog.askdirectory(parent=root, initialdir=str(output_dir))
        if value:
            destination.set(value)

    def choose_mapping():
        value = filedialog.askopenfilename(parent=root, initialdir=str(consent_dir), filetypes=[("Excel", "*.xlsx")])
        if value:
            osd_mapping.set(value)

    def choose_plan():
        value = filedialog.asksaveasfilename(parent=root, title="Wskaż istniejący plan lub nazwę nowego",
                                            initialdir=str(output_dir), defaultextension=".json",
                                            filetypes=[("Stały plan podziału", "*.json")], confirmoverwrite=False)
        if value:
            plan_path.set(value)
            refresh_plan()

    path_row(source_panel, "Aktualny plik zgód", consent, choose_consents)
    path_row(source_panel, "Pierwotny plik zgód — mapowanie OSD (wymagany dla nowej listy PPE)", osd_mapping, choose_mapping)
    path_row(source_panel, "Folder wyników i logów", destination, choose_output)
    path_row(source_panel, "Stały plan podziału (JSON; istniejący albo nowy)", plan_path, choose_plan)
    ttk.Label(source_panel, textvariable=plan_note, wraplength=800).grid(sticky="w", pady=8)
    ttk.Button(source_panel, text="Odczytaj zapisany plan", command=lambda: refresh_plan()).grid(sticky="w")

    ttk.Label(run_panel, text="Oddziały do tego przebiegu (kliknięcie zaznacza lub odznacza):").grid(sticky="w")
    branch_list = Listbox(run_panel, selectmode="multiple", exportselection=False, height=8)
    branch_list.grid(sticky="ew", pady=6)
    for key in BRANCH_ORDER:
        branch_list.insert(END, BRANCH_LABELS[key] + " — przydział po przygotowaniu planu")
    branch_list.selection_set(0)
    buttons = ttk.Frame(run_panel)
    buttons.grid(sticky="w")
    ttk.Button(buttons, text="Wszystkie OSD", command=lambda: branch_list.selection_set(0, END)).pack(side="left")
    ttk.Button(buttons, text="Odznacz wszystkie", command=lambda: branch_list.selection_clear(0, END)).pack(side="left", padx=8)
    settings = ttk.Frame(run_panel)
    settings.grid(sticky="ew", pady=10)
    ttk.Label(settings, text="Tryb pracy").grid(row=0, column=0, sticky="w")
    ttk.Combobox(settings, textvariable=mode, values=MODES, state="readonly", width=39).grid(row=0, column=1, padx=8, pady=4)
    ttk.Label(settings, text="Sposób ustawienia czasu").grid(row=1, column=0, sticky="w")
    ttk.Combobox(settings, textvariable=time_mode, values=TIME_MODES, state="readonly", width=39).grid(row=1, column=1, padx=8, pady=4)
    fields = (("Cel portfela łącznie (1–1100 podstawowych)", total), ("Budżet godzin", hours),
              ("Termin raportu: RRRR-MM-DD GG:MM", finish),
              ("Dodatkowy limit minut na grupę (puste = automatyczny)", minutes),
              ("Liczba niezależnych grup na OSD", groups))
    for row, (label, variable) in enumerate(fields, start=2):
        ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(settings, textvariable=variable, width=24).grid(row=row, column=1, sticky="w", padx=8)
    ttk.Checkbutton(run_panel, text="Dobierz unikalnego zastępcę dla każdego klienta (wymaga podwójnej puli PPE)",
                    variable=with_reserves).grid(sticky="w")
    ttk.Label(run_panel, wraplength=800, text="Termin obejmuje odczyt, solver, zastępców i raport. Czas jest dzielony między grupy. "
              "Bez limitu oznacza również brak ograniczenia 24 h. Komputer musi pozostać włączony i nieusypiany.").grid(sticky="w", pady=8)

    ttk.Label(quality_panel, wraplength=800, text="Raport obejmuje MAE, błąd względny, RMSE, bias, największe odchylenia, "
              "wyniki według dni i godzin, wykresy oraz wpływ podmiany pojedynczego klienta.").grid(sticky="w", pady=8)
    ttk.Label(quality_panel, text="Ostatnie dostępne dni odłożone do testu (0 = brak testu):").grid(sticky="w", pady=(12, 4))
    ttk.Entry(quality_panel, textvariable=holdout, width=10).grid(sticky="w")
    ttk.Label(quality_panel, wraplength=800, text="Te dni nie biorą udziału w doborze klientów, wag ani zastępców. "
              "Muszą pozostać co najmniej 2 dni do dopasowania. Przy 0 raport oznaczy brak niezależnego testu.").grid(sticky="w", pady=8)
    ttk.Label(quality_panel, text="Liczba podobnych kandydatów na zastępcę:").grid(sticky="w", pady=(12, 4))
    ttk.Combobox(quality_panel, textvariable=shortlist, values=("32", "128", "256"), state="readonly", width=10).grid(sticky="w")
    ttk.Label(quality_panel, wraplength=800, text="Każda grupa osobno odtwarza cały bilans oddziału. "
              "Przydział 88 oznacza 4 zestawy po 22; wag zestawów nie sumujemy. "
              "Przy małej puli można wyłączyć zastępców i wybrać 1 grupę, aby wspólnie dopasować dostępne PPE w OSD. "
              "Do porównania wielkości pul zachowaj tę samą liczbę grup i pozostałe parametry.").grid(sticky="w", pady=20)

    def refresh_plan():
        path = Path(plan_path.get()).expanduser()
        if not path.is_file():
            plan_note.set("Nowy plan: dodaj pliki wszystkich 8 OSD. Przydziały zostaną zapisane przed optymalizacją.")
            return
        try:
            plan = load_plan(path)
            indices = branch_list.curselection()
            branch_list.delete(0, END)
            for key in BRANCH_ORDER:
                count = plan["branches"][key]["target"]
                reserves = count if plan.get("with_reserves", True) else 0
                branch_list.insert(END, f"{BRANCH_LABELS[key]} — {count} podstawowych + {reserves} zastępców")
            for index in indices:
                branch_list.selection_set(index)
            total.set(str(plan["total_clients"]))
            with_reserves.set(plan.get("with_reserves", True))
            if not osd_mapping.get():
                osd_mapping.set(plan.get("osd_mapping") or "")
            if not consent.get():
                consent.set(plan.get("consents", ""))
            plan_note.set(f"Plan {plan['plan_id']}: {plan['total_clients']} podstawowych; "
                          f"zastępcy: {'włączeni' if with_reserves.get() else 'wyłączeni'}. "
                          "Przy pustej liście plików program użyje zapisanych ścieżek wybranych OSD.")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Plan podziału", str(exc), parent=root)

    def start():
        nonlocal result
        try:
            chosen_mode = ("validate", "trial", "full", "plan")[MODES.index(mode.get())]
            result = build_run_arguments(
                sources=sources, consents=consent.get(), destination=destination.get(), plan_path=plan_path.get(),
                total=total.get(), branches=[BRANCH_ORDER[i] for i in branch_list.curselection()],
                mode=chosen_mode, time_mode=time_mode.get(), hours=hours.get(), finish_by=finish.get(),
                group_minutes=minutes.get(), holdout_days=holdout.get(), shortlist=shortlist.get(),
                osd_mapping=osd_mapping.get(), with_reserves=with_reserves.get(), groups=groups.get(),
            )
            result[1].parent.mkdir(parents=True, exist_ok=True)
            root.destroy()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Sprawdź ustawienia", str(exc), parent=root)

    footer = ttk.Frame(root, padding=12)
    footer.pack(fill="x")
    ttk.Label(footer, text="Postęp zobaczysz w terminalu VS Code; wyniki i logi w wybranym folderze.").pack(side="left")
    ttk.Button(footer, text="Uruchom", command=start).pack(side="right")
    refresh_plan()
    root.mainloop()
    return result
