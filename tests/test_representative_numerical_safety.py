from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from representative_clients.model import SelectionConfig, SelectionData
from representative_clients.solver import (
    NoFeasibleSolutionError,
    _build_constraint_matrix,
    _safe_mean_absolute,
    _safe_sum_absolute,
    solve_selection,
)


class NumericalSafetyTests(unittest.TestCase):
    def test_direct_csc_builder_matches_gams_row_layout(self) -> None:
        matrix = _build_constraint_matrix(
            np.asarray([[1.0, 0.0], [2.0, 3.0]]),
            lower_weight=0.5,
            effective_upper=np.asarray([4.0, 5.0]),
        )
        expected = np.asarray(
            [
                [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [-0.5, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, -0.5, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                [-4.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, -5.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 2.0, 3.0, 0.0, -1.0, 0.0, 1.0],
            ]
        )

        np.testing.assert_allclose(matrix.toarray(), expected)

    def test_safe_mean_absolute_does_not_overflow_near_float_limit(self) -> None:
        values = np.asarray([1.0e308, -5.0e307])

        result = _safe_mean_absolute(values)

        self.assertTrue(np.isfinite(result))
        self.assertAlmostEqual(result / 1.0e307, 7.5, places=12)

    def test_unrepresentable_absolute_sum_is_rejected_instead_of_inf(self) -> None:
        with self.assertRaisesRegex(ValueError, "Suma błędów przekracza"):
            _safe_sum_absolute(
                np.asarray([np.finfo(float).max, np.finfo(float).max])
            )

    def test_rejects_material_objective_change_after_cleaning_tiny_binary(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0e7]]),
            branch_balance=np.asarray([1.0]),
        )
        config = SelectionConfig(
            max_clients_per_group=1,
            group_count=1,
            max_contribution_share=1.0e8,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )
        # z jest wystarczajaco bliskie 0, aby przejsc tolerancje calkowitosci,
        # ale przy duzym profilu powiazana waga nadal odtwarza caly target.
        fake = SimpleNamespace(
            status=1,
            message="Time limit reached",
            x=np.asarray([2.0e-8, 1.0e-7, 0.0, 0.0]),
        )

        with patch("scipy.optimize.milp", return_value=fake):
            with self.assertRaisesRegex(
                NoFeasibleSolutionError,
                "zaokrąglenie rozwiązania zmienia funkcję celu",
            ):
                solve_selection(data, config)


if __name__ == "__main__":
    unittest.main()
