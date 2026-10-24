import gzip
import json
from pathlib import Path
import tempfile
import unittest

from scripts.result_archives import digest, restore


class ResultArchiveTests(unittest.TestCase):
    def fixture(self, root):
        payload = b"saved scientific data\n" * 100
        original = root / "sample"
        original.write_bytes(payload)
        sha = digest(original)
        original.unlink()
        archive = root / "sample.gz"
        archive.write_bytes(gzip.compress(payload, mtime=0))
        return {"schema": "otw2.result_archives.v1", "files": [{"path": "results/sample.csv",
                "bytes": len(payload), "sha256": sha, "archive": "sample.gz", "archive_sha256": digest(archive)}]}

    def test_restore_exact_bytes_and_existing_files_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            self.assertEqual(restore(root, manifest, True)["missing"], 1)
            self.assertEqual(restore(root, manifest)["restored"], 1)
            self.assertEqual(restore(root, manifest)["already_present"], 1)
            self.assertEqual(digest(root / "results/sample.csv"), manifest["files"][0]["sha256"])

    def test_corrupt_archive_and_differing_existing_result_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            (root / "sample.gz").write_bytes(b"corrupt")
            with self.assertRaises(ValueError): restore(root, manifest)
            target = root / "results/sample.csv"; target.parent.mkdir(); target.write_text("keep")
            with self.assertRaises(FileExistsError): restore(root, manifest)
            self.assertEqual(target.read_text(), "keep")

    def test_manifest_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            manifest["files"][0]["path"] = "../outside.csv"
            with self.assertRaises(ValueError): restore(root, manifest)

    def test_split_gzip_stream_restores_in_manifest_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            data = (root / "sample.gz").read_bytes(); parts = []
            for index, block in enumerate((data[:13], data[13:])):
                path = root / f"part{index}"; path.write_bytes(block)
                parts.append({"path": path.name, "sha256": digest(path)})
            manifest["files"][0]["parts"] = parts
            del manifest["files"][0]["archive"]
            del manifest["files"][0]["archive_sha256"]
            self.assertEqual(restore(root, manifest)["restored"], 1)
            self.assertEqual(digest(root / "results/sample.csv"), manifest["files"][0]["sha256"])

