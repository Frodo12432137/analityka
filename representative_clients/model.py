from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np


Period = Tuple[object, object]


@dataclass(frozen=True)
class SelectionConfig:
    """Parametry odpowiadające skalarom i opcjom modelu GAMS v8."""

    max_clients_per_group: int = 50
    group_count: int = 4
    max_contribution_share: float = 0.20
    time_limit_seconds: Optional[float] = 14_400.0
    mip_relative_gap: float = 0.10
    weight_lower_factor: float = 0.10
    weight_upper_factor: float = 5.0
    normalize_balance: bool = True
    solver_display: bool = False
    exact_clients_per_group: Optional[Tuple[int, ...]] = None

    def validate(self) -> None:
        for name in ("max_clients_per_group", "group_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ValueError(f"{name} musi być liczbą całkowitą.")
            if value <= 0:
                raise ValueError(f"{name} musi być dodatnie.")

        numeric = {
            "max_contribution_share": self.max_contribution_share,
            "time_limit_seconds": self.time_limit_seconds,
            "mip_relative_gap": self.mip_relative_gap,
            "weight_lower_factor": self.weight_lower_factor,
            "weight_upper_factor": self.weight_upper_factor,
        }
        for name, value in numeric.items():
            if name == "time_limit_seconds" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"{name} musi być liczbą.")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} musi być wartością skończoną.")

        if self.max_contribution_share < 0:
            raise ValueError("max_contribution_share nie może być ujemne.")
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds musi być dodatnie.")
        if not 0 <= self.mip_relative_gap <= 1:
            raise ValueError("mip_relative_gap musi należeć do [0, 1].")
        if self.weight_lower_factor < 0:
            raise ValueError("weight_lower_factor nie może być ujemne.")
        if self.weight_upper_factor <= 0:
            raise ValueError("weight_upper_factor musi być dodatnie.")
        if self.weight_lower_factor > self.weight_upper_factor:
            raise ValueError("Dolny mnożnik wagi nie może przekraczać górnego.")
        if not isinstance(self.normalize_balance, bool):
            raise ValueError("normalize_balance musi być wartością logiczną.")
        if not isinstance(self.solver_display, bool):
            raise ValueError("solver_display musi być wartością logiczną.")
        if self.exact_clients_per_group is not None:
            quotas = self.exact_clients_per_group
            if len(quotas) != self.group_count:
                raise ValueError(
                    "exact_clients_per_group musi zawierać po jednej wartości "
                    "dla każdej grupy."
                )
            for quota in quotas:
                if isinstance(quota, bool) or not isinstance(quota, Integral):
                    raise ValueError("Dokładne limity grup muszą być całkowite.")
                if quota < 0 or quota > self.max_clients_per_group:
                    raise ValueError(
                        "Dokładny limit grupy musi należeć do przedziału "
                        "[0, max_clients_per_group]."
                    )


@dataclass
class SelectionData:
    """Znormalizowane wejście jednego oddziału.

    ``client_balance`` ma układ ``okres x klient``. Kolejność klientów jest
    istotna, ponieważ GAMS v8 dzieli ich round-robin na c1..c4.
    """

    branch: str
    client_ids: Tuple[str, ...]
    periods: Tuple[Period, ...]
    client_balance: np.ndarray
    branch_balance: np.ndarray
    excluded: frozenset[str] = field(default_factory=frozenset)
    required_weights: Mapping[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.branch:
            raise ValueError("Brak nazwy oddziału.")
        if not self.client_ids:
            raise ValueError("Brak klientów w danych wejściowych.")
        if any(
            not isinstance(client_id, str) or not client_id.strip()
            for client_id in self.client_ids
        ):
            raise ValueError("Każdy identyfikator klienta musi być niepustym tekstem.")
        if len(set(self.client_ids)) != len(self.client_ids):
            raise ValueError("Lista klientów zawiera duplikaty.")
        if not self.periods:
            raise ValueError("Brak okresów historycznych.")
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("Lista okresów zawiera duplikaty.")

        profiles = np.asarray(self.client_balance, dtype=float)
        target = np.asarray(self.branch_balance, dtype=float)
        expected = (len(self.periods), len(self.client_ids))
        if profiles.shape != expected:
            raise ValueError(
                f"client_balance ma kształt {profiles.shape}, oczekiwano {expected}."
            )
        if target.shape != (len(self.periods),):
            raise ValueError(
                "branch_balance musi być wektorem o długości równej liczbie okresów."
            )
        if not np.isfinite(profiles).all():
            raise ValueError("Profile klientów zawierają NaN albo nieskończoność.")
        if not np.isfinite(target).all():
            raise ValueError("Bilans oddziału zawiera NaN albo nieskończoność.")

        known = set(self.client_ids)
        unknown_excluded = set(self.excluded) - known
        unknown_required = set(self.required_weights) - known
        if unknown_excluded:
            raise ValueError(
                "Wykluczenia zawierają nieznanych klientów: "
                + ", ".join(sorted(unknown_excluded))
            )
        if unknown_required:
            raise ValueError(
                "Lista wymaganych zawiera nieznanych klientów: "
                + ", ".join(sorted(unknown_required))
            )
        conflict = set(self.excluded) & set(self.required_weights)
        if conflict:
            raise ValueError(
                "Klient nie może być jednocześnie wymagany i wykluczony: "
                + ", ".join(sorted(conflict))
            )
        for client_id, weight in self.required_weights.items():
            if not np.isfinite(weight) or weight < 0:
                raise ValueError(
                    f"Wymagana waga klienta {client_id!r} musi być nieujemna i skończona."
                )


@dataclass(frozen=True)
class GroupResult:
    group: str
    candidate_ids: Tuple[str, ...]
    selected_weights: Mapping[str, float]
    binary_values: np.ndarray
    weights: np.ndarray
    model_balance: np.ndarray
    residual: np.ndarray
    objective_value: float
    status: int
    status_text: str
    has_solution: bool
    optimal: bool
    solve_seconds: float
    mip_gap: Optional[float] = None
    mip_dual_bound: Optional[float] = None
    mip_node_count: Optional[int] = None
    max_constraint_violation: float = 0.0


@dataclass(frozen=True)
class SelectionResult:
    branch: str
    periods: Tuple[Period, ...]
    branch_balance: np.ndarray
    config: SelectionConfig
    groups: Tuple[GroupResult, ...]
    required_weights: Mapping[str, float]
    excluded: frozenset[str]

    @property
    def selected_count(self) -> int:
        return sum(len(group.selected_weights) for group in self.groups)

    def selected_by_group(self) -> Dict[str, Mapping[str, float]]:
        return {group.group: group.selected_weights for group in self.groups}
