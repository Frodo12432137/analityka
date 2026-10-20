"""Regresje na danych syntetycznych, bez identyfikatorów i wyników użytkownika."""
from contextlib import redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np
from openpyxl import Workbook, load_workbook

from representative_clients.model import SelectionConfig, SelectionData
from representative_clients.portfolio_cli import main
from representative_clients.portfolio_data import inspect_workbook_clients
from representative_clients.portfolio_report import _style_workbook
from representative_clients.replacement import choose_unique_reserves
from representative_clients.solver import solve_group, solve_selection
from tests.test_representative_new_consents import records


class WeightPopulationTests(unittest.TestCase):
    @staticmethod
    def case():
        data = SelectionData(
            branch="PGED_Bialystok",
            client_ids=tuple(f"TEST{i}" for i in range(20)),
            periods=(("2026-01-01", 1), ("2026-01-01", 2)),
            client_balance=np.tile([[1.0], [-0.5]], (1, 20)),
            branch_balance=np.array([10000.0, -5000.0]),
        )
        config = SelectionConfig(
            group_count=2, max_clients_per_group=10,
            exact_clients_per_group=(10, 10), mip_relative_gap=0,
        )
        return data, config

    def test_source_population_restores_scale_and_both_solver_paths_agree(self):
        data, config = self.case()
        old = solve_selection(data, config)
        self.assertAlmostEqual(old.groups[0].objective_value / 15000, 0.99)
        self.assertEqual(old.groups[0].weights_at_upper_bound, 10)
        fixed = replace(config, weight_population_size=4000)
        result = solve_selection(data, fixed)
        self.assertEqual(result.selected_count, 20)
        for group in result.groups:
            np.testing.assert_allclose(group.model_balance, data.branch_balance, atol=1e-7)
            self.assertLess(group.objective_value, 1e-7)
            self.assertEqual(group.weight_upper_bound, 2000)
            self.assertEqual(group.weight_lower_bound, 40)
            direct = solve_group(data, fixed, group.group, group.candidate_ids, selection_count=10)
            np.testing.assert_allclose(direct.model_balance, group.model_balance, atol=1e-7)

    def test_population_does_not_remove_contribution_cap(self):
        data, config = self.case()
        result = solve_selection(data, replace(
            config, weight_population_size=4000, max_contribution_share=0.01,
        ))
        for group in result.groups:
            self.assertTrue(all(w <= 75 + 1e-7 for w in group.selected_weights.values()))
            self.assertEqual(group.weights_at_upper_bound, 10)
            self.assertGreater(group.objective_value, 0)

    def test_reserves_can_match_primary_weights_above_legacy_limit(self):
        data, config = self.case()
        data = replace(data, branch_balance=data.branch_balance * 10)
        config = replace(config, group_count=1, exact_clients_per_group=(10,),
                         weight_population_size=40000)
        result = solve_selection(data, config)
        self.assertLess(result.groups[0].objective_value, 1e-7)
        self.assertTrue(any(w > 3000 for w in result.groups[0].selected_weights.values()))
        replacements = choose_unique_reserves(data, result)
        self.assertEqual(len(replacements.matches), 10)
        self.assertTrue(all(match.l1_error < 1e-7 for match in replacements.matches))
        self.assertLess(replacements.diagnostics[0].l1_after_replacement, 1e-7)
        limited = choose_unique_reserves(data, result, maximum_weight=3000)
        self.assertGreater(limited.diagnostics[0].l1_after_replacement, 1)

    def test_invalid_population_is_rejected_and_default_is_legacy(self):
        data, config = self.case()
        for value in (0, -1, True, 1.5, float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(config, weight_population_size=value).validate()
        with self.assertRaisesRegex(ValueError, "mniejsza"):
            solve_selection(data, replace(config, weight_population_size=19))
        result = solve_selection(data, config)
        self.assertEqual(result.groups[0].weight_upper_bound, 10)

    @staticmethod
    def source_book():
        book = Workbook()
        clients = book.active
        clients.title = "Klienci"
        clients.append(["PPE"])
        for i in range(4000):
            clients.append([f"TEST{i}"])
        target = book.create_sheet("Oddzial")
        target.append(["Bilans"])
        target.append(["Oddzial", "Data", 1, 2])
        target.append(["PGED_Bialystok", "2026-01-01", 10000, -5000])
        for name in ("Klienci_part_1", "Klienci_part_2"):
            sheet = book.create_sheet(name)
            sheet.append(["Profile"])
            sheet.append(["Oddzial", "Klient", "Data", 1, 2])
        for i in range(20):
            book["Klienci_part_1"].append(["PGED_Bialystok", f"TEST{i}", "2026-01-01", 1, -0.5])
        book.create_sheet("Ograniczenia").append(["Wykluczeni", None, None, None, "Wymagani", "Waga"])
        return book

    def test_portfolio_uses_union_before_consents_including_skipped_part(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.xlsx"
            book = self.source_book()
            book.save(source)
            # Dodatkowa część: duplikaty populacji + nowe PPE, brak kandydatów.
            # Nie może ani zmniejszyć populacji, ani podwoić wspólnych PPE.
            extra = root / "extra.xlsx"
            book["Klienci"].delete_rows(2, 20)
            for i in range(4000, 4100):
                book["Klienci"].append([f"TEST{i}"])
            book["Klienci_part_1"].delete_rows(3, 20)
            book.save(extra)
            book.close()
            consents = root / "consents.xlsx"
            book = Workbook()
            book.active.append(["Kod PP Aktualny", "OSD Nazwa - PP Aktualny"])
            for i in range(20):
                book.active.append([f"TEST{i}", "PGED_Bialystok"])
            book.save(consents)
            book.close()
            output = root / "result.xlsx"
            with redirect_stdout(io.StringIO()):
                code = main([
                    "--input", str(source), "--input", str(extra),
                    "--consents", str(consents), "--all-consented",
                    "--allow-partial", "--groups", "2", "--mip-gap", "0",
                    "--output", str(output),
                ])
            self.assertEqual(code, 0)
            book = load_workbook(output, data_only=True)
            try:
                selected = records(book["Wybrani"])
                self.assertEqual({row["klient"] for row in selected}, {f"TEST{i}" for i in range(20)})
                self.assertTrue(all(row["populacja_do_wag"] == 4100 for row in records(book["Solver"])))
                self.assertTrue(all(row["waga_max_populacja"] == 2050 for row in records(book["Solver"])))
                self.assertTrue(all(abs(row["blad_wzgledny"]) < 1e-7 for row in records(book["Reprezentatywnosc"])))
                for row in records(book["Bilans"]):
                    self.assertAlmostEqual(row["bilans_model"], row["bilans_historyczny"])
                headers = [cell.value for cell in book["Bilans"][1]]
                absolute = book["Bilans"].cell(2, headers.index("blad_bezwzgledny") + 1)
                self.assertNotIn("%", absolute.number_format)
            finally:
                book.close()

    def test_multibranch_population_is_scoped_for_split_and_inline_layouts(self):
        for inline in (False, True):
            with self.subTest(inline=inline), tempfile.TemporaryDirectory() as folder:
                book = self.source_book()
                book["Oddzial"].append(["PGED_Lublin", "2026-01-01", 20, -10])
                book["Klienci_part_1"].append(["PGED_Lublin", "TEST20", "2026-01-01", 2, -1])
                # Ten sam PPE i inna data nie zwiększają liczebności populacji.
                book["Klienci_part_2"].append(["PGED_Bialystok", "TEST0", "2026-01-02", 1, -0.5])
                if inline:
                    del book["Klienci"]
                    book["Klienci_part_1"].append(["PGED_Bialystok", "TEST0", "2026-01-02", 1, -0.5])
                    del book["Klienci_part_2"]
                    book["Klienci_part_1"].title = "Klienci"
                path = Path(folder) / "source.xlsx"
                book.save(path)
                book.close()
                population, allowed, _, _ = inspect_workbook_clients(
                    path, {"TEST0", "TEST20"}, branch="PGED_Bialystok",
                )
                self.assertEqual(population, {f"TEST{i}" for i in range(20)})
                self.assertEqual(allowed, {"TEST0"})
                population, allowed, _, _ = inspect_workbook_clients(
                    path, {"TEST0", "TEST20"}, branch="PGED_Lublin",
                )
                self.assertEqual(population, {"TEST20"})
                self.assertEqual(allowed, {"TEST20"})


class PercentageFormatTests(unittest.TestCase):
    def test_absolute_errors_are_numbers_and_relative_errors_are_percentages(self):
        book = Workbook()
        sheet = book.active
        sheet.append(["blad_bezwzgledny", "blad_model_minus_historia", "blad_wzgledny",
                      "bias_wzgledny", "mip_gap", "L1", "wymagany"])
        sheet.append([123.45, -123.45, 0.99, -0.99, 0, 123.45, False])
        sheet.append([123, -123, 1, -1, 1, 123, True])
        _style_workbook(book)
        for row in (2, 3):
            for col in (1, 2, 6, 7):
                self.assertNotIn("%", sheet.cell(row, col).number_format)
            for col in (3, 4, 5):
                self.assertEqual(sheet.cell(row, col).number_format, "0.0%")
        self.assertEqual(sheet["A2"].value, 123.45)
        book.close()


if __name__ == "__main__":
    unittest.main()
