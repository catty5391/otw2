"""Protect first-loading history and the distinction between capacity and loops."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.carden_angle_identification import published_features, fit_capacity, publish as publish_angles
from initial_imperfection_material.tian_ma_qu.parameter_provenance import audit, DEFAULT_SOURCE
from py_view.results_dashboard.server import DashboardData, TMQ_PARAMETER_ROOT

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "initial_imperfection_material/tian_ma_qu" / TMQ_PARAMETER_ROOT


class CapacityEvidenceTests(unittest.TestCase):
    def test_tensile_prehistory_is_excluded_from_virgin_capacity(self):
        rows = published_features()
        self.assertEqual(len(rows), 17)
        self.assertEqual({r["specimen_id"] for r in rows if r["first_cycle"] == "compression"}, set("ABEFGIJLNP"))
        for row in rows:
            if row["first_cycle"] == "tension":
                with self.assertRaises(ValueError): fit_capacity(row)

    def test_force_ratio_uses_coupon_yield_force_not_code_expected_force(self):
        specimen = next(r for r in published_features() if r["specimen_id"] == "P")
        result = fit_capacity(specimen)
        self.assertAlmostEqual(result["conditional_phi"], 12 / 16.7)
        self.assertNotAlmostEqual(result["conditional_phi"], 12 / 18.4)
        lo, hi = result["rounding_only_phi_interval"]
        self.assertLess(lo, result["conditional_phi"])
        self.assertGreater(hi, result["conditional_phi"])
        self.assertFalse(result["full_hysteresis_validated"])
        self.assertFalse(result["calibrated_to_Z30103A6"])
        self.assertLess(result["ga_relative_capacity_error"], .002)

    def test_invalid_capacity_and_nonfinite_features_are_rejected(self):
        row = published_features()[0]
        for value in (0, -1, 46, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fit_capacity({**row, "measured_buckling_capacity_kip": value})

    def test_connection_reinforcement_is_not_lost_in_angle_grouping(self):
        rows = {r["specimen_id"]: r for r in published_features()}
        self.assertEqual(rows["E"]["connection"], "bolted_reinforced")
        self.assertEqual(rows["E"]["reported_net_to_gross_area_ratio"], 1.)
        self.assertEqual(rows["B"]["reported_net_to_gross_area_ratio"], .81)
        self.assertEqual(rows["H"]["reported_net_to_gross_area_ratio"], .93)
        self.assertEqual(rows["A"]["gusset_plate_thickness_in"], .5)
        self.assertEqual(rows["B"]["gusset_plate_thickness_in"], 1.)

    def test_unreviewed_pdf_cannot_be_assigned_to_the_fixed_table(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/"other.pdf"; source.write_bytes(b"%PDF other paper")
            with self.assertRaises(ValueError): publish_angles(root/"result", source)
            self.assertFalse((root/"result").exists())

    @unittest.skipUnless(DEFAULT_SOURCE.exists(), "Saved tower table is local evidence")
    def test_tower_audit_does_not_promote_borrowed_coefficients(self):
        result = audit(DEFAULT_SOURCE)
        self.assertEqual(result["member_count"], 1528)
        self.assertEqual(result["section_count"], 26)
        self.assertFalse(result["physical_calibration_complete"])
        self.assertFalse(result["production_parameters_changed"])
        self.assertEqual(result["coefficient_values"]["rho"], [.03])

    @unittest.skipUnless(DEFAULT_SOURCE.exists(), "Saved tower table is local evidence")
    def test_inconsistent_peak_is_not_silently_described_as_perry(self):
        with DEFAULT_SOURCE.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["phi"] = str(float(rows[0]["phi"]) / 2)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"bad.csv"
            with source.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows[:2])
            with self.assertRaises(ValueError): audit(source)


class ParameterPublicationTests(unittest.TestCase):
    def test_missing_study_and_unknown_schema_do_not_gain_success(self):
        with tempfile.TemporaryDirectory() as folder:
            data = DashboardData(folder)
            self.assertIsNone(data.tian_ma_qu()["parameter_identification"])
            path = data.tmq_root/TMQ_PARAMETER_ROOT/"summary.json"
            path.parent.mkdir(parents=True); path.write_text('{"schema":"unknown"}')
            with self.assertRaises(ValueError): data.tian_ma_qu()

    @unittest.skipUnless((BATCH/"summary.json").exists(), "Parameter study is local evidence")
    def test_published_flags_keep_algorithm_and_experiment_separate(self):
        data = DashboardData(ROOT)
        result = data.tian_ma_qu()["parameter_identification"]
        self.assertFalse(result["production_parameters_changed"])
        self.assertFalse(result["full_hysteresis_validation"])
        angle = result["single_angle_capacity"]
        self.assertEqual(angle["selected_compression_first"], 10)
        self.assertEqual(len(angle["excluded_tension_first"]), 7)
        self.assertFalse(angle["full_hysteresis_validation"])
        for name in ("index.html", "INTEGRATION.md", "single_angle_features/index.html", "tower_audit/summary.json"):
            self.assertIsNotNone(data.tmq_file(f"{TMQ_PARAMETER_ROOT}/{name}"))
        for name in ("../../material.py", "algorithm_check_before_contract_review/summary.json", "unknown.csv"):
            self.assertIsNone(data.tmq_file(f"{TMQ_PARAMETER_ROOT}/{name}"))


if __name__ == "__main__":
    unittest.main()
