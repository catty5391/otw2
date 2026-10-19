import unittest

from py_view import TowerLineDashboard


class FakeTowerLineModel:
    node_map = {
        1: {"node_tag": 1, "x": 0.0, "y": 0.0, "z": 0.0},
        2: {"node_tag": 2, "x": 0.0, "y": 0.0, "z": 10.0},
        3: {"node_tag": 3, "x": 0.0, "y": 1.0, "z": 9.0},
        4: {"node_tag": 4, "x": 0.0, "y": 11.0, "z": 9.0},
    }
    element_map = {
        1: {"element_tag": 1, "node_i": 1, "node_j": 2, "tower_id": "tower_1"},
        2: {"element_tag": 2, "node_i": 2, "node_j": 3, "component": "insulator"},
        3: {"element_tag": 3, "node_i": 3, "node_j": 4, "component": "transmission_line"},
    }
    mass_map = {3: {"node_tag": 3, "mx": 2.5, "my": 2.5, "mz": 2.5}}
    transmission_line_map = {
        "line_1": {
            "conductor": {"model": "JL/G1A-400/50", "bundle_count": 1},
            "conductor_length": 10.0,
            "mass_per_length": 1.5103,
            "q_g": 14.816043,
            "total_conductor_mass": 15.103,
        }
    }


class TowerLineDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard = TowerLineDashboard(FakeTowerLineModel())

    def test_summary(self) -> None:
        self.assertEqual(
            self.dashboard.summary(),
            {
                "nodes": 4,
                "elements": 3,
                "lines": 1,
                "height": 10.0,
                "total_conductor_mass": 15.103,
            },
        )

    def test_figure_has_component_groups_and_hidden_nodes(self) -> None:
        figure = self.dashboard.figure_dict()
        trace_names = [trace["name"] for trace in figure["data"]]

        self.assertIn("输电塔", trace_names)
        self.assertIn("绝缘子", trace_names)
        self.assertIn("输电线", trace_names)
        node_trace = next(trace for trace in figure["data"] if trace["name"] == "节点")
        self.assertEqual(node_trace["visible"], "legendonly")

    def test_html_contains_conductor_summary(self) -> None:
        page = self.dashboard.to_html()

        self.assertIn("输电塔—线体系可视化", page)
        self.assertIn("JL/G1A-400/50", page)
        self.assertIn("14.8160", page)


if __name__ == "__main__":
    unittest.main()
