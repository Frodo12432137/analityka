from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, Tuple

import pandas as pd

from .consent import BRANCH_LABELS, canonical_branch
from .model import SelectionResult
from .replacement import ReplacementResult
from .report import balance_frame, diagnostics_frame, selected_frame


EXCEL_MAX_ROWS = 1_048_576


@dataclass(frozen=True)
class BranchOutput:
    selection: SelectionResult
    replacements: ReplacementResult
    source_files: Tuple[str, ...]
    source_clients: int
    consent_clients: int
    legacy_excluded: int
    eligible_clients: int
    target_clients: int


def _frames(outputs: Sequence[BranchOutput]) -> Mapping[str, pd.DataFrame]:
    selected_parts = [selected_frame(output.selection) for output in outputs]
    balance_parts = [balance_frame(output.selection) for output in outputs]
    solver_parts = [diagnostics_frame(output.selection) for output in outputs]
    replacement_rows = []
    replacement_diagnostics = []
    funnel_rows = []
    summary_rows = []
    for output in outputs:
        key = canonical_branch(output.selection.branch)
        label = BRANCH_LABELS[key]
        for match in output.replacements.matches:
            replacement_rows.append(
                {
                    "OSD": label,
                    "grupa": match.group,
                    "klient_podstawowy": match.primary_id,
                    "waga_podstawowa": match.primary_weight,
                    "klient_zastepczy": match.reserve_id,
                    "waga_zastepcza": match.reserve_weight,
                    "blad_L1_podmiany": match.l1_error,
                    "MAE_podmiany": match.mae,
                    "blad_L1_wzgledny": match.normalized_l1,
                    "korelacja": match.correlation,
                }
            )
        for diagnostic in output.replacements.diagnostics:
            replacement_diagnostics.append(
                {
                    "OSD": label,
                    "grupa": diagnostic.group,
                    "L1_model_podstawowy": diagnostic.l1_primary,
                    "L1_po_podmianie_wszystkich": diagnostic.l1_after_replacement,
                    "MAE_model_podstawowy": diagnostic.mae_primary,
                    "MAE_po_podmianie_wszystkich": diagnostic.mae_after_replacement,
                    "max_blad_model_podstawowy": diagnostic.max_error_primary,
                    "max_blad_po_podmianie": diagnostic.max_error_after_replacement,
                }
            )
        funnel_rows.append(
            {
                "OSD": label,
                "pliki_zrodlowe": "; ".join(output.source_files),
                "klienci_w_modelu_zrodlowym": output.source_clients,
                "PPE_zgodne_z_plikiem_zgod": output.consent_clients,
                "wykluczeni_legacy": output.legacy_excluded,
                "kandydaci_po_filtrach": output.eligible_clients,
                "wybrani": output.selection.selected_count,
                "zastepcy": len(output.replacements.matches),
                "cel_dla_OSD": output.target_clients,
            }
        )
        group_diags = output.replacements.diagnostics
        summary_rows.append(
            {
                "OSD": label,
                "cel": output.target_clients,
                "wybrani": output.selection.selected_count,
                "zastepcy": len(output.replacements.matches),
                "liczba_grup": len(output.selection.groups),
                "wszystkie_rozwiazania_optymalne": all(
                    group.optimal for group in output.selection.groups
                ),
                "srednie_MAE_model": (
                    sum(item.mae_primary for item in group_diags) / len(group_diags)
                    if group_diags
                    else None
                ),
                "srednie_MAE_po_podmianie": (
                    sum(item.mae_after_replacement for item in group_diags)
                    / len(group_diags)
                    if group_diags
                    else None
                ),
            }
        )
    frames = {
        "Podsumowanie": pd.DataFrame(summary_rows),
        "Wybrani": pd.concat(selected_parts, ignore_index=True),
        "Zastepcy": pd.DataFrame(replacement_rows),
        "Bilans": pd.concat(balance_parts, ignore_index=True),
        "Diagnostyka": pd.DataFrame(replacement_diagnostics),
        "Solver": pd.concat(solver_parts, ignore_index=True),
        "Lejek_danych": pd.DataFrame(funnel_rows),
    }
    return frames


def _mail_text(outputs: Sequence[BranchOutput], total_target: int) -> str:
    selected = sum(output.selection.selected_count for output in outputs)
    reserves = sum(len(output.replacements.matches) for output in outputs)
    optimal = sum(
        group.optimal for output in outputs for group in output.selection.groups
    )
    group_count = sum(len(output.selection.groups) for output in outputs)
    distribution = ", ".join(
        f"{BRANCH_LABELS[canonical_branch(output.selection.branch)]}: "
        f"{output.selection.selected_count}"
        for output in outputs
    )
    return (
        "Model klientów reprezentatywnych został uruchomiony po ograniczeniu zbioru "
        "do PPE znajdujących się w aktualnym pliku zgód marketingowych i po "
        "zastosowaniu technicznych wykluczeń z arkuszy wejściowych. "
        f"Docelowa liczba klientów wynosiła {total_target}; wybrano dokładnie "
        f"{selected}. Podział na OSD: {distribution}.\n\n"
        "Dla każdego OSD kandydaci zostali rozdzieleni round-robin na "
        "niezależne grupy zgodnie z konfiguracją. W każdej grupie minimalizowano sumę bezwzględnych "
        "różnic godzinowych pomiędzy historycznym bilansem OSD a ważoną sumą "
        "profili klientów, z zachowaniem limitów wag i udziału pojedynczego PPE. "
        f"Solver zakończył w zadanej tolerancji luki MIP w {optimal} z {group_count} grup "
        "(szczegółowe luki i statusy w arkuszu Solver).\n\n"
        f"Dla wszystkich {selected} klientów podstawowych dobrano {reserves} "
        "różnych zastępców (relacja 1:1) wyłącznie spośród PPE z aktualną zgodą. "
        "Zastępcy zostali przypisani wspólnie w obrębie OSD z krótkich list podobnych "
        "profili, minimalizując sumę względnych błędów L1 podmian na tych listach. "
        "Nie dowodzono optymalności względem wszystkich możliwych par. "
        "Szczegółowe wyniki, lejek danych, statusy "
        "solvera i wpływ podmian znajdują się w załączonym skoroszycie."
    )


def _style_workbook(workbook: object) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        if sheet.max_row >= 1 and sheet.max_column >= 1:
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        for column_cells in sheet.iter_cols(
            min_row=1, max_row=min(sheet.max_row, 200), max_col=sheet.max_column
        ):
            width = min(
                45,
                max(10, max(len(str(cell.value or "")) for cell in column_cells) + 2),
            )
            sheet.column_dimensions[column_cells[0].column_letter].width = width


def write_portfolio_workbook(
    outputs: Sequence[BranchOutput],
    path: str | Path,
    total_target: int,
    *,
    overwrite: bool = False,
    partial: bool = False,
    run_metadata: Mapping[str, object] | None = None,
) -> Path:
    if not outputs:
        raise ValueError("Brak wyników do zapisania.")
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Plik {target} już istnieje.")
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = _frames(outputs)
    oversized = {
        name: len(frame) + 1
        for name, frame in frames.items()
        if len(frame) + 1 > EXCEL_MAX_ROWS
    }
    if oversized:
        details = ", ".join(f"{name}: {rows}" for name, rows in oversized.items())
        raise ValueError(
            f"Raport przekroczyłby limit {EXCEL_MAX_ROWS} wierszy Excela ({details})."
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".tmp.xlsx", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            for sheet_name, frame in frames.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)
            pd.DataFrame(
                {
                    "parametr": [
                        "docelowa_liczba_klientow",
                        "liczba_OSD",
                        "zasada_zgod",
                        "zasada_zastepcow",
                        "zakres_raportu",
                        *(run_metadata or {}).keys(),
                    ],
                    "wartosc": [
                        total_target,
                        len(outputs),
                        "Wyłącznie Kod PP Aktualny z pliku zgód, zgodny z OSD",
                        "Jeden unikalny zastępca na klienta, w tym samym OSD",
                        "CZĘŚCIOWY — tylko ukończony OSD, nie cały portfel" if partial else "Pełny przebieg wskazanych OSD",
                        *(run_metadata or {}).values(),
                    ],
                }
            ).to_excel(writer, sheet_name="Konfiguracja", index=False)
            mail_text = _mail_text(outputs, total_target)
            if partial:
                mail_text = "RAPORT CZĘŚCIOWY: tylko ukończony OSD. Nie jest pełnym wynikiem wyboru dla wszystkich OSD.\n\n" + mail_text
            pd.DataFrame(
                {"Tekst do maila (bez identyfikatorów PPE)": mail_text.split("\n")}
            ).to_excel(writer, sheet_name="Tekst_do_maila", index=False)
            _style_workbook(writer.book)
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
