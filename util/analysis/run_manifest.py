"""Atomic run status and reproducibility metadata for independent analysis jobs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .result_quality import ResultQuality


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _environment() -> dict[str, str | None]:
    try:
        engine = importlib.metadata.version("openseespy")
    except importlib.metadata.PackageNotFoundError:
        engine = None
    return {"python": platform.python_version(), "platform": platform.platform(), "openseespy": engine}


def _git_info(directory: Path) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(directory), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(directory), "status", "--porcelain", "--untracked-files=normal"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        return {"commit": commit, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


class RunManifest:
    """A context manager that records running/completed/nonconverged/failed state.

    The manifest is metadata, not a saved OpenSees domain. A sibling exclusive
    lock prevents two writers from concurrently using the same result directory.
    Exceptions propagate after the failure state has been saved.
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        parameters: dict[str, Any],
        input_files: Iterable[str | Path] = (),
        seed: int | None = None,
        expected_steps: int | None = None,
        project_root: str | Path | None = None,
        quality: ResultQuality | None = None,
    ) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.path = self.output_dir / "run_manifest.json"
        self.lock_path = self.output_dir / ".run.lock"
        self._owns_lock = False
        self.input_files = tuple(Path(path) for path in input_files)
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        if quality is not None and not isinstance(quality, ResultQuality):
            raise TypeError("quality 必须为 ResultQuality 或 None。")
        self.quality = quality if quality is not None else ResultQuality()
        self._quality_coverage_from_steps = quality is None
        # Validate serializability before acquiring a lock or changing a file.
        json.dumps(parameters, allow_nan=False)
        if expected_steps is not None and (
            isinstance(expected_steps, bool) or not isinstance(expected_steps, int) or expected_steps < 0
        ):
            raise ValueError("expected_steps 必须为非负整数。")
        self.payload: dict[str, Any] = {
            "schema_version": 1, "run_id": uuid.uuid4().hex, "parameters": parameters,
            "seed": seed, "expected_steps": expected_steps, "completed_steps": 0,
            "artifacts": {}, "metrics": {},
        }

    def _write(self) -> None:
        # Numerical status is authoritative only for execution. It never grants
        # physical validation, domain acceptance, or a physical failure label.
        self.quality.set_execution(
            self.payload.get("status", "not_started"),
            failure_reason=self.payload.get("error", {}).get("message"),
        )
        if self._quality_coverage_from_steps:
            self.quality.set_coverage(self.payload["expected_steps"], self.payload["completed_steps"], unit="steps")
        quality = self.quality.to_dict()
        self.payload["quality"] = quality
        for key in ("execution_status", "validation_status", "domain_status", "validation_scope",
                    "quality_flags", "limit_state_status", "eligible_for_fragility"):
            self.payload[key] = quality[key]
        text = json.dumps(self.payload, ensure_ascii=False, indent=2, allow_nan=False)
        descriptor, filename = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=self.output_dir)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(text + "\n")
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def __enter__(self) -> "RunManifest":
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise RuntimeError(f"输出目录已有运行锁: {self.lock_path}") from error
        self._owns_lock = True
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(f"pid={os.getpid()} run_id={self.payload['run_id']}\n")
            self.payload.update(status="running", started_at=_now(), pid=os.getpid(),
                                git=_git_info(self.project_root), environment=_environment(), inputs=[])
            source_files = (*self.input_files, *sorted(Path(__file__).parent.glob("*.py")))
            for path in dict.fromkeys(source_files):
                self.payload["inputs"].append(file_fingerprint(path))
            self._write()
        except BaseException as error:
            try:
                self.payload.update(status="failed", finished_at=_now(),
                                    error={"type": type(error).__name__, "message": str(error)})
                self._write()
            finally:
                self.lock_path.unlink(missing_ok=True)
                self._owns_lock = False
            raise
        return self

    def update(self, *, completed_steps: int | None = None, expected_steps: int | None = None, **metrics: Any) -> None:
        if not self._owns_lock or self.payload.get("status") != "running":
            raise RuntimeError("只能更新正在运行的任务。")
        json.dumps(metrics, allow_nan=False)
        if expected_steps is not None:
            if isinstance(expected_steps, bool) or not isinstance(expected_steps, int) or expected_steps < self.payload["completed_steps"]:
                raise ValueError("expected_steps 必须为不小于已完成步数的整数。")
            self.payload["expected_steps"] = expected_steps
        if completed_steps is not None:
            if isinstance(completed_steps, bool) or not isinstance(completed_steps, int) or completed_steps < self.payload["completed_steps"]:
                raise ValueError("completed_steps 必须为非递减整数。")
            self.payload["completed_steps"] = completed_steps
        self.payload["metrics"].update(metrics)
        self._write()

    def add_artifact(self, name: str, path: str | Path) -> None:
        if not self._owns_lock or self.payload.get("status") != "running":
            raise RuntimeError("只能向正在运行的任务登记文件。")
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        self.payload["artifacts"][name] = str(resolved)
        self._write()

    def set_quality(self, quality: ResultQuality) -> None:
        """Persist an explicit assessment without changing legacy run status.

        Caller-supplied quality owns its coverage (targets, time points, etc.).
        The owning workflow must freeze and satisfy that coverage separately
        from the manifest's count of accepted analysis steps.
        """
        if not self._owns_lock or self.payload.get("status") != "running":
            raise RuntimeError("只能向正在运行的任务登记质量评估。")
        if not isinstance(quality, ResultQuality):
            raise TypeError("quality 必须为 ResultQuality。")
        quality.to_dict()  # Validate serializability before replacing state.
        self.quality = quality
        self._quality_coverage_from_steps = False
        self._write()

    def finish(self, *, converged: bool = True, **metrics: Any) -> None:
        if not self._owns_lock or self.payload.get("status") != "running":
            raise RuntimeError("任务未运行或已经结束。")
        json.dumps(metrics, allow_nan=False)
        expected = self.payload["expected_steps"]
        covered = expected is None or self.payload["completed_steps"] >= expected
        self.payload["status"] = "completed" if converged and covered else "nonconverged"
        self.payload["metrics"].update(metrics)
        self.payload["finished_at"] = _now()
        self._write()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if exc is not None:
                self.payload.update(
                    status="interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed",
                    error={"type": type(exc).__name__, "message": str(exc)}, finished_at=_now(),
                )
                self._write()
            elif self.payload.get("status") == "running":
                self.finish()
        finally:
            if self._owns_lock:
                self.lock_path.unlink(missing_ok=True)
                self._owns_lock = False
