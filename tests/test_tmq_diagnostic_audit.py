"""N00/N01 audit invariants using saved data and small synthetic ledgers; no FE."""
import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from initial_imperfection_material.tian_ma_qu.diagnostic_audit import (
    ROOT, TMQ, EXPECTED_MUTABLE_SOURCE, audit_case, compare_snapshot, file_sha,
    initial_snapshot, line_geometry, load_first_state, nodal_mass_audit, read_csv, run, runtime_binary_identity,
)


class MassLedgerTests(unittest.TestCase):
    def test_physical_mass_not_three_times_directional_sum(self):
        mass = np.array([[2, 2, 2, 0, 0, 0], [5, 5, 5, 0, 0, 0]], float)
        fixed = np.array([[True]*6, [False]*3+[True]*3])
        tower = np.array([[2, 2, 2, 0, 0, 0], [3, 3, 3, 0, 0, 0]], float)
        cable = np.array([[0]*6, [1, 1, 1, 0, 0, 0]], float)
        result = nodal_mass_audit(mass, fixed, tower, cable)
        self.assertEqual(result["physical_mass_kg"], 7)
        self.assertEqual(result["free_XYZ_kg"], [5, 5, 5])
        self.assertEqual(result["fixed_XYZ_kg"], [2, 2, 2])
        self.assertEqual(result["component_kg"], {"tower": 5, "cable": 1, "insulator": 1})

    def test_rejects_shape_nonfinite_negative_and_overallocated_components(self):
        good = np.ones((2, 6))
        fixed = np.zeros((2, 6), bool)
        zero = np.zeros_like(good)
        with self.assertRaises(ValueError):
            nodal_mass_audit(good[:, :3], fixed, zero, zero)
        for value in (-1., float("nan")):
            bad = good.copy(); bad[0, 0] = value
            with self.assertRaises(ValueError):
                nodal_mass_audit(bad, fixed, zero, zero)
        with self.assertRaises(ValueError):
            nodal_mass_audit(good, fixed.astype(int), zero, zero)
        with self.assertRaises(ValueError):
            nodal_mass_audit(good, fixed, good, good)


class GeometryAndStateTests(unittest.TestCase):
    def test_sag_uses_sloping_chord_and_is_translation_invariant(self):
        points = np.array([[0, 0, 4], [0, 5, 2], [0, 10, 6]], float)
        result = line_geometry(points)
        shifted = line_geometry(points + [12, -23, 100])
        self.assertAlmostEqual(result["maximum_chord_sag_m"], 3)
        self.assertAlmostEqual(result["horizontal_span_m"], 10)
        self.assertAlmostEqual(result["arc_length_m"], np.sqrt(29)+np.sqrt(41))
        self.assertAlmostEqual(result["maximum_chord_sag_m"], shifted["maximum_chord_sag_m"])

    def test_invalid_line_geometry_fails(self):
        for points in ([[0, 0, 0], [0, 0, 2]], [[0, 0, 0], [0, 0, 0], [0, 2, 0]], [[0, 0, 0], [0, 2, float("nan")]]):
            with self.assertRaises(ValueError):
                line_geometry(points)

    def _write_states(self, path, rows):
        with gzip.open(path, "wt", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["step", "node_tag", "ux", "uy", "uz", "rx", "ry", "rz"])
            writer.writerows(rows)

    def test_gravity_reader_stops_before_later_nonlinear_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.csv.gz"
            self._write_states(path, [[0, 10, 1, 2, 3, 4, 5, 6], [1, 10, 99, 99, 99, 99, 99, 99]])
            self.assertEqual(load_first_state(path)[10].tolist(), [1, 2, 3, 4, 5, 6])

    def test_duplicate_missing_or_nonfinite_gravity_state_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.csv.gz"
            for rows in ([[0, 10, 0, 0, 0, 0, 0, 0]]*2,
                         [[1, 10, 0, 0, 0, 0, 0, 0]],
                         [[0, 10, float("nan"), 0, 0, 0, 0, 0]]):
                self._write_states(path, rows)
                with self.assertRaises(ValueError):
                    load_first_state(path)

    def test_required_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.csv"
            path.write_text("node_tag,x\n1,2\n")
            with self.assertRaises(ValueError):
                read_csv(path, ("node_tag", "z"))


class BaselineEvidenceTests(unittest.TestCase):
    def _fixture(self, root):
        publisher = root / EXPECTED_MUTABLE_SOURCE
        evidence = root / "initial_imperfection_material/tian_ma_qu/modal_results/summary.json"
        for path in (publisher, evidence):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("original")
        baseline = root / "BASELINE.json"
        baseline.write_text(json.dumps({"protected_files": [{"path": str(p.relative_to(root)), "size_bytes": p.stat().st_size,
                                                              "sha256": file_sha(p)} for p in (publisher, evidence)]}))
        return publisher, evidence, baseline

    def test_declared_publisher_change_does_not_relabel_evidence_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); publisher, evidence, baseline = self._fixture(root)
            snapshot = initial_snapshot(root, baseline)
            publisher.write_text("new publisher")
            result = compare_snapshot(snapshot, root, [EXPECTED_MUTABLE_SOURCE])
            self.assertTrue(result["passed"])
            self.assertFalse(result["current_all_match_initial"])
            self.assertEqual(result["files"][0]["status"], "expected_publisher_source_change")
            self.assertEqual(snapshot["files"][0]["actual_sha256"], snapshot["files"][0]["sha256"])

    def test_changed_or_missing_historical_evidence_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); publisher, evidence, baseline = self._fixture(root)
            snapshot = initial_snapshot(root, baseline)
            evidence.write_text("changed result")
            self.assertFalse(compare_snapshot(snapshot, root, [EXPECTED_MUTABLE_SOURCE])["passed"])
            with self.assertRaises(ValueError):
                compare_snapshot(snapshot, root, [str(evidence.relative_to(root))])
            evidence.unlink()
            self.assertFalse(compare_snapshot(snapshot, root)["passed"])

    def test_initial_mismatch_is_not_forgiven_by_expected_later_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); publisher, evidence, baseline = self._fixture(root)
            publisher.write_text("already changed before capture")
            snapshot = initial_snapshot(root, baseline)
            self.assertFalse(compare_snapshot(snapshot, root, [EXPECTED_MUTABLE_SOURCE])["passed"])

    def test_historical_output_and_completed_output_are_rejected(self):
        with self.assertRaises(ValueError):
            run(TMQ / "modal_results" / "forbidden_audit")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory); (output / "model_contract.json").write_text("{}")
            with self.assertRaises(FileExistsError):
                run(output)


class SavedEvidenceIntegrationTests(unittest.TestCase):
    def test_installed_engine_bridge_and_source_match_saved_binary_identity(self):
        saved = json.loads((TMQ / "wind_speed_results/runs/tower_line_45_disp/summary.json").read_text())
        actual = runtime_binary_identity(saved["native_metadata"])
        self.assertTrue(actual["all_match_saved"], actual)
        self.assertTrue(actual["wrapper_version_is_not_engine_version"])

    def test_four_saved_model_mass_constraint_and_geometry_ledgers(self):
        for key in ("bare_checked", "coupled_20_checked", "coupled_40_checked", "coupled_80_checked"):
            with self.subTest(case=key):
                contract, files = audit_case(TMQ / "modal_results/runs" / key)
                self.assertTrue(contract["checks_passed"], contract["checks"])
                self.assertEqual(contract["nodes"]["tower_count"], 621)
                self.assertEqual(contract["elements"]["tower_physical_count"], 1528)
                self.assertLess(contract["mass"]["audit_errors_kg"]["matrix_diagonal"], 1e-8)
                self.assertEqual(contract["physical_validation"], "unvalidated")
                self.assertTrue(all(path.is_file() for path in files))


if __name__ == "__main__":
    unittest.main()
