"""覆盖缺失/未来时段和误差配对，防止展示口径回退。"""

import unittest

from cecep_console.analysis import dataset
from cecep_console.data import records


class BusinessContractTests(unittest.TestCase):
    def test_full_day_has_96_aligned_intervals(self):
        rows = records("lanneng", "2026-11-19")
        self.assertEqual(len(rows), 96)
        self.assertEqual(rows[0]["time"], "00:00")
        self.assertEqual(rows[-1]["time"], "23:45")
        self.assertTrue(all(row["timestamp"].endswith("+08:00") for row in rows))

    def test_future_actuals_remain_missing(self):
        future = dataset("lanneng", "2026-11-21")
        self.assertTrue(all(row["actual"] is None for row in future["rows"]))
        self.assertEqual(future["metrics"]["generation"]["n"], 0)
        self.assertIsNone(future["metrics"]["generation"]["mae"])

    def test_intraday_energy_and_metrics_use_matched_rows(self):
        data = dataset("lanneng", "2026-11-20")
        valid = [row for row in data["rows"] if row["actual"] is not None]
        metrics = data["metrics"]
        self.assertEqual(metrics["generation"]["n"], len(valid))
        self.assertEqual(metrics["energy_forecast_matched"], round(sum(row["forecast"] * 0.25 for row in valid), 2))
        self.assertEqual(metrics["energy_actual"], round(sum(row["actual"] * 0.25 for row in valid), 2))
        self.assertEqual(metrics["baseline_matched"]["n"], metrics["correction_matched"]["n"])
        self.assertTrue(all(row["corrected"] is None for row in data["rows"] if row["time"] < "10:00"))

    def test_daylight_scope_excludes_night(self):
        data = dataset("lanneng", "2026-11-19", True)
        self.assertTrue(0 < len(data["rows"]) < 96)
        self.assertTrue(all(row["physical"] > 0.1 for row in data["rows"]))


if __name__ == "__main__":
    unittest.main()
