import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.member_reference_extension import extend_mesh


class MemberReferenceExtensionGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source.s2k"
        self.history = self.root / "history.jsonl"
        self.study = self.root / "study.json"
        self.source.write_text("fixture-source", encoding="utf-8")
        self.history.write_text("fixture-history", encoding="utf-8")
        (self.root / "run_manifest.json").write_text('{"status":"completed"}', encoding="utf-8")
        self.data = {"source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "history_sha256": hashlib.sha256(self.history.read_bytes()).hexdigest(),
            "members": [{"member_id": 825, "stop_reason": None, "mesh_thresholds_passed": False,
                "cases": [{"divisions": 4, "matching_mesh_passed": True}, {"divisions": 16, "execution_status": "completed"}]}]}

    def tearDown(self):
        self.directory.cleanup()

    def run_gate(self):
        self.study.write_text(json.dumps(self.data), encoding="utf-8")
        return extend_mesh(self.source, self.history, self.study, self.root / "out", member_id=825, divisions=32)

    def test_changed_source_or_history_is_rejected_before_build(self):
        self.data["source_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "same source"):
            self.run_gate()
        self.assertFalse((self.root / "out").exists())

    def test_matching_mesh_gate_failure_is_rejected_before_refinement(self):
        self.data["members"][0]["cases"][0]["matching_mesh_passed"] = False
        with self.assertRaisesRegex(ValueError, "failed matching"):
            self.run_gate()
        self.assertFalse((self.root / "out").exists())

    def test_incomplete_or_already_converged_prior_mesh_is_rejected(self):
        self.data["members"][0]["cases"][-1]["execution_status"] = "not_converged"
        with self.assertRaisesRegex(ValueError, "completed prior"):
            self.run_gate()
        self.data["members"][0]["cases"][-1]["execution_status"] = "completed"
        self.data["members"][0]["mesh_thresholds_passed"] = True
        with self.assertRaisesRegex(ValueError, "only extends"):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
