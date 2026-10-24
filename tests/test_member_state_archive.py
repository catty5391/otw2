import gzip
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.state_archive import iter_archive_states


class MemberStateArchiveTests(unittest.TestCase):
    def test_small_chunks_preserve_states_and_ignore_nested_key_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.json.gz"
            rows = [{"number": 123456789, "text": 'escaped "states" and \\ path', "nested": [1, 2, {"ok": True}]},
                    {"number": -1.25e-15, "text": "中文", "nested": []}]
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump({"metadata": {"states": ["not the target"]}, "number": 1.23456e-12, "states": rows, "tail": "unused"}, stream)
            self.assertEqual(list(iter_archive_states(path, chunk_size=7)), rows)

    def test_empty_state_list_and_missing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.json"
            path.write_text('{"states": []}', encoding="utf-8")
            self.assertEqual(list(iter_archive_states(path, chunk_size=2)), [])
            path.write_text('{"other": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no top-level"):
                list(iter_archive_states(path, chunk_size=2))

    def test_truncated_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "states.json"
            path.write_text('{"states": [{"force": [1,2', encoding="utf-8")
            with self.assertRaises(ValueError):
                list(iter_archive_states(path, chunk_size=3))


if __name__ == "__main__":
    unittest.main()
