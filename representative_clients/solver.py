from __future__ import annotations

import time
from typing import Callable, Dict, Optional, Sequence, Tuple

import numpy as np

from .grouping import round_robin_groups
from .model import GroupResult, SelectionConfig, SelectionData, SelectionResult


class SolverUnavailableError(RuntimeError):
    pass


class NoFeasibleSolutionError(RuntimeError):
    pass


def _safe_mean_absolute(values: np.ndarray) -> float:
    """Liczy średni moduł bez przepełnienia pośredniej sumy.

    Zwykłe ``mean(abs(x))`` może zwrócić ``inf`` mimo że każdy element ``x``
    jest skończony. Skalowanie przez największy moduł utrzymuje składniki w
    przedziale [0, 1].
    """

    array = np.asarray(values, dtype=float)
    if array.size == 0:
        raise ValueError("Nie można policzyć średniej z pustego zbioru.")
    if not np.isfinite(array).all():
        raise ValueError("Średnia modułu wymaga wyłącznie skończonych wartości.")
    maximum_absolute = max(float(np.max(array)), float(-np.min(array)))
    if maximum_absolute == 0.0:
        return 0.0
    mean_absolute = maximum_absolute * float(
        np.mean(np.abs(array / maximum_absolute))
    )
    if not np.isfinite(mean_absolute):
        raise ValueError("Nie można wiarygodnie policzyć średniego modułu danych.")
    return mean_absolute


def _safe_sum_absolute(values: np.ndarray) -> float:
    """Liczy sumę modułów i jawnie odrzuca wynik poza zakresem float64."""

    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return 0.0
    if not np.isfinite(array).all():
        raise ValueError("Suma modułów wymaga wyłącznie skończonych wartości.")
    maximum_absolute = max(float(np.max(array)), float(-np.min(array)))
    if maximum_absolute == 0.0:
        return 0.0
    normalized_sum = float(np.sum(np.abs(array / maximum_absolute)))
    with np.errstate(over="ignore", invalid="ignore"):
        result = maximum_absolute * normalized_sum
    if not np.isfinite(result):
        raise ValueError("Suma błędów przekracza obsługiwany zakres liczb.")
    return result


def _contribution_limit(
    branch_balance: np.ndarray, max_contribution_share: float
) -> float:
    mean_absolute = _safe_mean_absolute(branch_balance)
    with np.errstate(over="ignore", invalid="ignore"):
        limit = float(max_contribution_share) * mean_absolute
    if not np.isfinite(limit):
        raise ValueError(
            "Iloczyn maksymalnego udziału i średniego bilansu jest zbyt duży."
        )
    return limit


def gams_weight_bounds(
    total_client_count: int,
    max_clients: int,
    lower_factor: float = 0.10,
    upper_factor: float = 5.0,
) -> Tuple[float, float]:
    """Zwraca domyślne L i U z modelu Marka.

    GAMS używa ``card(s_Klient)``, a więc wszystkich klientów przed
    wykluczeniami, nie tylko kandydatów danej grupy.
    """

    if total_client_count <= 0 or max_clients <= 0:
        raise ValueError("Liczba klientów i limit wyboru muszą być dodatnie.")
    average_weight = total_client_count / max_clients
    return average_weight * lower_factor, average_weight * upper_factor


def contribution_weight_caps(
    profiles: np.ndarray,
    branch_balance: np.ndarray,
    max_contribution_share: float,
) -> np.ndarray:
    """Redukuje ograniczenia klient x okres do równoważnego limitu wagi.

    Dla wagi nieujemnej układ ``-C <= w_i B_it <= C`` jest równoważny
    ``w_i <= C / max_t(abs(B_it))``.
    """

    profile_array = np.asarray(profiles, dtype=float)
    target = np.asarray(branch_balance, dtype=float)
    if profile_array.ndim != 2:
        raise ValueError("profiles musi być macierzą okres x klient.")
    if target.shape != (profile_array.shape[0],):
        raise ValueError("branch_balance ma niezgodny kształt.")
    if not np.isfinite(max_contribution_share) or max_contribution_share < 0:
        raise ValueError("max_contribution_share musi być nieujemne i skończone.")
    if not np.isfinite(profile_array).all() or not np.isfinite(target).all():
        raise ValueError("Profile i bilans muszą zawierać skończone wartości.")
    contribution_limit = _contribution_limit(target, max_contribution_share)
    maximum_absolute_profile = _maximum_absolute_by_column(profile_array)
    caps = np.full(profile_array.shape[1], np.inf, dtype=float)
    nonzero = maximum_absolute_profile > 0
    caps[nonzero] = contribution_limit / maximum_absolute_profile[nonzero]
    return caps


def selection_weight_bounds(data: SelectionData, config: SelectionConfig) -> Tuple[float, float]:
    """Populacja rozszerza maksimum, ale nie wymusza większej minimalnej wagi."""
    population = config.weight_population_size
    if population is None:
        population = len(data.client_ids)
    if population < len(data.client_ids):
        raise ValueError("Populacja do wag nie może być mniejsza od puli kandydatów.")
    lower, _ = gams_weight_bounds(
        len(data.client_ids), config.max_clients_per_group,
        config.weight_lower_factor, config.weight_upper_factor,
    )
    _, upper = gams_weight_bounds(
        population, config.max_clients_per_group,
        config.weight_lower_factor, config.weight_upper_factor,
    )
    return lower, upper


def _maximum_absolute_by_column(values: np.ndarray) -> np.ndarray:
    """Maksimum modułu kolumn bez tworzenia pełnej kopii przez ``abs``."""

    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[0] == 0:
        raise ValueError("Oczekiwano niepustej macierzy okres x klient.")
    return np.maximum(np.max(array, axis=0), -np.min(array, axis=0))


def _build_constraint_matrix(
    profiles: np.ndarray,
    lower_weight: float,
    effective_upper: np.ndarray,
) -> object:
    """Buduje jedną macierz CSC bez kosztownych kopii hstack/vstack.

    Kolumny mają kolejno układ ``z, w, e_plus, e_minus``, a wiersze:
    liczba wybranych, dolne powiązanie wag, górne powiązanie wag i bilans.
    Tablice CSC są wypełniane bezpośrednio, kolumna po kolumnie.
    """

    try:
        from scipy.sparse import csc_matrix
    except ImportError as exc:  # pragma: no cover - zależy od środowiska
        raise SolverUnavailableError("Do budowy modelu wymagany jest SciPy.") from exc

    profile_array = np.asarray(profiles, dtype=float)
    upper = np.asarray(effective_upper, dtype=float)
    if profile_array.ndim != 2:
        raise ValueError("profiles musi być macierzą okres x klient.")
    period_count, client_count = profile_array.shape
    if upper.shape != (client_count,):
        raise ValueError("effective_upper ma niezgodny kształt.")

    profile_nonzero_by_column = np.count_nonzero(profile_array, axis=0)
    nonzero_count = int(
        5 * client_count
        + int(np.sum(profile_nonzero_by_column, dtype=np.int64))
        + 2 * period_count
    )
    variable_count = 2 * client_count + 2 * period_count
    row_count = 1 + 2 * client_count + period_count
    int32_maximum = int(np.iinfo(np.int32).max)
    if (
        nonzero_count > int32_maximum
        or variable_count > int32_maximum
        or row_count > int32_maximum
    ):
        raise MemoryError(
            "Model przekracza bezpieczny limit indeksów macierzy rzadkiej "
            "(2^31-1). Zmniejsz zakres danych."
        )

    values = np.empty(nonzero_count, dtype=np.float64)
    row_indices = np.empty(nonzero_count, dtype=np.int32)
    column_pointers = np.empty(variable_count + 1, dtype=np.int32)
    column_pointers[0] = 0
    cursor = 0
    balance_row_start = 1 + 2 * client_count

    # z_i: licznik wyboru, -L*z_i + w_i >= 0,
    #      -U_i*z_i + w_i <= 0
    for client_index in range(client_count):
        next_cursor = cursor + 3
        row_indices[cursor:next_cursor] = (
            0,
            1 + client_index,
            1 + client_count + client_index,
        )
        values[cursor:next_cursor] = (
            1.0,
            -lower_weight,
            -upper[client_index],
        )
        cursor = next_cursor
        column_pointers[client_index + 1] = cursor

    # w_i: dwa równania wiążące oraz współczynniki profilu w bilansie.
    for client_index in range(client_count):
        column = client_count + client_index
        row_indices[cursor : cursor + 2] = (
            1 + client_index,
            1 + client_count + client_index,
        )
        values[cursor : cursor + 2] = 1.0
        cursor += 2
        nonzero_rows = np.flatnonzero(profile_array[:, client_index])
        profile_nonzero_count = len(nonzero_rows)
        next_cursor = cursor + profile_nonzero_count
        row_indices[cursor:next_cursor] = balance_row_start + nonzero_rows
        values[cursor:next_cursor] = profile_array[nonzero_rows, client_index]
        cursor = next_cursor
        column_pointers[column + 1] = cursor

    # e_plus i e_minus mają po jednym współczynniku w swoim okresie.
    for period_index in range(period_count):
        column = 2 * client_count + period_index
        row_indices[cursor] = balance_row_start + period_index
        values[cursor] = -1.0
        cursor += 1
        column_pointers[column + 1] = cursor
    for period_index in range(period_count):
        column = 2 * client_count + period_count + period_index
        row_indices[cursor] = balance_row_start + period_index
        values[cursor] = 1.0
        cursor += 1
        column_pointers[column + 1] = cursor

    if cursor != nonzero_count:  # obrona przed błędem w układzie macierzy
        raise RuntimeError("Wewnętrzny błąd podczas budowy macierzy ograniczeń.")
    return csc_matrix(
        (values, row_indices, column_pointers),
        shape=(row_count, variable_count),
        copy=False,
    )


def _optional_number(result: object, name: str) -> Optional[float]:
    value = getattr(result, name, None)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _scaled_interval_violation(
    values: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> Tuple[float, float]:
    """Zwraca największe bezwzględne i względnie skalowane naruszenie."""

    values = np.asarray(values, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    violation = np.zeros_like(values, dtype=float)
    finite_lower = np.isfinite(lower)
    finite_upper = np.isfinite(upper)
    violation[finite_lower] = np.maximum(
        violation[finite_lower], lower[finite_lower] - values[finite_lower]
    )
    violation[finite_upper] = np.maximum(
        violation[finite_upper], values[finite_upper] - upper[finite_upper]
    )
    violation = np.maximum(violation, 0.0)

    scale = np.maximum(1.0, np.abs(values))
    scale[finite_lower] = np.maximum(scale[finite_lower], np.abs(lower[finite_lower]))
    scale[finite_upper] = np.maximum(scale[finite_upper], np.abs(upper[finite_upper]))
    return (
        float(violation.max(initial=0.0)),
        float((violation / scale).max(initial=0.0)),
    )


def _audit_solver_incumbent(
    solution: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    integrality: np.ndarray,
    constraint_matrix: object,
    constraint_lower: np.ndarray,
    constraint_upper: np.ndarray,
    relative_tolerance: float = 1e-6,
    integrality_tolerance: float = 1e-5,
) -> Tuple[float, float, float]:
    """Sprawdza incumbent niezależnie od deklarowanego statusu solvera.

    Zwracane są maksymalne naruszenia: bounds, ograniczeń liniowych oraz
    całkowitości. Naruszenia przedziałów są oceniane relatywnie do skali
    danego wiersza, co jest ważne przy dużych wolumenach energii.
    """

    x = np.asarray(solution, dtype=float)
    if x.shape != np.asarray(lower_bounds).shape:
        raise NoFeasibleSolutionError(
            "Solver zwrócił wektor rozwiązania o nieprawidłowej długości."
        )
    if not np.isfinite(x).all():
        raise NoFeasibleSolutionError(
            "Solver zwrócił NaN albo nieskończoność w rozwiązaniu."
        )

    bound_absolute, bound_scaled = _scaled_interval_violation(
        x, lower_bounds, upper_bounds
    )
    activity = np.asarray(constraint_matrix @ x, dtype=float).reshape(-1)
    if not np.isfinite(activity).all():
        raise NoFeasibleSolutionError(
            "Nie można wiarygodnie policzyć ograniczeń zwróconego rozwiązania."
        )
    linear_absolute, linear_scaled = _scaled_interval_violation(
        activity, constraint_lower, constraint_upper
    )

    integer_mask = np.asarray(integrality) != 0
    integer_values = x[integer_mask]
    integrality_violation = float(
        np.abs(integer_values - np.rint(integer_values)).max(initial=0.0)
    )
    if (
        bound_scaled > relative_tolerance
        or linear_scaled > relative_tolerance
        or integrality_violation > integrality_tolerance
    ):
        raise NoFeasibleSolutionError(
            "Solver zwrócił incumbent naruszający tolerancje: "
            f"bounds={bound_absolute:.6g}, ograniczenia={linear_absolute:.6g}, "
            f"całkowitość={integrality_violation:.6g}."
        )
    return bound_absolute, linear_absolute, integrality_violation


def _validate_required_weights(
    candidate_ids: Sequence[str],
    required_weights: Dict[str, float],
    lower_weight: float,
    effective_upper: np.ndarray,
    tolerance: float = 1e-9,
) -> None:
    positions = {client_id: index for index, client_id in enumerate(candidate_ids)}
    for client_id, weight in required_weights.items():
        if client_id not in positions:
            continue
        upper = effective_upper[positions[client_id]]
        if weight < lower_weight - tolerance or weight > upper + tolerance:
            raise NoFeasibleSolutionError(
                f"Wymagana waga {weight:g} klienta {client_id!r} nie mieści się "
                f"w dozwolonym przedziale [{lower_weight:g}, {upper:g}]."
            )


def _validate_selection_capacity(
    group_name: str,
    selection_count: Optional[int],
    lower_weight: float,
    effective_upper: np.ndarray,
) -> None:
    if selection_count is None:
        return
    selectable = int(np.count_nonzero(effective_upper >= lower_weight - 1e-12))
    if selection_count > selectable:
        blocked = len(effective_upper) - selectable
        raise NoFeasibleSolutionError(
            f"Grupa {group_name}: sprzeczne ograniczenia wag. "
            f"Wymagany wybór: {selection_count}, możliwy: {selectable}. "
            f"U {blocked} kandydatów górny limit wagi jest niższy niż "
            f"minimalna waga {lower_weight:g}. "
            "Sprawdź minimalną wagę i limit udziału pojedynczego PPE."
        )


def _empty_group_result(
    group_name: str, branch_balance: np.ndarray
) -> GroupResult:
    residual = -np.asarray(branch_balance, dtype=float)
    return GroupResult(
        group=group_name,
        candidate_ids=(),
        selected_weights={},
        binary_values=np.empty(0),
        weights=np.empty(0),
        model_balance=np.zeros_like(branch_balance, dtype=float),
        residual=residual,
        objective_value=_safe_sum_absolute(residual),
        status=0,
        status_text="Pusta grupa — brak kandydatów.",
        has_solution=True,
        optimal=True,
        solve_seconds=0.0,
    )


def solve_group(
    data: SelectionData,
    config: SelectionConfig,
    group_name: str,
    candidate_ids: Sequence[str],
    *,
    selection_count: Optional[int] = None,
    _effective_upper: Optional[np.ndarray] = None,
    _maximum_absolute_profile: Optional[np.ndarray] = None,
    time_limit_provider: Optional[Callable[[], float]] = None,
) -> GroupResult:
    """Rozwiązuje jeden niezależny podproblem w1..wn."""

    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
    except ImportError as exc:  # pragma: no cover - zależy od środowiska
        raise SolverUnavailableError(
            "Brak SciPy z scipy.optimize.milp. Zainstaluj zależności projektu."
        ) from exc

    if selection_count is not None:
        if selection_count < 0 or selection_count > config.max_clients_per_group:
            raise ValueError("Nieprawidłowa dokładna liczba klientów dla grupy.")
        if selection_count > len(candidate_ids):
            raise NoFeasibleSolutionError(
                f"Grupa {group_name} ma tylko {len(candidate_ids)} kandydatów, "
                f"a wymaga wyboru {selection_count}."
            )
    if not candidate_ids:
        if selection_count not in (None, 0):
            raise NoFeasibleSolutionError(
                f"Grupa {group_name} jest pusta, a wymaga wyboru {selection_count}."
            )
        return _empty_group_result(group_name, data.branch_balance)

    client_position = {client_id: index for index, client_id in enumerate(data.client_ids)}
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError(f"Grupa {group_name} zawiera klienta więcej niż raz.")
    unknown = [client_id for client_id in candidate_ids if client_id not in client_position]
    if unknown:
        raise ValueError(
            f"Grupa {group_name} zawiera nieznanych klientów: "
            + ", ".join(unknown)
        )
    indices = np.asarray([client_position[client_id] for client_id in candidate_ids], dtype=int)
    profiles_all = np.asarray(data.client_balance, dtype=float)
    # Indeksowanie kolumn tworzy jedną roboczą kopię grupy. Jest ona później
    # skalowana w miejscu i zwalniana przed startem MILP; nie utrzymujemy
    # jednocześnie drugiej gęstej kopii, co ma znaczenie dla dużych XLSX.
    profiles = np.asarray(profiles_all[:, indices], dtype=float)
    target_original = np.asarray(data.branch_balance, dtype=float)
    period_count, client_count = profiles.shape

    lower_weight, upper_weight = selection_weight_bounds(data, config)
    if _effective_upper is None or _maximum_absolute_profile is None:
        caps = contribution_weight_caps(
            profiles, target_original, config.max_contribution_share
        )
        maximum_absolute_profile = _maximum_absolute_by_column(profiles)
        effective_upper = np.minimum(upper_weight, caps)
    else:
        effective_upper = np.asarray(_effective_upper, dtype=float)
        maximum_absolute_profile = np.asarray(
            _maximum_absolute_profile, dtype=float
        )
        if effective_upper.shape != (client_count,) or maximum_absolute_profile.shape != (
            client_count,
        ):
            raise ValueError("Nieprawidłowy kształt prekomputowanych limitów grupy.")
    group_required = {
        client_id: float(data.required_weights[client_id])
        for client_id in candidate_ids
        if client_id in data.required_weights
    }
    if len(group_required) > config.max_clients_per_group:
        raise NoFeasibleSolutionError(
            f"Grupa {group_name} ma więcej wymaganych klientów niż limit wyboru."
        )
    if selection_count is not None and len(group_required) > selection_count:
        raise NoFeasibleSolutionError(
            f"Grupa {group_name} ma {len(group_required)} wymaganych klientów, "
            f"ale dokładny limit wynosi {selection_count}."
        )
    _validate_required_weights(
        candidate_ids, group_required, lower_weight, effective_upper
    )
    _validate_selection_capacity(group_name, selection_count, lower_weight, effective_upper)

    # Dzielenie obu stron równań bilansu przez tę samą wartość nie zmienia
    # rozwiązania, a ogranicza problemy numeryczne na danych energetycznych.
    scale = _safe_mean_absolute(target_original)
    if not config.normalize_balance or scale <= 0:
        scale = 1.0
    profiles /= scale
    target = target_original / scale

    z_start = 0
    w_start = client_count
    error_up_start = 2 * client_count
    error_down_start = error_up_start + period_count
    variable_count = 2 * client_count + 2 * period_count

    objective = np.zeros(variable_count, dtype=float)
    objective[error_up_start:error_down_start] = 1.0
    objective[error_down_start:] = 1.0

    lower_bounds = np.zeros(variable_count, dtype=float)
    upper_bounds = np.full(variable_count, np.inf, dtype=float)
    upper_bounds[z_start:w_start] = 1.0
    upper_bounds[w_start:error_up_start] = effective_upper

    # Klient, dla którego limit kontrybucji spadł poniżej minimalnej wagi,
    # nie może zostać wybrany (chyba że był wymagany — obsłużono wyżej).
    impossible = effective_upper < lower_weight - 1e-12
    upper_bounds[z_start:w_start][impossible] = 0.0
    upper_bounds[w_start:error_up_start][impossible] = 0.0
    # Nie umieszczaj gęstych współczynników klientów ustalonych na zero w
    # macierzy rzadkiej. HiGHS i tak nie może ich użyć, a oszczędza to pamięć.
    if impossible.any():
        profiles[:, impossible] = 0.0

    local_position = {client_id: index for index, client_id in enumerate(candidate_ids)}
    for client_id, weight in group_required.items():
        index = local_position[client_id]
        lower_bounds[z_start + index] = 1.0
        upper_bounds[z_start + index] = 1.0
        lower_bounds[w_start + index] = weight
        upper_bounds[w_start + index] = weight

    integrality = np.zeros(variable_count, dtype=np.uint8)
    integrality[z_start:w_start] = 1

    # Budujemy od razu jedną docelową macierz CSC. Unikamy tym samym
    # równoczesnego trzymania csc(profiles), hstack i vstack, co na dużych
    # wejściach usuwa kilka kosztownych kopii współczynników.
    constraint_matrix = _build_constraint_matrix(
        profiles, lower_weight, effective_upper
    )
    del profiles
    count_lower = -np.inf if selection_count is None else float(selection_count)
    count_upper = (
        float(config.max_clients_per_group)
        if selection_count is None
        else float(selection_count)
    )
    constraint_lower = np.concatenate(
        [
            np.asarray([count_lower]),
            np.zeros(client_count),
            np.full(client_count, -np.inf),
            target,
        ]
    )
    constraint_upper = np.concatenate(
        [
            np.asarray([count_upper]),
            np.full(client_count, np.inf),
            np.zeros(client_count),
            target,
        ]
    )

    time_limit = config.time_limit_seconds
    if time_limit_provider is not None:
        provided_limit = time_limit_provider()
        if provided_limit is not None:
            time_limit = provided_limit if time_limit is None else min(time_limit, provided_limit)
    options = {
        "mip_rel_gap": float(config.mip_relative_gap),
        "disp": bool(config.solver_display),
        "presolve": True,
    }
    if time_limit is not None:
        options["time_limit"] = float(time_limit)
    started = time.monotonic()
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=LinearConstraint(
            constraint_matrix, constraint_lower, constraint_upper
        ),
        options=options,
    )
    solve_seconds = time.monotonic() - started

    status = int(getattr(result, "status", -1))
    if result.x is None:
        reason = {
            1: "limit czasu lub iteracji bez dopuszczalnego rozwiązania",
            2: "zadanie niewykonalne — sprzeczne ograniczenia",
            3: "zadanie nieograniczone",
            4: "błąd solvera",
        }.get(status, "nieznany status")
        raise NoFeasibleSolutionError(
            f"Grupa {group_name}: solver nie zwrócił rozwiązania; "
            f"status {status}: {reason} ({result.message})."
        )
    if status not in (0, 1):
        raise NoFeasibleSolutionError(
            f"Grupa {group_name}: odrzucono rozwiązanie o statusie {status} "
            f"({result.message})."
        )

    raw_solution = np.asarray(result.x, dtype=float)
    bound_violation, matrix_violation, integrality_violation = (
        _audit_solver_incumbent(
            raw_solution,
            lower_bounds,
            upper_bounds,
            integrality,
            constraint_matrix,
            constraint_lower,
            constraint_upper,
        )
    )

    raw_binary_values = np.asarray(raw_solution[z_start:w_start], dtype=float)
    selected_mask = np.rint(raw_binary_values).astype(bool)
    binary_values = selected_mask.astype(float)
    raw_weights = np.asarray(raw_solution[w_start:error_up_start], dtype=float)
    weights = raw_weights.copy()
    # Ten sam oczyszczony wektor wag zasila raport wyboru i bilans. Dzięki
    # temu śladowa waga przy z=0 nie powoduje rozjazdu między arkuszami.
    weights[~selected_mask] = 0.0
    full_weights = np.zeros(len(data.client_ids), dtype=float)
    full_weights[indices] = weights
    with np.errstate(over="ignore", invalid="ignore"):
        model_balance = profiles_all @ full_weights
        residual = model_balance - target_original
    if not np.isfinite(model_balance).all() or not np.isfinite(residual).all():
        raise NoFeasibleSolutionError(
            f"Grupa {group_name}: oczyszczone rozwiązanie przepełnia zakres liczb."
        )

    # Po zaokrągleniu binarek i wyzerowaniu wag dla z=0 ponownie budujemy
    # zmienne błędu i audytujemy CAŁE rozwiązanie. Bez tego śladowe z bliskie
    # zeru mogłoby przy bardzo dużym U przenosić istotną wagę, która zniknęłaby
    # dopiero w raporcie.
    cleaned_solution = raw_solution.copy()
    cleaned_solution[z_start:w_start] = binary_values
    cleaned_solution[w_start:error_up_start] = weights
    normalized_residual = residual / scale
    cleaned_solution[error_up_start:error_down_start] = np.maximum(
        normalized_residual, 0.0
    )
    cleaned_solution[error_down_start:] = np.maximum(-normalized_residual, 0.0)
    (
        cleaned_bound_violation,
        cleaned_matrix_violation,
        cleaned_integrality_violation,
    ) = _audit_solver_incumbent(
        cleaned_solution,
        lower_bounds,
        upper_bounds,
        integrality,
        constraint_matrix,
        constraint_lower,
        constraint_upper,
    )
    raw_objective_normalized = float(
        np.sum(raw_solution[error_up_start:error_down_start])
        + np.sum(raw_solution[error_down_start:])
    )
    cleaned_objective_normalized = float(np.sum(np.abs(normalized_residual)))
    objective_tolerance = 1e-6 * max(
        1.0,
        abs(raw_objective_normalized),
        abs(cleaned_objective_normalized),
    )
    if (
        not np.isfinite(raw_objective_normalized)
        or not np.isfinite(cleaned_objective_normalized)
        or abs(cleaned_objective_normalized - raw_objective_normalized)
        > objective_tolerance
    ):
        raise NoFeasibleSolutionError(
            f"Grupa {group_name}: zaokrąglenie rozwiązania zmienia funkcję celu "
            "powyżej tolerancji; wynik nie zostanie zapisany."
        )
    selected_weights = {
        client_id: float(weights[index])
        for index, client_id in enumerate(candidate_ids)
        if selected_mask[index]
    }

    selected_count = float(binary_values.sum())
    count_violation = max(0.0, selected_count - count_upper)
    if selection_count is not None:
        count_violation = max(count_violation, count_lower - selected_count)
    lower_violation = float(
        np.maximum(lower_weight * binary_values - weights, 0.0).max(initial=0.0)
    )
    upper_violation = float(
        np.maximum(weights - effective_upper * binary_values, 0.0).max(initial=0.0)
    )
    balance_violation_normalized = float(
        np.max(
            np.abs(
                (profiles_all @ np.bincount(
                    indices,
                    weights=raw_weights,
                    minlength=len(data.client_ids),
                )) / scale
                - raw_solution[error_up_start:error_down_start]
                + raw_solution[error_down_start:]
                - target
            ),
            initial=0.0,
        )
    )
    with np.errstate(over="ignore", invalid="ignore"):
        balance_violation = balance_violation_normalized * scale
    if not np.isfinite(balance_violation):
        # Diagnostyka łączy wielkości w różnych jednostkach. Gdy samo
        # przeskalowanie przekracza float64, zachowujemy skończone naruszenie
        # z modelu znormalizowanego zamiast wpisywać `inf` do raportu.
        balance_violation = balance_violation_normalized
    contribution_limit = _contribution_limit(
        target_original, config.max_contribution_share
    )
    contribution_violation = float(
        np.maximum(
            maximum_absolute_profile * weights - contribution_limit,
            0.0,
        ).max(initial=0.0)
    )
    required_violation = 0.0
    for client_id, required_weight in group_required.items():
        index = local_position[client_id]
        required_violation = max(
            required_violation,
            abs(binary_values[index] - 1.0),
            abs(weights[index] - required_weight),
        )
    max_violation = max(
        count_violation,
        lower_violation,
        upper_violation,
        balance_violation,
        contribution_violation,
        required_violation,
        bound_violation,
        matrix_violation,
        integrality_violation,
        cleaned_bound_violation,
        cleaned_matrix_violation,
        cleaned_integrality_violation,
    )

    objective_value = _safe_sum_absolute(residual)
    node_count = _optional_number(result, "mip_node_count")
    dual_bound = _optional_number(result, "mip_dual_bound")
    scaled_dual_bound = None
    if dual_bound is not None:
        with np.errstate(over="ignore", invalid="ignore"):
            candidate_dual_bound = dual_bound * scale
        if np.isfinite(candidate_dual_bound):
            scaled_dual_bound = candidate_dual_bound
    return GroupResult(
        group=group_name,
        candidate_ids=tuple(candidate_ids),
        selected_weights=selected_weights,
        binary_values=binary_values,
        weights=weights,
        model_balance=model_balance,
        residual=residual,
        objective_value=objective_value,
        status=status,
        status_text=str(result.message),
        has_solution=True,
        optimal=status == 0,
        solve_seconds=solve_seconds,
        mip_gap=_optional_number(result, "mip_gap"),
        mip_dual_bound=scaled_dual_bound,
        mip_node_count=None if node_count is None else int(node_count),
        max_constraint_violation=max_violation,
        weight_lower_bound=lower_weight,
        weight_upper_bound=upper_weight,
        weights_at_upper_bound=int(np.count_nonzero(
            selected_mask & np.isclose(weights, effective_upper, rtol=1e-7, atol=1e-9)
        )),
    )


def solve_selection(
    data: SelectionData,
    config: SelectionConfig,
    on_group_start: Optional[Callable[[str, int, int], None]] = None,
    on_group_complete: Optional[Callable[[GroupResult], None]] = None,
    time_limit_provider: Optional[Callable[[], float]] = None,
) -> SelectionResult:
    """Uruchamia niezależny model dla każdej grupy w1..wn."""

    data.validate()
    config.validate()
    groups = round_robin_groups(data.client_ids, data.excluded, config.group_count)

    # Wszystkie kontrole wag wymaganych wykonujemy przed pierwszym, potencjalnie
    # wielogodzinnym solve. Maksima profili liczymy raz dla całej macierzy.
    profiles_all = np.asarray(data.client_balance, dtype=float)
    target = np.asarray(data.branch_balance, dtype=float)
    maximum_absolute_all = _maximum_absolute_by_column(profiles_all)
    contribution_limit = _contribution_limit(target, config.max_contribution_share)
    caps_all = np.full(len(data.client_ids), np.inf, dtype=float)
    nonzero = maximum_absolute_all > 0
    caps_all[nonzero] = contribution_limit / maximum_absolute_all[nonzero]
    lower_weight, upper_weight = selection_weight_bounds(data, config)
    effective_upper_all = np.minimum(upper_weight, caps_all)
    client_position = {
        client_id: index for index, client_id in enumerate(data.client_ids)
    }
    prepared_groups = []
    for group_index, (group_name, candidate_ids) in enumerate(groups.items()):
        selection_count = (
            None
            if config.exact_clients_per_group is None
            else config.exact_clients_per_group[group_index]
        )
        indices = np.asarray(
            [client_position[client_id] for client_id in candidate_ids], dtype=int
        )
        group_upper = effective_upper_all[indices]
        group_maximum = maximum_absolute_all[indices]
        group_required = {
            client_id: float(data.required_weights[client_id])
            for client_id in candidate_ids
            if client_id in data.required_weights
        }
        if len(group_required) > config.max_clients_per_group:
            raise NoFeasibleSolutionError(
                f"Grupa {group_name} ma więcej wymaganych klientów niż limit wyboru."
            )
        if selection_count is not None and len(group_required) > selection_count:
            raise NoFeasibleSolutionError(
                f"Grupa {group_name} ma {len(group_required)} wymaganych klientów, "
                f"ale dokładny limit wynosi {selection_count}."
            )
        if selection_count is not None and selection_count > len(candidate_ids):
            raise NoFeasibleSolutionError(
                f"Grupa {group_name} ma tylko {len(candidate_ids)} kandydatów, "
                f"a wymaga wyboru {selection_count}."
            )
        _validate_required_weights(
            candidate_ids, group_required, lower_weight, group_upper
        )
        _validate_selection_capacity(group_name, selection_count, lower_weight, group_upper)
        prepared_groups.append(
            (group_name, candidate_ids, group_upper, group_maximum, selection_count)
        )

    results = []
    total_groups = len(prepared_groups)
    for position, (
        group_name,
        candidate_ids,
        group_upper,
        group_maximum,
        selection_count,
    ) in enumerate(prepared_groups, start=1):
        if on_group_start is not None:
            on_group_start(group_name, position, total_groups)
        results.append(
            solve_group(
                data,
                config,
                group_name,
                candidate_ids,
                selection_count=selection_count,
                _effective_upper=group_upper,
                _maximum_absolute_profile=group_maximum,
                time_limit_provider=time_limit_provider,
            )
        )
        if on_group_complete is not None:
            on_group_complete(results[-1])
    return SelectionResult(
        branch=data.branch,
        periods=data.periods,
        branch_balance=np.asarray(data.branch_balance, dtype=float),
        config=config,
        groups=tuple(results),
        required_weights=dict(data.required_weights),
        excluded=frozenset(data.excluded),
    )

