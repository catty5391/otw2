import tempfile
import unittest
from pathlib import Path

from util import TowerInternalForceHistory, TowerInternalForceRecorder


class FakeOps:
    def __init__(self) -> None:
        self.time = 0.0

    def getTime(self) -> float:
        return self.time

    def eleResponse(self, element_tag: int, response: str) -> list[float]:
        assert response == "localForce"
        return [float(element_tag) + self.time] * 12


class FakeModel:
    def __init__(self) -> None:
        self.ops = FakeOps()
        self.element_map = {
            1: {"element_tag": 1, "tower_id": "tower_1", "node_i": 1, "node_j": 2},
            2: {"element_tag": 2, "tower_id": "tower_1", "node_i": 2, "node_j": 3},
            3: {
                "element_tag": 3,
                "component": "transmission_line",
                "node_i": 3,
                "node_j": 4,
            },
        }


class FakeTrussOps(FakeOps):
    def eleResponse(self, element_tag: int, response: str) -> list[float]:
        if response == "localForce":
            return []
        if response == "axialForce":
            return [12.5]
        raise AssertionError(response)


class TowerInternalForceRecorderTests(unittest.TestCase):
    def test_truss_axial_force_is_expanded_to_beam_database_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = FakeModel()
            model.ops = FakeTrussOps()
            recorder = TowerInternalForceRecorder(
                model,
                Path(directory) / "truss_recorded.sqlite",
            )
            recorder.capture(step=0)
            history = recorder.close()
            rows = list(history.iter_history())
            self.assertEqual(rows[0]["p_i"], -12.5)
            self.assertEqual(rows[0]["p_j"], 12.5)
            self.assertEqual(rows[0]["vy_i"], 0.0)

    def test_record_query_snapshot_and_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "forces.sqlite"
            model = FakeModel()
            recorder = TowerInternalForceRecorder(model, database)
            self.assertEqual(recorder.capture(step=0), 2)
            model.ops.time = 1.0
            self.assertEqual(recorder.capture(step=1), 2)
            history = recorder.close()

            self.assertIsInstance(history, TowerInternalForceHistory)
            self.assertEqual(history.time_range(), (0.0, 1.0))
            self.assertEqual(len(list(history.iter_history(start_time=0.5))), 2)
            snapshot = history.snapshot(0.8)
            self.assertEqual(len(snapshot), 2)
            self.assertTrue(all(row["time"] == 1.0 for row in snapshot))
            envelope = history.envelope(start_time=0.0, end_time=1.0)
            self.assertEqual(len(envelope), 2)
            self.assertEqual(envelope[1]["p_i_abs_max"], 3.0)

            csv_path = history.export_snapshot_csv(Path(directory) / "snapshot.csv", 1.0)
            self.assertTrue(csv_path.exists())


if __name__ == "__main__":
    unittest.main()
