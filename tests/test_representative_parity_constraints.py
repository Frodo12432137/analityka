from __future__ import annotations

import unittest

import numpy as np

from representative_clients.model import SelectionConfig, SelectionData
from representative_clients.report import importance_frames
from representative_clients.solver import solve_selection


def _config(**overrides) -> SelectionConfig:
    values = {
        "max_clients_per_group": 1,
        "group_count": 1,
        "max_contribution_share": 10.0,
        "time_limit_seconds": 30.0,
        "mip_relative_gap": 0.0,
    }
    values.update(overrides)
    return SelectionConfig(**values)


class GamsConstraintParityTests(unittest.TestCase):
    def test_selection_count_is_an_upper_limit(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A", "B"),
            periods=(("2026-01-01", 1), ("2026-01-01", 2)),
            client_balance=np.asarray([[1.0, 0.0], [0.0, 1.0]]),
            branch_balance=np.asarray([1.0, 1.0]),
        )

        group = solve_selection(data, _config()).groups[0]

        self.assertLessEqual(len(group.selected_weights), 1)
        self.assertAlmostEqual(group.objective_value, 1.0, places=7)

    def test_contribution_cap_limits_weight_in_every_period(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[10.0]]),
            branch_balance=np.asarray([100.0]),
        )

        group = solve_selection(
            data, _config(max_contribution_share=0.20)
        ).groups[0]

        self.assertAlmostEqual(group.selected_weights["A"], 2.0, places=7)
        self.assertAlmostEqual(group.model_balance[0], 20.0, places=7)
        self.assertAlmostEqual(group.objective_value, 80.0, places=7)

    def test_candidate_below_minimum_weight_is_fixed_out(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0]]),
            branch_balance=np.asarray([1.0]),
        )

        group = solve_selection(
            data, _config(max_contribution_share=0.01)
        ).groups[0]

        self.assertEqual(group.candidate_ids, ("A",))
        self.assertEqual(group.selected_weights, {})
        self.assertAlmostEqual(group.objective_value, 1.0, places=7)

    def test_four_groups_keep_round_robin_order_after_exclusion(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A", "B", "C", "D", "E", "F"),
            periods=(("2026-01-01", 1),),
            client_balance=np.zeros((1, 6)),
            branch_balance=np.zeros(1),
            excluded=frozenset({"B"}),
        )

        result = solve_selection(data, _config(group_count=4))

        self.assertEqual(
            [group.candidate_ids for group in result.groups],
            [("A", "F"), ("C",), ("D",), ("E",)],
        )

    def test_required_and_excluded_conflict_is_rejected(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.zeros((1, 1)),
            branch_balance=np.zeros(1),
            excluded=frozenset({"A"}),
            required_weights={"A": 1.0},
        )

        with self.assertRaisesRegex(ValueError, "jednocześnie wymagany i wykluczony"):
            solve_selection(data, _config())


class ImportanceParityTests(unittest.TestCase):
    def test_positive_and_negative_shares_match_gams_formulas(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A", "B"),
            periods=(("2026-01-01", 1), ("2026-01-01", 2)),
            client_balance=np.asarray([[2.0, 1.0], [-1.0, -3.0]]),
            branch_balance=np.asarray([3.0, -4.0]),
            required_weights={"A": 1.0, "B": 1.0},
        )
        result = solve_selection(
            data,
            _config(
                max_clients_per_group=2,
                max_contribution_share=10.0,
            ),
        )

        daily, overall = importance_frames(data, result)

        daily_by_client = daily.set_index("klient")
        overall_by_client = overall.set_index("klient")
        self.assertAlmostEqual(daily_by_client.loc["A", "Pobor"], 2 / 3)
        self.assertAlmostEqual(daily_by_client.loc["B", "Pobor"], 1 / 3)
        self.assertAlmostEqual(daily_by_client.loc["A", "Oddanie"], 1 / 4)
        self.assertAlmostEqual(daily_by_client.loc["B", "Oddanie"], 3 / 4)
        self.assertAlmostEqual(overall_by_client.loc["A", "Pobor"], 2 / 3)
        self.assertAlmostEqual(overall_by_client.loc["B", "Oddanie"], 3 / 4)

    def test_zero_denominator_is_reported_as_missing(self) -> None:
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0]]),
            branch_balance=np.asarray([1.0]),
            required_weights={"A": 1.0},
        )
        result = solve_selection(data, _config())

        daily, overall = importance_frames(data, result)

        self.assertTrue(np.isnan(daily.loc[0, "Oddanie"]))
        self.assertTrue(np.isnan(overall.loc[0, "Oddanie"]))


if __name__ == "__main__":
    unittest.main()
