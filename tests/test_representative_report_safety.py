from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from representative_clients.model import SelectionConfig, SelectionData
from representative_clients.report import validate_report_capacity, write_result_workbook
from representative_clients.solver import solve_selection


class AtomicReportTests(unittest.TestCase):
    @staticmethod
    def _solved_case():
        data = SelectionData(
            branch="PGED_TEST",
            client_ids=("A",),
            periods=(("2026-01-01", 1),),
            client_balance=np.asarray([[1.0]]),
            branch_balance=np.asarray([1.0]),
        )
        config = SelectionConfig(
            max_clients_per_group=1,
            group_count=1,
            max_contribution_share=10.0,
            time_limit_seconds=30.0,
            mip_relative_gap=0.0,
        )
        return data, solve_selection(data, config)

    def test_failed_export_does_not_damage_existing_output(self) -> None:
        data, result = self._solved_case()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "wynik.xlsx"
            target.write_bytes(b"poprzedni-poprawny-wynik")

            with patch(
                "representative_clients.report.pd.ExcelWriter",
                side_effect=RuntimeError("symulowany błąd eksportu"),
            ):
                with self.assertRaisesRegex(RuntimeError, "symulowany"):
                    write_result_workbook(data, result, target, overwrite=True)

            self.assertEqual(target.read_bytes(), b"poprzedni-poprawny-wynik")
            self.assertEqual(tuple(Path(directory).iterdir()), (target,))

    def test_competing_output_is_never_overwritten_without_permission(self) -> None:
        data, result = self._solved_case()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "wynik.xlsx"

            def competing_writer(source, destination):
                Path(destination).write_bytes(b"wynik-innego-procesu")
                raise FileExistsError(destination)

            with patch(
                "representative_clients.report.os.link",
                side_effect=competing_writer,
            ):
                with self.assertRaisesRegex(FileExistsError, "podczas eksportu"):
                    write_result_workbook(data, result, target, overwrite=False)

            self.assertEqual(target.read_bytes(), b"wynik-innego-procesu")
            self.assertEqual(tuple(Path(directory).iterdir()), (target,))

    def test_excel_row_limit_is_checked_before_solving(self) -> None:
        data, result = self._solved_case()

        with patch("representative_clients.report.EXCEL_MAX_ROWS", 2):
            with self.assertRaisesRegex(ValueError, "limit Excela"):
                validate_report_capacity(data, result.config)


if __name__ == "__main__":
    unittest.main()
