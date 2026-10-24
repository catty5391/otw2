"""Pack local result files without removing them; restore separately supplied archives.

Run from any directory: python scripts/result_archives.py restore
Archives are not included in the source/documentation publication.
No third-party dependencies; existing differing files are never overwritten.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = Path("artifacts/result_archives")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path outside repository: {relative}")
    return path


def restore(root: Path, manifest: dict, verify_only: bool = False) -> dict:
    if manifest.get("schema") != "otw2.result_archives.v1":
        raise ValueError("Unsupported archive schema")
    counts = {"restored": 0, "already_present": 0, "missing": 0}
    for entry in manifest["files"]:
        target = safe_path(root, entry["path"])
        parts = entry.get("parts") or [{"path": entry["archive"], "sha256": entry["archive_sha256"]}]
        archives = [(safe_path(root, part["path"]), part) for part in parts]
        if target.exists():
            if target.stat().st_size != entry["bytes"] or digest(target) != entry["sha256"]:
                raise FileExistsError(f"Existing result differs; preserve it before restoring: {target}")
            counts["already_present"] += 1
            continue
        if verify_only:
            counts["missing"] += 1
            continue
        for archive, part in archives:
            if digest(archive) != part["sha256"]:
                raise ValueError(f"Archive checksum mismatch: {archive}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            # Parts are byte slices of one gzip stream, not independent gzip files.
            with tempfile.TemporaryFile(dir=target.parent) as compressed:
                for archive, _ in archives:
                    with archive.open("rb") as source:
                        shutil.copyfileobj(source, compressed, 1024 * 1024)
                compressed.seek(0)
                with gzip.GzipFile(fileobj=compressed, mode="rb") as source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
            if temporary.stat().st_size != entry["bytes"] or digest(temporary) != entry["sha256"]:
                raise ValueError(f"Restored result checksum mismatch: {target}")
            # Exclusive creation also protects against a concurrent writer.
            target.hardlink_to(temporary)
            counts["restored"] += 1
        finally:
            temporary.unlink(missing_ok=True)
    return counts


def pack(root: Path) -> dict:
    names = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    paths = sorted(name for name in names if name and (
        Path(name).suffix == ".sqlite" or (
            Path(name).suffix in {".csv", ".json", ".jsonl"}
            and (root / name).stat().st_size > 8 * 1024**2
        )
    ))
    output = root / ARCHIVES
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Existing archive manifest: {manifest_path}")
    entries = []
    for index, name in enumerate(paths, 1):
        source = root / name
        before = source.stat()
        sha = digest(source)
        archive = output / f"{sha}.gz"
        if not archive.exists():
            with tempfile.NamedTemporaryFile(dir=output, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                with source.open("rb") as src, temporary.open("wb") as raw:
                    if compressor := shutil.which("pigz"):
                        subprocess.run([compressor, "-1", "-n", "-p", "2", "-c"],
                                       stdin=src, stdout=raw, check=True)
                    else:
                        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=1, mtime=0) as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest(source) != sha:
            raise RuntimeError(f"Source changed during archival: {name}")
        parts = []
        if archive.stat().st_size > 48 * 1024**2:
            with archive.open("rb") as stream:
                part_index = 0
                while block := stream.read(48 * 1024**2):
                    part_path = output / f"{sha}.gz.part{part_index:03d}"
                    if not part_path.exists():
                        part_path.write_bytes(block)
                    parts.append({"path": part_path.relative_to(root).as_posix(),
                                  "bytes": len(block), "sha256": hashlib.sha256(block).hexdigest()})
                    part_index += 1
        else:
            parts.append({"path": archive.relative_to(root).as_posix(),
                          "bytes": archive.stat().st_size, "sha256": digest(archive)})
        entries.append({"path": name, "bytes": before.st_size, "sha256": sha, "parts": parts})
        print(f"{index}/{len(paths)} {name}", flush=True)
    manifest = {"schema": "otw2.result_archives.v1", "compression": "gzip",
                "original_files_retained_locally": True, "files": entries}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with (root / ".gitignore").open("a") as stream:
        stream.write("\n# Raw results preserved in artifacts/result_archives/manifest.json\n")
        for entry in entries:
            stream.write("/" + entry["path"] + "\n")
    kept = {part["path"] for e in entries for part in e["parts"]}
    # Whole large gzip streams are temporary; Git receives only <=48 MiB parts.
    for path in output.glob("*.gz"):
        if path.relative_to(root).as_posix() not in kept:
            path.unlink()
    for path in output.glob("tmp*"):
        path.unlink()
    return {"files": len(entries), "original_bytes": sum(e["bytes"] for e in entries),
            "unique_archive_bytes": sum((root / name).stat().st_size for name in kept)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["pack", "restore", "verify"])
    args = parser.parse_args()
    if args.action == "pack":
        result = pack(ROOT)
    else:
        manifest = json.loads((ROOT / ARCHIVES / "manifest.json").read_text())
        result = restore(ROOT, manifest, verify_only=args.action == "verify")
    print(json.dumps(result, indent=2))
    if result.get("missing", 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
