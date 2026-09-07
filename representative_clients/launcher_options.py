"""Walidacja ustawień okna, także bez uruchamiania Tk w testach."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .allocation_plan import load_plan
from .consent import BRANCH_ORDER, canonical_branch
from .portfolio_cli import build_parser
from .runtime import configured_seconds


TIME_MODES = ("Gotowy raport do wskazanej daty i godziny", "Budżet godzin od uruchomienia", "Bez limitu czasu")


def build_run_arguments(*, sources, consents, destination, plan_path, total, branches,
                        mode, time_mode, hours="12", finish_by="", group_minutes="",
                        holdout_days="0", shortlist="128", now=None):
    total = int(total)
    if not 500 <= total <= 1100:
        raise ValueError("Cel całego portfela musi należeć do przedziału 500–1100.")
    keys = tuple(dict.fromkeys(canonical_branch(key) for key in branches))
    if not keys:
        raise ValueError("Zaznacz co najmniej jeden oddział.")
    plan = Path(plan_path).expanduser().resolve()
    if plan.suffix.lower() != ".json":
        raise ValueError("Plan podziału musi mieć rozszerzenie .json.")
    existing = load_plan(plan) if plan.is_file() else None
    if existing and total != existing["total_clients"]:
        raise ValueError("Cel różni się od zapisanego planu. Dla nowego celu wskaż nowy plik planu.")
    paths = [Path(path).expanduser().resolve() for path in sources]
    if not paths and not existing:
        raise ValueError("Dodaj pliki wszystkich 8 OSD do przygotowania pierwszego planu.")
    for path in [*paths, Path(consents).expanduser()]:
        if not path.is_file() or path.suffix.lower() != ".xlsx":
            raise ValueError(f"Wskaż istniejący plik XLSX: {path}.")
    folder = Path(destination).expanduser().resolve()
    arguments = []
    for path in paths:
        arguments.extend(("--input", str(path)))
    arguments.extend(("--consents", str(Path(consents).expanduser().resolve()),
                      "--total-clients", str(total), "--allocation-plan", str(plan)))
    if set(keys) != set(BRANCH_ORDER):
        for key in keys:
            arguments.extend(("--branches", key))
    if time_mode == TIME_MODES[0]:
        arguments.extend(("--finish-by", finish_by.strip()))
    elif time_mode == TIME_MODES[1]:
        arguments.extend(("--total-time-limit", str(float(str(hours).replace(",", ".")) * 3600)))
    elif time_mode == TIME_MODES[2]:
        arguments.append("--no-time-limit")
    else:
        raise ValueError("Wybierz sposób ustawienia czasu.")
    holdout, shortlist = int(holdout_days), int(shortlist)
    if holdout < 0 or shortlist < 1:
        raise ValueError("Liczba dni testu musi być nieujemna, a liczba kandydatów na zastępcę dodatnia.")
    arguments.extend(("--holdout-days", str(holdout), "--reserve-shortlist", str(shortlist)))
    name = {"plan": "plan", "validate": "walidacja", "trial": "proba", "full": "pelny"}[mode]
    if mode == "plan":
        arguments.append("--plan-only")
    elif mode == "validate":
        arguments.append("--validate-full")
    else:
        if mode == "trial" and time_mode == TIME_MODES[2]:
            raise ValueError("Próba ma limit 60 s na grupę; wybierz budżet godzin lub termin.")
        if mode == "trial":
            arguments.extend(("--time-limit", "60"))
        elif str(group_minutes).strip():
            cap = float(str(group_minutes).replace(",", ".")) * 60
            if not 0 < cap <= 86400:
                raise ValueError("Opcjonalny limit grupy musi być dodatni i nie większy niż 1440 minut.")
            arguments.extend(("--time-limit", str(cap)))
        stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
        arguments.extend(("--output", str(folder / f"Wyniki_{name}_{stamp}.xlsx"), "--solver-log"))
    configured_seconds(build_parser().parse_args(arguments), now=now)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return arguments, folder / f"Przebieg_{name}_{stamp}.log"
