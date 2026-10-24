import unittest
from pathlib import Path

from py_view.results_dashboard import DashboardData


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ResultsDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = DashboardData(PROJECT_ROOT)

    def test_overview_uses_generated_results(self) -> None:
        overview = self.data.overview()

        self.assertEqual(overview["project"]["tower"], "Z30103A6")
        self.assertEqual(overview["tower"]["physical_members"], 1528)
        self.assertTrue(overview["member"]["pre_yield_unloading_passed"])

    def test_curve_endpoints_are_available(self) -> None:
        pushover = self.data.pushover()
        cyclic = self.data.cyclic()

        self.assertIn("segmented_reference", pushover["series"])
        self.assertIn("equivalent_calibrated", pushover["series"])
        self.assertEqual(len(cyclic["targets"]), 6)

    def test_model_and_component_validation(self) -> None:
        self.assertEqual(self.data.normalize_model("equivalent"), "equivalent")
        self.assertEqual(self.data.normalize_component("my"), "my")
        with self.assertRaises(ValueError):
            self.data.normalize_model("unknown")
        with self.assertRaises(ValueError):
            self.data.normalize_component("stress")

    def test_equivalent_force_snapshot_is_physical_member_based(self) -> None:
        database = (
            PROJECT_ROOT
            / "initial_imperfection_material"
            / "results"
            / "full_tower_cyclic"
            / "equivalent"
            / "tower_internal_forces.sqlite"
        )
        if not database.exists():
            self.skipTest("全塔内力数据库未生成")

        snapshot = self.data.force_snapshot("equivalent", 0.0, "p")

        self.assertEqual(snapshot["step"], 0)
        self.assertEqual(len(snapshot["members"]), 1528)
        self.assertIn("a", snapshot["members"][0])

    def test_downloads_are_allowlisted(self) -> None:
        self.assertIsNotNone(self.data.downloadable("tower-report"))
        self.assertIsNone(self.data.downloadable("../../pyproject.toml"))


if __name__ == "__main__":
    unittest.main()
