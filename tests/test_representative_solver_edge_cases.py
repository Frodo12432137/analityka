from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from representative_clients.model import SelectionConfig, SelectionData
from representative_clients.solver import NoFeasibleSolutionError, _audit_solver_incumbent, solve_selection


class ConfigurationValidationTests(unittest.TestCase):
    def test_rejects_non_integer_group_limits(self) -> None:
        for value in (1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SelectionConfig(max_clients_per_group=value).validate()

    def test_rejects_non_finite_numeric_options(self) -> None:
        cases = (
            {"max_contribution_share": math.nan},
            {"time_limit_seconds": math.inf},
            {"mip_relative_gap": -math.inf},
            {"weight_lower_factor": math.nan},
            {"weight_upper_factor": math.inf},
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    SelectionConfig(**values).validate()


class IncumbentAuditTests(unittest.TestCase):
    def test_rejects_non_finite_solution(self) -> None:
        with self.assertRaises(NoFeasibleSolutionError):
            _audit_solver_incumbent(
                np.asarray([np.nan]),
                np.asarray([0.0]),
                np.asarray([1.0]),
                np.asarray([1]),
                np.asarray([[1.0]]),
                np.asarray([0.0]),
                np.asarray([1.0]),
            )

    def test_rejects_fractional_binary(self) -> None:
        with self.assertRaisesRegex(NoFeasibleSolutionError, "całkowitość"):
            _audit_solver_incumbent(
                np.asarray([0.49]),
                np.asarray([0.0]),
                np.asarray([1.0]),
                np.asarray([1]),
                np.asarray([[1.0]]),
                np.asarray([0.0]),
                np.asarray([1.0]),
            )


class SolverInputEdgeCaseTests(unittest.TestCase):
    @staticmethod
    def _one_client_data() -> SelectionData:
        return SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0]]),
            branch_balance=np.asarray([1.0]),
        )

    @staticmethod
    def _one_client_config() -> SelectionConfig:
        return SelectionConfig(
            max_clients_per_group=1,
            group_count=1,
            max_contribution_share=10.0,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )

    def test_feasible_time_limit_incumbent_is_kept_but_not_optimal(self) -> None:
        fake = SimpleNamespace(
            status=1,
            message="Time limit reached",
            x=np.asarray([1.0, 1.0, 0.0, 0.0]),
            mip_gap=0.25,
            mip_dual_bound=0.75,
            mip_node_count=4,
        )
        with patch("scipy.optimize.milp", return_value=fake):
            group = solve_selection(
                self._one_client_data(), self._one_client_config()
            ).groups[0]

        self.assertTrue(group.has_solution)
        self.assertFalse(group.optimal)
        self.assertEqual(group.selected_weights, {"A": 1.0})

    def test_incumbent_with_solver_error_status_is_rejected(self) -> None:
        fake = SimpleNamespace(
            status=4,
            message="Solver error",
            x=np.asarray([1.0, 1.0, 0.0, 0.0]),
        )
        with patch("scipy.optimize.milp", return_value=fake):
            with self.assertRaisesRegex(NoFeasibleSolutionError, "statusie 4"):
                solve_selection(self._one_client_data(), self._one_client_config())

    def test_invalid_required_weight_is_rejected_before_first_group_solve(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A", "B", "C", "D"),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0, 1.0, 1.0, 1.0]]),
            branch_balance=np.asarray([1.0]),
            required_weights={"D": 100.0},
        )
        config = SelectionConfig(
            max_clients_per_group=1,
            group_count=4,
            max_contribution_share=10.0,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )
        started_groups = []

        with self.assertRaisesRegex(NoFeasibleSolutionError, "Wymagana waga"):
            solve_selection(
                data,
                config,
                on_group_start=lambda name, position, total: started_groups.append(name),
            )

        self.assertEqual(started_groups, [])

    def test_accepts_list_backed_input_after_validation(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=[[1.0]],
            branch_balance=[2.0],
        )
        config = SelectionConfig(
            max_clients_per_group=1,
            group_count=1,
            max_contribution_share=10.0,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )

        group = solve_selection(data, config).groups[0]

        self.assertEqual(group.selected_weights, {"A": 2.0})
        np.testing.assert_allclose(group.model_balance, [2.0])

    def test_required_zero_weight_remains_selected(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[0.0]]),
            branch_balance=np.asarray([0.0]),
            required_weights={"A": 0.0},
        )
        config = SelectionConfig(
            max_clients_per_group=1,
            group_count=1,
            max_contribution_share=0.20,
            weight_lower_factor=0.0,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )

        group = solve_selection(data, config).groups[0]

        self.assertEqual(group.selected_weights, {"A": 0.0})
        self.assertEqual(group.binary_values.round().tolist(), [1.0])


if __name__ == "__main__":
    unittest.main()
