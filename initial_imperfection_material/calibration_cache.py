"""Immutable v2 calibration files, process exclusion and typed failure records."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import AnalysisConfig, canonical_json, file_sha256, fingerprint


CACHE_SCHEMA = "otw2.equivalent_imperfection_library.v2"
LEGACY_SCHEMA = "otw2.equivalent_imperfection_library.v1"


class CalibrationCacheError(RuntimeError):
    pass


class CacheCorruptionError(CalibrationCacheError):
    pass


class CacheIdentityMismatch(CalibrationCacheError):
    pass


class CacheWriteConflict(CalibrationCacheError):
    pass


class LegacyCacheRequiresOptIn(CalibrationCacheError):
    pass


class ReferenceNonconvergence(RuntimeError):
    """Only this failure permits an explicitly requested exploratory fallback."""

    def __init__(self, result: Any, message: str | None = None) -> None:
        self.result = result
        super().__init__(message or (
            f"reference completed {result.completed_steps}/{result.requested_steps} steps; "
            f"actual endpoint={result.actual_end_shortening} m"
        ))

    def as_record(self) -> dict[str, Any]:
        return {
            "method": "reference", "converged": False,
            "completed_steps": self.result.completed_steps,
            "requested_steps": self.result.requested_steps,
            "actual_end_shortening": self.result.actual_end_shortening,
            "requested_end_shortening": self.result.requested_end_shortening,
            "runtime_seconds": self.result.runtime_seconds,
            "fallback_reason": str(self),
        }


def publish_json_once(path: str | Path, payload: Any) -> None:
    """Publish a complete JSON file atomically without replacing an existing file.

    The temporary file and hard link are on the same filesystem. os.link is the
    no-overwrite publication primitive; unlike os.replace it cannot clobber a
    concurrent writer's result. Only our own temporary file is cleaned up.
    """

    destination = Path(path)
    serialized = canonical_json(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=f".{destination.name}.", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(serialized + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise CacheWriteConflict(f"refusing to overwrite {destination}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CalibrationCache:
    def __init__(self, path: str | Path, *, allow_legacy: bool = False) -> None:
        self.path = Path(path)
        self.allow_legacy = allow_legacy

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Fail promptly on contention; never guess that another lock is stale."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CacheWriteConflict(f"cache is locked: {lock_path}") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "cache": str(self.path)}))
                stream.flush()
                os.fsync(stream.fileno())
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def read(self, config: AnalysisConfig) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"),
                              parse_constant=lambda value: (_ for _ in ()).throw(
                                  ValueError(f"nonfinite JSON value: {value}")))
        except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
            raise CacheCorruptionError(f"invalid JSON cache: {self.path}") from exc
        if not isinstance(data, dict):
            raise CacheCorruptionError("cache root must be an object")
        if data.get("format") == LEGACY_SCHEMA:
            if not self.allow_legacy:
                raise LegacyCacheRequiresOptIn(
                    f"{self.path} is legacy v1; explicitly allow read-only legacy use, "
                    "or select a new v2 output path"
                )
            if not isinstance(data.get("groups"), dict) or not data["groups"]:
                raise CacheCorruptionError("legacy cache has no groups")
            return {**data, "legacy": True, "validation_status": "legacy_unknown",
                    "file_sha256": file_sha256(self.path)}
        if data.get("format") != CACHE_SCHEMA:
            raise CacheCorruptionError("unsupported or missing cache schema")
        if data.get("status") != "complete" or not isinstance(data.get("groups"), dict):
            raise CacheCorruptionError("partial cache cannot be used as a completed library")
        stored_config = data.get("config")
        if not isinstance(stored_config, dict) or fingerprint(stored_config) != data.get("config_fingerprint"):
            raise CacheCorruptionError("cache configuration fingerprint is corrupt")
        if data["config_fingerprint"] != config.fingerprint:
            raise CacheIdentityMismatch(
                f"configuration changed; preserve {self.path} and choose a new cache path"
            )
        if fingerprint(data["groups"]) != data.get("groups_fingerprint"):
            raise CacheCorruptionError("cache group payload fingerprint is corrupt")
        return {**data, "legacy": False, "file_sha256": file_sha256(self.path)}

    def write(self, config: AnalysisConfig, groups: dict[str, Any]) -> None:
        publish_json_once(self.path, {
            "format": CACHE_SCHEMA, "status": "complete", "config": config.to_dict(),
            "config_fingerprint": config.fingerprint, "groups_fingerprint": fingerprint(groups),
            "validation_status": "unvalidated", "groups": groups,
        })
