"""Ocena bilansu i podmian przy niezmienionych klientach i wagach."""
from __future__ import annotations

from dataclasses import replace
import math
import numpy as np
import pandas as pd

from .model import SelectionData, SelectionResult


def training_data(data: SelectionData, holdout_days: int) -> tuple[SelectionData, frozenset[str]]:
    if holdout_days < 0:
        raise ValueError("Liczba dni testowych nie może być ujemna.")
    if holdout_days == 0:
        return data, frozenset()
    dates = [pd.Timestamp(period[0]).date().isoformat() for period in data.periods]
    unique = sorted(set(dates))
    if holdout_days >= len(unique) or len(unique) - holdout_days < 2:
        raise ValueError("Test wymaga pozostawienia co najmniej dwóch dni do doboru klientów.")
    test_days = frozenset(unique[-holdout_days:])
    mask = np.asarray([day not in test_days for day in dates])
    training = replace(data, periods=tuple(p for p, use in zip(data.periods, mask) if use),
                       client_balance=data.client_balance[mask, :], branch_balance=data.branch_balance[mask])
    training.validate()
    return training, test_days


def error_metrics(actual, modeled) -> dict:
    actual, modeled = np.asarray(actual, dtype=float), np.asarray(modeled, dtype=float)
    if actual.shape != modeled.shape or actual.ndim != 1 or len(actual) == 0:
        raise ValueError("Ocena wymaga dwóch niepustych wektorów tej samej długości.")
    if not np.isfinite(actual).all() or not np.isfinite(modeled).all():
        raise ValueError("Ocena zawiera NaN lub nieskończoność.")
    residual = modeled - actual
    absolute = np.abs(residual)
    denominator = float(np.sum(np.abs(actual)))
    scale = float(np.max(absolute))
    rmse = scale * math.sqrt(float(np.mean((residual / scale) ** 2))) if scale else 0.0
    variance = float(np.sum((actual - actual.mean()) ** 2))
    return {
        "liczba_okresow": len(actual), "L1": float(absolute.sum()),
        "MAE": float(absolute.mean()), "RMSE": rmse,
        "blad_wzgledny": float(absolute.sum()) / denominator if denominator else None,
        "sredni_blad_ze_znakiem": float(residual.mean()),
        "suma_bledow_ze_znakiem": float(residual.sum()),
        "bias_wzgledny": float(residual.sum()) / denominator if denominator else None,
        "maks_blad": float(absolute.max()), "P95_bledu": float(np.quantile(absolute, 0.95)),
        "korelacja": float(np.corrcoef(actual, modeled)[0, 1]) if np.std(actual) > 0 and np.std(modeled) > 0 else None,
        "R2": 1 - float(np.sum(residual ** 2)) / variance if variance > 0 else None,
        "suma_abs_historii": denominator,
    }


def assess_quality(data: SelectionData, selection: SelectionResult, replacements, test_days=frozenset()) -> dict:
    positions = {client: i for i, client in enumerate(data.client_ids)}
    dates = np.asarray([pd.Timestamp(p[0]).date().isoformat() for p in data.periods])
    hours = np.asarray([str(p[1]) for p in data.periods])
    targets = np.asarray(data.branch_balance, dtype=float)
    test_mask = np.asarray([day in test_days for day in dates])
    scopes = [("Dopasowanie", ~test_mask)]
    if test_mask.any():
        scopes.append(("Test poza doborem", test_mask))
    summary, slices, balances, impacts = [], [], [], []
    for group in selection.groups:
        prediction = np.zeros(len(targets))
        for client, weight in group.selected_weights.items():
            prediction += data.client_balance[:, positions[client]] * weight
        group_matches = [match for match in replacements.matches if match.group == group.group]
        all_prediction = prediction.copy()
        for match in group_matches:
            all_prediction += (data.client_balance[:, positions[match.reserve_id]] * match.reserve_weight
                               - data.client_balance[:, positions[match.primary_id]] * match.primary_weight)
        for scope, mask in scopes:
            base = error_metrics(targets[mask], prediction[mask])
            row = {"oddzial": data.branch, "grupa": group.group, "zakres": scope,
                   "klienci_podstawowi": len(group.selected_weights), **base,
                   "walidacja": "Odłożone ostatnie dni; nie użyte w doborze ani wagach" if scope.startswith("Test") else
                   ("Dopasowanie; test podano osobno" if test_days else "Brak testu poza doborem"),
                   "zastepcy_kompletni": len(group_matches) == len(group.selected_weights)}
            if len(group_matches) == len(group.selected_weights):
                after = error_metrics(targets[mask], all_prediction[mask])
                row.update({"MAE_podmiana_wszystkich": after["MAE"],
                            "blad_wzgledny_podmiana_wszystkich": after["blad_wzgledny"]})
            summary.append(row)
            for kind, labels in (("Dzień", dates), ("Godzina", hours)):
                for label in dict.fromkeys(labels[mask]):
                    subset = mask & (labels == label)
                    slices.append({"oddzial": data.branch, "grupa": group.group, "zakres": scope,
                                   "przekroj": kind, "okres": label,
                                   **error_metrics(targets[subset], prediction[subset])})
            for match in group_matches:
                single = prediction.copy()
                single += (data.client_balance[:, positions[match.reserve_id]] * match.reserve_weight
                           - data.client_balance[:, positions[match.primary_id]] * match.primary_weight)
                after = error_metrics(targets[mask], single[mask])
                impacts.append({"oddzial": data.branch, "grupa": group.group, "zakres": scope,
                                "klient_podstawowy": match.primary_id, "klient_zastepczy": match.reserve_id,
                                "MAE_przed": base["MAE"], "MAE_po_jednej_podmianie": after["MAE"],
                                "zmiana_MAE": after["MAE"] - base["MAE"],
                                "blad_wzgledny_przed": base["blad_wzgledny"],
                                "blad_wzgledny_po": after["blad_wzgledny"],
                                "maks_blad_po": after["maks_blad"]})
        for i, period in enumerate(data.periods):
            balances.append({"oddzial": data.branch, "grupa": group.group,
                             "data": period[0], "godzina": period[1],
                             "bilans_historyczny": targets[i], "bilans_model": prediction[i],
                             "blad_model_minus_historia": prediction[i] - targets[i],
                             "blad_bezwzgledny": abs(prediction[i] - targets[i]),
                             "zakres": "Test poza doborem" if test_mask[i] else "Dopasowanie",
                             "okres_na_wykresie": f"{dates[i]} / {hours[i]}"})
    return {"Reprezentatywnosc": pd.DataFrame(summary), "Jakosc_dni_godzin": pd.DataFrame(slices),
            "Podmiany_pojedyncze": pd.DataFrame(impacts), "Bilans": pd.DataFrame(balances)}
