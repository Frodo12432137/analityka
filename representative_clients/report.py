from __future__ import annotations

import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .grouping import round_robin_groups
from .model import GroupResult, SelectionConfig, SelectionData, SelectionResult


EXCEL_MAX_ROWS = 1_048_576


def validate_report_capacity(data: SelectionData, config: SelectionConfig) -> None:
    """Odrzuca konfigurację, której raport nie zmieści się w arkuszu Excel."""

    groups = round_robin_groups(
        data.client_ids, data.excluded, config.group_count
    )
    maximum_selected = sum(
        min(len(candidate_ids), config.max_clients_per_group)
        for candidate_ids in groups.values()
    )
    date_count = len({period[0] for period in data.periods})
    checks = {
        "Bilans": 1 + config.group_count * len(data.periods),
        "Wyniki / blok bilansu": 2 + config.group_count * len(data.periods),
        "Istotnosc_dzienna": 1 + maximum_selected * date_count,
        "Wyniki / blok istotności dziennej": 2
        + maximum_selected * date_count,
    }
    too_large = {name: rows for name, rows in checks.items() if rows > EXCEL_MAX_ROWS}
    if too_large:
        description = ", ".join(
            f"{name}: do {rows} wierszy" for name, rows in too_large.items()
        )
        raise ValueError(
            f"Raport przekroczyłby limit Excela {EXCEL_MAX_ROWS} wierszy "
            f"({description}). Zmniejsz liczbę grup/klientów albo zakres dat."
        )


def _safe_ratio(values: np.ndarray) -> np.ndarray:
    denominator = float(values.sum())
    if abs(denominator) <= 1e-15:
        return np.full(values.shape, np.nan, dtype=float)
    return values / denominator


def selected_frame(result: SelectionResult) -> pd.DataFrame:
    rows: List[dict] = []
    for group in result.groups:
        for client_id, weight in group.selected_weights.items():
            rows.append(
                {
                    "oddzial": result.branch,
                    "grupa": group.group,
                    "klient": client_id,
                    "waga": weight,
                    "wymagany": client_id in result.required_weights,
                    "status_solvera": group.status_text,
                    "cel_L1": group.objective_value,
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "oddzial",
            "grupa",
            "klient",
            "waga",
            "wymagany",
            "status_solvera",
            "cel_L1",
        ],
    )


def balance_frame(result: SelectionResult) -> pd.DataFrame:
    rows: List[dict] = []
    for group in result.groups:
        for period, target, modeled, residual in zip(
            result.periods,
            result.branch_balance,
            group.model_balance,
            group.residual,
        ):
            rows.append(
                {
                    "oddzial": result.branch,
                    "grupa": group.group,
                    "data": period[0],
                    "godzina": period[1],
                    "bilans_historyczny": target,
                    "bilans_model": modeled,
                    "blad_model_minus_historia": residual,
                    "blad_bezwzgledny": abs(residual),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "oddzial",
            "grupa",
            "data",
            "godzina",
            "bilans_historyczny",
            "bilans_model",
            "blad_model_minus_historia",
            "blad_bezwzgledny",
        ],
    )


def importance_frames(
    data: SelectionData, result: SelectionResult
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    client_position = {client_id: index for index, client_id in enumerate(data.client_ids)}
    date_positions: Dict[object, List[int]] = OrderedDict()
    for index, period in enumerate(result.periods):
        date_positions.setdefault(period[0], []).append(index)

    daily_rows: List[dict] = []
    all_rows: List[dict] = []
    for group in result.groups:
        selected_ids = tuple(group.selected_weights)
        if not selected_ids:
            continue
        indices = [client_position[client_id] for client_id in selected_ids]
        weights = np.asarray([group.selected_weights[client_id] for client_id in selected_ids])
        profiles = np.asarray(data.client_balance, dtype=float)[:, indices]
        weighted = profiles * weights[np.newaxis, :]

        for history_date, row_indices in date_positions.items():
            daily_profiles = profiles[row_indices, :]
            daily_weighted = weighted[row_indices, :]
            positive_values = np.where(daily_profiles > 0, daily_weighted, 0.0).sum(axis=0)
            negative_values = np.where(daily_profiles < 0, daily_weighted, 0.0).sum(axis=0)
            positive_share = _safe_ratio(positive_values)
            negative_share = _safe_ratio(negative_values)
            for offset, client_id in enumerate(selected_ids):
                daily_rows.append(
                    {
                        "oddzial": result.branch,
                        "grupa": group.group,
                        "data": history_date,
                        "klient": client_id,
                        "Pobor": positive_share[offset],
                        "Oddanie": negative_share[offset],
                    }
                )

        positive_values = np.where(profiles > 0, weighted, 0.0).sum(axis=0)
        negative_values = np.where(profiles < 0, weighted, 0.0).sum(axis=0)
        positive_share = _safe_ratio(positive_values)
        negative_share = _safe_ratio(negative_values)
        for offset, client_id in enumerate(selected_ids):
            all_rows.append(
                {
                    "oddzial": result.branch,
                    "grupa": group.group,
                    "klient": client_id,
                    "Pobor": positive_share[offset],
                    "Oddanie": negative_share[offset],
                }
            )
    return (
        pd.DataFrame(
            daily_rows,
            columns=["oddzial", "grupa", "data", "klient", "Pobor", "Oddanie"],
        ),
        pd.DataFrame(
            all_rows,
            columns=["oddzial", "grupa", "klient", "Pobor", "Oddanie"],
        ),
    )


def diagnostics_frame(result: SelectionResult) -> pd.DataFrame:
    rows = []
    for group in result.groups:
        rows.append(
            {
                "oddzial": result.branch,
                "grupa": group.group,
                "liczba_kandydatow": len(group.candidate_ids),
                "liczba_wybranych": len(group.selected_weights),
                "cel_L1": group.objective_value,
                "status_kod": group.status,
                "status": group.status_text,
                "optymalne": group.optimal,
                "czas_s": group.solve_seconds,
                "mip_gap": group.mip_gap,
                "mip_dual_bound": group.mip_dual_bound,
                "mip_node_count": group.mip_node_count,
                "maks_naruszenie": group.max_constraint_violation,
                "populacja_do_wag": result.config.weight_population_size,
                "waga_min": group.weight_lower_bound,
                "waga_min_pierwotna": group.weight_lower_nominal,
                "obnizono_minimum_wagi": (group.weight_lower_nominal is not None
                                        and group.weight_lower_bound is not None
                                        and group.weight_lower_bound < group.weight_lower_nominal - 1e-12),
                "wybrani_z_waga_zero": sum(abs(w) <= 1e-12 for w in group.selected_weights.values()),
                "waga_max_populacja": group.weight_upper_bound,
                "wagi_na_limicie_gornym": group.weights_at_upper_bound,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "oddzial",
            "grupa",
            "liczba_kandydatow",
            "liczba_wybranych",
            "cel_L1",
            "status_kod",
            "status",
            "optymalne",
            "czas_s",
            "mip_gap",
            "mip_dual_bound",
            "mip_node_count",
            "maks_naruszenie",
            "populacja_do_wag",
            "waga_min",
            "waga_min_pierwotna",
            "obnizono_minimum_wagi",
            "waga_max_populacja",
            "wagi_na_limicie_gornym",
        ],
    )


def configuration_frame(result: SelectionResult) -> pd.DataFrame:
    config = result.config
    values = [
        ("oddzial", result.branch),
        ("max_klientow_na_grupe", config.max_clients_per_group),
        ("liczba_grup", config.group_count),
        ("max_udzial", config.max_contribution_share),
        ("limit_czasu_s_na_grupe", config.time_limit_seconds),
        ("mip_relative_gap", config.mip_relative_gap),
        ("mnoznik_wagi_min", config.weight_lower_factor),
        ("mnoznik_wagi_max", config.weight_upper_factor),
        ("populacja_do_wag", config.weight_population_size),
        ("normalizacja_numeryczna", config.normalize_balance),
        ("liczba_wykluczonych", len(result.excluded)),
        ("liczba_wymaganych", len(result.required_weights)),
    ]
    return pd.DataFrame(values, columns=["parametr", "wartosc"])


def _write_gams_compatibility_sheet(
    writer: object,
    result: SelectionResult,
    daily: pd.DataFrame,
    overall: pd.DataFrame,
) -> None:
    """Odtwarza cztery bloki eksportowane przez GDXXRW w GAMS v8."""

    sheet = writer.book.create_sheet("Wyniki", 0)

    # p_out_waga_klient, rng='Wyniki'!B3, rdim=2, cdim=0
    row_number = 3
    for group in result.groups:
        for client_id, weight in group.selected_weights.items():
            sheet.cell(row=row_number, column=2, value=group.group)
            sheet.cell(row=row_number, column=3, value=client_id)
            sheet.cell(row=row_number, column=4, value=float(weight))
            row_number += 1

    # p_out_bilans, rng='Wyniki'!G2, rdim=3, cdim=1
    sheet.cell(row=2, column=10, value="b_historia")
    sheet.cell(row=2, column=11, value="b_model_w_klienci")
    row_number = 3
    for group in result.groups:
        for period, target, modeled in zip(
            result.periods, result.branch_balance, group.model_balance
        ):
            sheet.cell(row=row_number, column=7, value=group.group)
            sheet.cell(row=row_number, column=8, value=period[0])
            sheet.cell(row=row_number, column=9, value=period[1])
            sheet.cell(row=row_number, column=10, value=float(target))
            sheet.cell(row=row_number, column=11, value=float(modeled))
            row_number += 1

    # p_out_istotnosc, rng='Wyniki'!N2, rdim=3, cdim=1
    sheet.cell(row=2, column=17, value="Pobor")
    sheet.cell(row=2, column=18, value="Oddanie")
    for row_number, row in enumerate(daily.itertuples(index=False), start=3):
        sheet.cell(row=row_number, column=14, value=row.grupa)
        sheet.cell(row=row_number, column=15, value=row.data)
        sheet.cell(row=row_number, column=16, value=row.klient)
        sheet.cell(
            row=row_number,
            column=17,
            value=None if pd.isna(row.Pobor) else float(row.Pobor),
        )
        sheet.cell(
            row=row_number,
            column=18,
            value=None if pd.isna(row.Oddanie) else float(row.Oddanie),
        )

    # p_out_istotnosc_all, rng='Wyniki'!U2, rdim=2, cdim=1
    sheet.cell(row=2, column=23, value="Pobor")
    sheet.cell(row=2, column=24, value="Oddanie")
    for row_number, row in enumerate(overall.itertuples(index=False), start=3):
        sheet.cell(row=row_number, column=21, value=row.grupa)
        sheet.cell(row=row_number, column=22, value=row.klient)
        sheet.cell(
            row=row_number,
            column=23,
            value=None if pd.isna(row.Pobor) else float(row.Pobor),
        )
        sheet.cell(
            row=row_number,
            column=24,
            value=None if pd.isna(row.Oddanie) else float(row.Oddanie),
        )


def write_result_workbook(
    data: SelectionData,
    result: SelectionResult,
    path: str | Path,
    overwrite: bool = False,
) -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"Plik {target} już istnieje. Użyj --overwrite, aby go zastąpić."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    daily, overall = importance_frames(data, result)
    actual_rows = {
        "Wyniki / blok bilansu": 2 + len(result.groups) * len(result.periods),
        "Wyniki / blok istotności dziennej": 2 + len(daily),
        "Bilans": 1 + len(result.groups) * len(result.periods),
        "Istotnosc_dzienna": 1 + len(daily),
    }
    too_large = {
        name: rows for name, rows in actual_rows.items() if rows > EXCEL_MAX_ROWS
    }
    if too_large:
        description = ", ".join(
            f"{name}: {rows} wierszy" for name, rows in too_large.items()
        )
        raise ValueError(
            f"Raport nie mieści się w limicie Excela {EXCEL_MAX_ROWS} "
            f"wierszy ({description})."
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".tmp.xlsx", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            _write_gams_compatibility_sheet(writer, result, daily, overall)
            selected_frame(result).to_excel(writer, sheet_name="Wybrani", index=False)
            balance_frame(result).to_excel(writer, sheet_name="Bilans", index=False)
            daily.to_excel(writer, sheet_name="Istotnosc_dzienna", index=False)
            overall.to_excel(writer, sheet_name="Istotnosc_all", index=False)
            diagnostics_frame(result).to_excel(
                writer, sheet_name="Diagnostyka", index=False
            )
            configuration_frame(result).to_excel(
                writer, sheet_name="Konfiguracja", index=False
            )

        if overwrite:
            os.replace(temporary, target)
        else:
            # Utworzenie hardlinku ma semantykę exclusive-create: albo gotowy
            # plik pojawia się pod nazwą docelową, albo istniejący cel pozostaje
            # nietknięty. Oba pliki są w tym samym katalogu/systemie plików.
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"Plik {target} powstał podczas eksportu i nie został zastąpiony."
                ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target

