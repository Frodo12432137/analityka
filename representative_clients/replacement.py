from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Tuple

import numpy as np

from .model import SelectionData, SelectionResult
from .solver import selection_weight_bounds


@dataclass(frozen=True)
class ReserveMatch:
    branch: str
    group: str
    primary_id: str
    primary_weight: float
    reserve_id: str
    reserve_weight: float
    l1_error: float
    mae: float
    normalized_l1: float
    correlation: float | None


@dataclass(frozen=True)
class ReplacementGroupDiagnostic:
    branch: str
    group: str
    l1_primary: float
    l1_after_replacement: float
    mae_primary: float
    mae_after_replacement: float
    max_error_primary: float
    max_error_after_replacement: float


@dataclass(frozen=True)
class ReplacementResult:
    matches: Tuple[ReserveMatch, ...]
    diagnostics: Tuple[ReplacementGroupDiagnostic, ...]


def optimal_nonnegative_weight(
    candidate_profile: np.ndarray,
    target_profile: np.ndarray,
    upper: float = 3000.0,
) -> Tuple[float, float]:
    """Dokładne minimum L1 dla jednej nieujemnej wagi zastępcy."""

    candidate = np.asarray(candidate_profile, dtype=float)
    target = np.asarray(target_profile, dtype=float)
    if candidate.shape != target.shape or candidate.ndim != 1:
        raise ValueError("Profile zastępcy i celu muszą być wektorami tej samej długości.")
    if not np.isfinite(candidate).all() or not np.isfinite(target).all():
        raise ValueError("Profile zastępcy zawierają NaN albo nieskończoność.")
    nonzero = candidate != 0
    if not nonzero.any():
        weight = 0.0
    else:
        ratios = target[nonzero] / candidate[nonzero]
        masses = np.abs(candidate[nonzero])
        order = np.argsort(ratios, kind="stable")
        cumulative = np.cumsum(masses[order])
        median_position = int(np.searchsorted(cumulative, cumulative[-1] / 2.0))
        weight = float(ratios[order[median_position]])
        weight = min(float(upper), max(0.0, weight))
    residual = candidate * weight - target
    return weight, float(np.sum(np.abs(residual)))


def _shape_features(profiles: np.ndarray, blocks: int = 24) -> np.ndarray:
    """Mały wektor kształtu profilu do utworzenia listy najbliższych kandydatów."""

    matrix = np.asarray(profiles, dtype=float)
    period_count, client_count = matrix.shape
    scale = np.mean(np.abs(matrix), axis=0)
    scale[scale <= 1e-12] = 1.0
    normalized = matrix / scale[np.newaxis, :]
    boundaries = np.linspace(0, period_count, min(blocks, period_count) + 1, dtype=int)
    block_features = np.vstack(
        [
            normalized[boundaries[index] : boundaries[index + 1], :].mean(axis=0)
            for index in range(len(boundaries) - 1)
        ]
    ).T
    statistics = np.column_stack(
        (
            normalized.mean(axis=0),
            normalized.std(axis=0),
            np.mean(normalized > 0, axis=0),
            np.mean(normalized < 0, axis=0),
            np.max(normalized, axis=0),
            np.min(normalized, axis=0),
        )
    )
    return np.hstack((block_features, statistics))


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if np.std(left) <= 1e-12 or np.std(right) <= 1e-12:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if np.isfinite(value) else None


def choose_unique_reserves(
    data: SelectionData,
    selection: SelectionResult,
    *,
    initial_shortlist: int = 32,
    maximum_weight: float | None = None,
    check_budget=None,
) -> ReplacementResult:
    """Dobiera globalnie jeden różny zastępca do każdego wybranego PPE."""

    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import min_weight_full_bipartite_matching
        from scipy.spatial import cKDTree
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Do doboru zastępców wymagany jest SciPy.") from exc

    selected: list[Tuple[str, str, float]] = []
    for group in selection.groups:
        selected.extend(
            (group.group, client_id, float(weight))
            for client_id, weight in group.selected_weights.items()
        )
    if not selected:
        return ReplacementResult(matches=(), diagnostics=())
    if maximum_weight is None:
        # Zachowaj historyczny limit minimalny, ale nie obcinaj skali
        # odtworzonej z pełnej populacji klientów podstawowych.
        maximum_weight = max(3000.0, selection_weight_bounds(data, selection.config)[1])
    selected_ids = {client_id for _, client_id, _ in selected}
    reserve_ids = tuple(
        client_id
        for client_id in data.client_ids
        if client_id not in selected_ids and client_id not in data.excluded
    )
    if len(reserve_ids) < len(selected):
        raise ValueError(
            f"OSD {data.branch}: wybrano {len(selected)} klientów, ale zostało tylko "
            f"{len(reserve_ids)} dopuszczonych kandydatów na unikalnych zastępców."
        )
    positions = {client_id: index for index, client_id in enumerate(data.client_ids)}
    primary_indices = np.asarray([positions[item[1]] for item in selected], dtype=int)
    reserve_indices = np.asarray([positions[item] for item in reserve_ids], dtype=int)
    profiles = np.asarray(data.client_balance, dtype=float)
    primary_profiles = profiles[:, primary_indices]
    reserve_profiles = profiles[:, reserve_indices]
    reserve_features = _shape_features(reserve_profiles)
    primary_features = _shape_features(primary_profiles)
    tree = cKDTree(reserve_features)

    primary_count = len(selected)
    reserve_count = len(reserve_ids)
    shortlist = min(reserve_count, max(1, int(initial_shortlist)))
    cached: Dict[Tuple[int, int], Tuple[float, float]] = {}
    assignment: Mapping[int, int] | None = None
    while assignment is None:
        if check_budget is not None:
            check_budget()
        _, neighbours = tree.query(primary_features, k=shortlist)
        neighbours = np.asarray(neighbours, dtype=int)
        if neighbours.ndim == 1:
            neighbours = neighbours[:, np.newaxis]
        rows: list[int] = []
        columns: list[int] = []
        costs: list[float] = []
        for primary_index in range(primary_count):
            if check_budget is not None:
                check_budget()
            target = primary_profiles[:, primary_index] * selected[primary_index][2]
            denominator = max(float(np.sum(np.abs(target))), 1e-12)
            for reserve_index in np.unique(neighbours[primary_index]):
                key = (primary_index, int(reserve_index))
                if key not in cached:
                    cached[key] = optimal_nonnegative_weight(
                        reserve_profiles[:, reserve_index], target, maximum_weight
                    )
                _, l1 = cached[key]
                rows.append(primary_index)
                columns.append(int(reserve_index))
                costs.append(l1 / denominator + 1e-12 * (int(reserve_index) + 1))
        graph = coo_matrix(
            (np.asarray(costs), (np.asarray(rows), np.asarray(columns))),
            shape=(primary_count, reserve_count),
        ).tocsr()
        try:
            matched_rows, matched_columns = min_weight_full_bipartite_matching(graph)
            if len(matched_rows) == primary_count:
                assignment = dict(zip(matched_rows.tolist(), matched_columns.tolist()))
        except ValueError:
            assignment = None
        if assignment is None:
            if shortlist == reserve_count:
                raise ValueError(f"OSD {data.branch}: nie znaleziono pełnego skojarzenia zastępców.")
            shortlist = min(reserve_count, shortlist * 2)

    matches: list[ReserveMatch] = []
    by_group: Dict[str, list[ReserveMatch]] = {}
    for primary_index, (group, primary_id, primary_weight) in enumerate(selected):
        reserve_index = assignment[primary_index]
        target = primary_profiles[:, primary_index] * primary_weight
        key = (primary_index, reserve_index)
        if key not in cached:
            cached[key] = optimal_nonnegative_weight(
                reserve_profiles[:, reserve_index], target, maximum_weight
            )
        reserve_weight, l1 = cached[key]
        replacement = reserve_profiles[:, reserve_index] * reserve_weight
        match = ReserveMatch(
            branch=data.branch,
            group=group,
            primary_id=primary_id,
            primary_weight=primary_weight,
            reserve_id=reserve_ids[reserve_index],
            reserve_weight=reserve_weight,
            l1_error=l1,
            mae=l1 / len(data.periods),
            normalized_l1=l1 / max(float(np.sum(np.abs(target))), 1e-12),
            correlation=_correlation(target, replacement),
        )
        matches.append(match)
        by_group.setdefault(group, []).append(match)

    diagnostics: list[ReplacementGroupDiagnostic] = []
    groups_by_name = {group.group: group for group in selection.groups}
    for group_name, group in groups_by_name.items():
        replacement_balance = np.asarray(group.model_balance, dtype=float).copy()
        for match in by_group.get(group_name, []):
            replacement_balance -= profiles[:, positions[match.primary_id]] * match.primary_weight
            replacement_balance += profiles[:, positions[match.reserve_id]] * match.reserve_weight
        primary_residual = np.asarray(group.residual, dtype=float)
        replacement_residual = replacement_balance - data.branch_balance
        diagnostics.append(
            ReplacementGroupDiagnostic(
                branch=data.branch,
                group=group_name,
                l1_primary=float(np.sum(np.abs(primary_residual))),
                l1_after_replacement=float(np.sum(np.abs(replacement_residual))),
                mae_primary=float(np.mean(np.abs(primary_residual))),
                mae_after_replacement=float(np.mean(np.abs(replacement_residual))),
                max_error_primary=float(np.max(np.abs(primary_residual))),
                max_error_after_replacement=float(np.max(np.abs(replacement_residual))),
            )
        )
    return ReplacementResult(matches=tuple(matches), diagnostics=tuple(diagnostics))

