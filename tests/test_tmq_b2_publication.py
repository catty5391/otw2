"""A completed diagnostic may remain limited; model states must stay distinct."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.publish_followup import (
    SCHEMAS, check_baseline, make_summary, publish, read_components,
)
from py_view.results_dashboard.server import DashboardData, TMQ_B2_ROOT

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "initial_imperfection_material/tian_ma_qu" / TMQ_B2_ROOT


def write_parts(root):
    for name, schema in SCHEMAS.items():
        target = root/name/"summary.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"schema": schema, "execution_status": "complete", "assessment": "limited",
                                     "physical_validation": "unvalidated", "new_FE_runs": 4 if name == "insulator_grid" else 0,
                                     "new_eigen_solves": 1 if name == "frequency_response" else 0}))


class B2PublicationContractTests(unittest.TestCase):
    def test_completed_diagnostics_preserve_limitations_and_distinct_states(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); write_parts(root)
            parts = read_components(root)
            result = make_summary(root, parts, {"passed": True})
            self.assertEqual(result["execution_status"], "complete")
            self.assertEqual(result["assessment"], "limited")
            self.assertEqual(result["physical_validation"], "unvalidated")
            self.assertEqual(result["gates"]["G2"], "not_passed")
            self.assertEqual((result["new_FE_runs"], result["new_eigen_solves"]), (4, 1))
            scopes = [r["scope"] for r in result["components"].values()]
            self.assertIn("严格仅受拉", scopes[0]); self.assertIn("历史弹性", scopes[1])
            parts["frequency_response"]["execution_status"] = "partial"
            self.assertEqual(make_summary(root, parts, {})["execution_status"], "partial")

    def test_schema_physical_upgrade_running_and_invalid_counts_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); write_parts(root)
            path = root/"frequency_response/summary.json"
            original = json.loads(path.read_text())
            for field, value in [("schema", "unknown"), ("physical_validation", "validated"),
                                 ("execution_status", "running"), ("assessment", "unknown"),
                                 ("new_FE_runs", -1), ("new_eigen_solves", True)]:
                with self.subTest(field=field):
                    path.write_text(json.dumps({**original, field: value}))
                    with self.assertRaises(ValueError): read_components(root)

    def test_changed_or_missing_baseline_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root/"source.txt"; source.write_text("frozen")
            (root/"baseline.json").write_text(json.dumps({"sha256": {"source.txt": hashlib.sha256(source.read_bytes()).hexdigest()}}))
            self.assertTrue(check_baseline(root, root)["passed"])
            source.write_text("changed")
            with self.assertRaises(ValueError): check_baseline(root, root)
            source.unlink()
            with self.assertRaises(ValueError): check_baseline(root, root)

    def test_protected_publication_and_unknown_api_schema(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/"summary.json").write_text("{}")
            with self.assertRaises(FileExistsError): publish(root)
            p = root/"initial_imperfection_material/tian_ma_qu"/TMQ_B2_ROOT/"summary.json"
            p.parent.mkdir(parents=True); p.write_text('{"schema":"unknown"}')
            with self.assertRaises(ValueError): DashboardData(root).tian_ma_qu()


@unittest.skipUnless((BATCH/"summary.json").exists(), "B2 saved evidence not installed")
class B2SavedPublicationTests(unittest.TestCase):
    def test_summary_hashes_and_unverified_actual_damping(self):
        summary = json.loads((BATCH/"summary.json").read_text())
        for name, digest in summary["source_sha256"].items():
            self.assertEqual(hashlib.sha256((BATCH/name).read_bytes()).hexdigest(), digest)
        data = DashboardData(ROOT).tian_ma_qu()["b2_followup"]
        self.assertEqual(data["physical_validation"], "unvalidated")
        self.assertEqual(data["gates"]["actual_dynamic_damping"], "unverified")

    def test_fixed_evidence_paths_do_not_expose_source_or_workspace(self):
        data = DashboardData(ROOT)
        for name in ("index.html", "summary.json", "REPORT.md", "insulator_grid/summary.json", "frequency_response/summary.json"):
            self.assertTrue(data.tmq_file(f"{TMQ_B2_ROOT}/{name}").is_file())
        for name in ("baseline.json", "../../../material.py", "insulator_grid/runs/unknown/history.csv"):
            self.assertIsNone(data.tmq_file(f"{TMQ_B2_ROOT}/{name}"))


if __name__ == "__main__":
    unittest.main()
