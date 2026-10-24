from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

import openseespy.opensees as ops
from model import OpenSeesModel
from util.analysis import AdaptiveStepper, Algorithm, RunManifest, TimeGrid, validate_wind_sample
from util.analysis.run_manifest import file_fingerprint

STATIC_DIR = PROJECT_ROOT / "fluctuate_wind_simulate" / "static"
CONFIG_DIR = PROJECT_ROOT / "fluctuate_wind_simulate" / ".config"
WIND_PRESS_ROOT = STATIC_DIR / "wind_press_generate"
RECORD_ROOT = STATIC_DIR / ".opensees.output"
WIND_NODE_CONFIG = CONFIG_DIR / "node_to_add_wind_press.json"
DRIFT_NODE_CONFIG = CONFIG_DIR / "node_to_record_floor_disp.json"
S2K_PATH = PROJECT_ROOT / "Source" / "Z30103A6.s2k"
_DOMAIN_LOCK = threading.Lock()


@contextmanager
def _own_domain():
    """One OpenSees domain per process; threaded sample execution is rejected."""
    if not _DOMAIN_LOCK.acquire(blocking=False):
        raise RuntimeError("Concurrent samples cannot share one OpenSees domain; use separate processes")
    try:
        yield
    finally:
        _DOMAIN_LOCK.release()


def _callable_name(callback):
    return f"{callback.__module__}.{getattr(callback, '__qualname__', type(callback).__qualname__)}" if callback else None


def get_floor_index(floor_name: str) -> int:
    match = re.fullmatch(r"floor(\d+)", floor_name)
    if not match:
        raise ValueError(f"非法楼层名: {floor_name}")
    return int(match.group(1))


def get_wind_samples(wind_press_root: Path = WIND_PRESS_ROOT) -> list[tuple[str, str, Path]]:
    samples: list[tuple[str, str, Path]] = []
    for speed_dir in sorted(wind_press_root.iterdir()):
        if not speed_dir.is_dir():
            continue
        for sample_dir in sorted(speed_dir.iterdir()):
            if not sample_dir.is_dir():
                continue
            if (sample_dir / "t.csv").exists():
                samples.append((speed_dir.name, sample_dir.name, sample_dir))
    return samples


def read_time_info(sample_dir: Path) -> tuple[float, int]:
    grid = TimeGrid.from_csv(sample_dir / "t.csv")
    return grid.dt, grid.nsteps


def load_node_config(config_path: Path = WIND_NODE_CONFIG) -> dict[str, list[int]]:
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    return {floor: [int(node) for node in nodes] for floor, nodes in config.items()}


def build_base_model(s2k_path: Path = S2K_PATH) -> OpenSeesModel:
    """Build the ordinary model for one independent sample, using legacy physics."""
    ops.wipe()
    model = OpenSeesModel(str(s2k_path))
    model.model_tower()
    return model


def build_progress_markers(nsteps: int, segments: int = 10) -> dict[int, int]:
    if nsteps <= 0:
        return {}
    markers: dict[int, int] = {}
    for percent in range(0, 101, max(1, 100 // segments)):
        step_index = min(nsteps - 1, max(0, round((nsteps - 1) * percent / 100)))
        markers[step_index] = percent
    markers[nsteps - 1] = 100
    return markers


def should_log_step(step_index: int, nsteps: int, interval: int = 100) -> bool:
    if nsteps <= 0:
        return False
    if step_index == 0 or step_index == nsteps - 1:
        return True
    return (step_index + 1) % interval == 0


def log_progress(log_path: Path, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


# 施加一个sample的风荷载，返回施加的时间序列和荷载模式的标签，以便后续移除
def apply_wind_load_for_sample(
    node_config: dict[str, list[int]],
    sample_dir: Path,
    force_control,
    sample_prefix: str,
    dt: float,
    load_dof: int = 2,
    start_time: float = 0.0,
) -> tuple[list[int], list[int]]:
    floor_names = sorted(node_config.keys(), key=get_floor_index)
    ts_tags: list[int] = []
    pattern_tags: list[int] = []

    try:
        for floor_name in floor_names:
            node_list = node_config[floor_name]
            floor_file = sample_dir / f"{floor_name}_wind_press.csv"
            if not floor_file.exists():
                raise FileNotFoundError(f"缺少楼层风压文件: {floor_file}")
            if len(node_list) == 0:
                raise ValueError(f"{floor_name} 没有可施加风荷载的节点。")
            counts = {int(node): len(ops.nodeDisp(int(node))) for node in node_list}
            if any(not 1 <= load_dof <= count for count in counts.values()):
                raise ValueError(f"load DOF {load_dof} not available at every node in {floor_name}")
            ts_tag, pattern_tag = force_control.get_next_tag_pair(
                time_series_name=f"{sample_prefix}_{floor_name}_ts",
                pattern_name=f"{sample_prefix}_{floor_name}_pattern",
            )
            node_factor = 1.0 / len(node_list)
            # Analysis stops at the input endpoint. Preserve its specified last
            # value when floating-point indexing falls on/outside that sample;
            # otherwise changing only the domain time offset can change force.
            ops.timeSeries("Path", ts_tag, "-dt", dt, "-filePath", floor_file.as_posix(),
                           "-startTime", start_time, "-useLast")
            ts_tags.append(ts_tag)
            ops.pattern("Plain", pattern_tag, ts_tag)
            pattern_tags.append(pattern_tag)
            for node_tag, count in counts.items():
                vector = [0.0] * count
                vector[load_dof - 1] = node_factor
                ops.load(node_tag, *vector)
    except BaseException:
        remove_wind_load(ts_tags, pattern_tags)
        raise

    return ts_tags, pattern_tags


def remove_wind_load(ts_tags: list[int], pattern_tags: list[int]) -> None:
    for pattern_tag in pattern_tags:
        ops.remove("loadPattern", int(pattern_tag))
    for ts_tag in ts_tags:
        ops.remove("timeSeries", int(ts_tag))

def run_one_sample(
    sample_id: int,
    speed_name: str,
    sample_name: str,
    sample_dir: Path,
    node_config: dict[str, list[int]],
    model: OpenSeesModel | None = None,
    *,
    model_factory: Callable[[], Any] | None = None,
    initialize_model: Callable[[Any], Mapping[str, Any] | None] | None = None,
    model_declaration: Mapping[str, Any] | None = None,
    control_node: int = 370,
    control_dof: int = 2,
    wind_load_dof: int = 2,
    output_root: Path | None = None,
    drift_node_config: Path | None = None,
    drift_enabled: bool = True,
    legacy_fiber_recording: bool = False,
) -> dict[str, Any]:
    """Run one sample in a fresh domain, or use an explicitly supplied domain.

    A factory is called after wipe for every sample. An external legacy model
    is caller-owned and retains its committed gravity/material state; reset is
    never assumed to reproduce that state. The initialization callback owns
    gravity/loadConst/damping and returns their provenance declarations.
    """
    if model is not None and model_factory is not None:
        raise ValueError("supply model or model_factory, not both")
    for name, value in (("control_node", control_node), ("control_dof", control_dof), ("wind_load_dof", wind_load_dof)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    declaration = dict(model_declaration or {})
    json.dumps(declaration, allow_nan=False)
    root = Path(output_root) if output_root is not None else RECORD_ROOT
    drift_config = Path(drift_node_config) if drift_node_config is not None else DRIFT_NODE_CONFIG
    sample_output_dir = root / speed_name / sample_name
    if (sample_output_dir / "run_manifest.json").exists():
        raise FileExistsError(f"sample output already exists; choose a new output_root: {sample_output_dir}")
    inputs = [sample_dir / "t.csv", Path(__file__)]
    if drift_enabled:
        inputs.append(drift_config)
    source = getattr(model, "s2k_path", None) if model is not None else S2K_PATH if model_factory is None else None
    if source is not None:
        inputs.append(Path(source))
    with _own_domain(), RunManifest(
        sample_output_dir,
        parameters={"analysis": "wind_transient", "sample_id": sample_id,
                    "speed_name": speed_name, "sample_name": sample_name,
                    "node_config": node_config, "model_factory": _callable_name(model_factory),
                    "initialize_model": _callable_name(initialize_model),
                    "model_declaration": declaration, "control_node": control_node,
                    "control_dof": control_dof, "wind_load_dof": wind_load_dof,
                    "drift_enabled": drift_enabled, "legacy_fiber_recording": legacy_fiber_recording},
        input_files=inputs + [sample_dir / f"{floor}_wind_press.csv" for floor in node_config],
    ) as run:
        preflight = validate_wind_sample(sample_dir, node_config)
        run.update(expected_steps=preflight["nsteps"], preflight=preflight)
        with ExitStack() as cleanup:
            result = _run_one_sample(sample_id, speed_name, sample_name, sample_dir, node_config,
                                     model=model, model_factory=model_factory, initialize_model=initialize_model,
                                     model_declaration=declaration, control_node=control_node,
                                     control_dof=control_dof, wind_load_dof=wind_load_dof,
                                     sample_output_dir=sample_output_dir, drift_config=drift_config,
                                     drift_enabled=drift_enabled, legacy_fiber_recording=legacy_fiber_recording,
                                     run=run, cleanup=cleanup)
        run.add_artifact("internal_forces", result["internal_force_database"])
        run.add_artifact("drift", sample_output_dir / "drift.csv")
        run.add_artifact("section_responses", sample_output_dir / "section_responses.jsonl")
        run.finish()
        return result


def _run_one_sample(
    sample_id: int,
    speed_name: str,
    sample_name: str,
    sample_dir: Path,
    node_config: dict[str, list[int]],
    *,
    model: OpenSeesModel | None,
    model_factory: Callable[[], Any] | None,
    initialize_model: Callable[[Any], Mapping[str, Any] | None] | None,
    model_declaration: Mapping[str, Any],
    control_node: int,
    control_dof: int,
    wind_load_dof: int,
    sample_output_dir: Path,
    drift_config: Path,
    drift_enabled: bool,
    legacy_fiber_recording: bool,
    run: RunManifest,
    cleanup: ExitStack,
) -> dict[str, Any]:
    from util import CorrectedStoryDriftTracker, ForceControl, TowerInternalForceRecorder

    sample_label = f"{speed_name}/{sample_name}"
    pid = os.getpid()
    external_model = model is not None
    if not external_model:
        ops.wipe()
        model = (model_factory or build_base_model)()
    initialization = dict(initialize_model(model) or {}) if initialize_model is not None else {}
    if control_node not in ops.getNodeTags() or control_dof > len(ops.nodeDisp(control_node)):
        raise ValueError(f"control node/DOF does not exist: {control_node}/{control_dof}")
    validate_wind_sample(sample_dir, node_config, available_nodes=ops.getNodeTags())
    transient_start_time = float(ops.getTime())
    if not math.isfinite(transient_start_time):
        raise ValueError("nonfinite initialized domain time")
    family = model_declaration.get("model_family", "ordinary" if type(model) is OpenSeesModel else "unknown")
    equivalent = bool(getattr(model, "equivalent_materials", None)) or "equivalent" in str(family).lower()
    metadata = {"model_family": family, "model_class": f"{type(model).__module__}.{type(model).__qualname__}",
                "effective_factory": None if external_model else _callable_name(model_factory or build_base_model),
                "domain_source": "external_legacy_model" if external_model else "fresh_factory",
                "sample_isolation": "caller_managed_unknown" if external_model else "wipe_and_rebuild_per_sample",
                "initialization": initialization.get("initialization", "callback_completed" if initialize_model else "unknown"),
                "gravity": initialization.get("gravity", model_declaration.get("gravity", "unknown")),
                "damping": initialization.get("damping", model_declaration.get("damping", "unknown")),
                "mass": initialization.get("mass", model_declaration.get("mass", "unknown")),
                "transient_start_time": transient_start_time,
                "time_semantics": "transient elapsed seconds = domain time - transient_start_time; preload time can be pseudo-time",
                "wind_series_endpoint_policy": "last_recorded_value; analysis never extends beyond requested input endpoint",
                "control_node": control_node, "control_dof": control_dof, "wind_load_dof": wind_load_dof,
                "control_coordinates": list(ops.nodeCoord(control_node)),
                "control_node_ndf": len(ops.nodeDisp(control_node)),
                "initial_control_displacement": float(ops.nodeDisp(control_node, control_dof)),
                "section_deformation_meaning": "equivalent_component_generalized_deformation_not_steel_fiber_strain" if equivalent
                                               else "section_generalized_deformation_not_a_fiber_strain",
                "drift_enabled": drift_enabled, "drift_translation_dof": 2, "drift_rotation_dof": 4,
                "physical_validation": "unvalidated"}
    if external_model:
        metadata["warning"] = "External model retains committed state; caller must independently establish sample isolation"
    if getattr(model, "s2k_path", None):
        metadata["model_source"] = file_fingerprint(model.s2k_path)
    run.update(model_adapter=metadata)

    dt, nsteps = read_time_info(sample_dir)
    progress_markers = build_progress_markers(nsteps)
    # Existing gravity patterns must survive and must not collide with wind tags.
    first_tag = max(1_000_000, max(ops.getPatterns(), default=0) + 1)
    force_control = ForceControl(start_time_series_tag=int(initialization.get("wind_time_series_start", first_tag)),
                                 start_pattern_tag=int(initialization.get("wind_pattern_start", first_tag)))
    sample_prefix = f"{speed_name}_{sample_name}"
    ts_tags, pattern_tags = apply_wind_load_for_sample(
        node_config=node_config,
        sample_dir=sample_dir,
        force_control=force_control,
        sample_prefix=sample_prefix,
        dt=dt,
        load_dof=wind_load_dof,
        start_time=transient_start_time,
    )
    cleanup.callback(remove_wind_load, ts_tags, pattern_tags)
    metadata.update(wind_time_series_tags=ts_tags, wind_pattern_tags=pattern_tags)
    run.update(model_adapter=metadata)

    ops.wipeAnalysis()
    sample_output_dir.mkdir(parents=True, exist_ok=True)
    progress_log = sample_output_dir / "progress.log"
    progress_log.write_text("", encoding="utf-8")
    sample_start = perf_counter()
    log_progress(progress_log, f"start analysis: {sample_label}, sample_id={sample_id}, pid={pid}")
    log_progress(progress_log, f"time info: dt={dt}, nsteps={nsteps}")

    cleanup.callback(ops.remove, "recorders")
    for name, response in (("Node_accel.out", "accel"), ("Node_velocity.out", "vel"), ("Node_displacement.out", "disp")):
        ops.recorder("Node", "-file", str(sample_output_dir / name), "-time", "-node", control_node, "-dof", control_dof, response)
    if legacy_fiber_recording:
        if equivalent or not getattr(model, "section_fiber_map", None):
            raise ValueError("legacy fixed fiber probe requires an explicitly ordinary Fiber model; Aggregator is unsupported")
        warnings.warn("Legacy fixed fiber coordinate is an unvalidated probe, not a section strain envelope", RuntimeWarning)
        metadata["legacy_fiber_warning"] = "fixed (-0.05,1) probe; not a fiber envelope or an equivalent strain"
        ops.recorder("Element", "-file", str(sample_output_dir / "Element_all_section_1.out"), "-time", "-ele", *ops.getEleTags(), "section", 1, "fiber", -0.05, 1, "stress")
        run.update(model_adapter=metadata)
    internal_force_recorder = TowerInternalForceRecorder(
        model,
        sample_output_dir / "tower_internal_forces.sqlite",
        overwrite=True,
        record_every=1,
        commit_every=10,
    )
    cleanup.callback(internal_force_recorder.close)

    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 0.001, 40, 2)
    ops.algorithm("KrylovNewton")
    ops.integrator("Newmark", 0.5, 0.25)
    ops.analysis("Transient")
    stepper = AdaptiveStepper(
        ops, progress=ops.getTime, transient=True, minimum_increment=dt / 16,
        algorithms=(Algorithm("KrylovNewton"), Algorithm("Newton"), Algorithm("NewtonLineSearch", (0.8,))),
        convergence_test=("NormDispIncr", 0.001, 40, 0),
        progress_tolerance=min(1e-9, dt * 1e-5),
    )

    tracker = CorrectedStoryDriftTracker(drift_config) if drift_enabled else None
    story_labels = tracker.get_story_labels() if tracker is not None else []
    drift_csv = sample_output_dir / "drift.csv"
    not_correct_drift_csv = sample_output_dir / "not_correct_drift.csv"

    try:
        sections = cleanup.enter_context((sample_output_dir / "section_responses.jsonl").open("w", encoding="utf-8"))
        section_capabilities = {}
        for tag in ops.getEleTags():
            force = list(ops.eleResponse(tag, "section", 1, "force") or ())
            deformation = list(ops.eleResponse(tag, "section", 1, "deformation") or ())
            section_capabilities[int(tag)] = bool(force and deformation)
        metadata["section_response_capabilities"] = {"available_elements": sum(section_capabilities.values()),
            "unsupported_elements": len(section_capabilities) - sum(section_capabilities.values()), "section_point": 1}
        run.update(model_adapter=metadata)
        def capture_sections(step):
            responses = []
            for tag, available in section_capabilities.items():
                if available:
                    force = [float(v) for v in ops.eleResponse(tag, "section", 1, "force")]
                    deformation = [float(v) for v in ops.eleResponse(tag, "section", 1, "deformation")]
                    if not force or not deformation or not all(math.isfinite(v) for v in (*force, *deformation)):
                        raise RuntimeError(f"section response disappeared/nonfinite at element {tag}")
                    responses.append({"element": tag, "section": 1, "status": "available",
                                      "generalized_force": force, "generalized_deformation": deformation})
            sections.write(json.dumps({"accepted_step":step,"time":float(ops.getTime()),
                                       "elapsed_time_s":float(ops.getTime())-transient_start_time,"committed":True,
                                       "deformation_meaning":metadata["section_deformation_meaning"],
                                       "unsupported_elements":[tag for tag,available in section_capabilities.items() if not available],
                                       "sections":responses},allow_nan=False)+"\n")
        capture_sections(0)
        internal_force_recorder.capture(step=0, time=ops.getTime())
        with drift_csv.open("w", encoding="utf-8") as drift_file, not_correct_drift_csv.open("w", encoding="utf-8") as not_corr_file:
            drift_file.write("step," + ",".join(story_labels) + "\n")
            not_corr_file.write("step," + ",".join(story_labels) + "\n")
            accepted_steps = 0

            def capture_substep(_result: Any) -> None:
                nonlocal accepted_steps
                drift_now = tracker.capture_step() if tracker is not None else []
                accepted_steps += 1
                internal_force_recorder.capture(step=accepted_steps, time=ops.getTime())
                capture_sections(accepted_steps)
                not_corr_now = tracker.get_not_corrected_history()[-1] if tracker is not None else []
                # Keep the historical CSV schema; the DB maps accepted step -> actual time.
                drift_file.write(f"{accepted_steps - 1}," + ",".join(str(value) for value in drift_now) + "\n")
                not_corr_file.write(f"{accepted_steps - 1}," + ",".join(str(value) for value in not_corr_now) + "\n")

            for step in range(nsteps):
                step_start = perf_counter()
                advancement = stepper.advance_to(transient_start_time + (step + 1) * dt, maximum_increment=dt, on_step=capture_substep)
                if not advancement.converged:
                    run.update(completed_steps=step, actual_time=ops.getTime(), solver=stepper.diagnostics())
                    raise RuntimeError(f"transient analyze failed at {speed_name}/{sample_name}, step={step}")
                if should_log_step(step, nsteps, interval=100):
                    run.update(completed_steps=step + 1, actual_time=ops.getTime(),
                               solver=stepper.diagnostics())
                    step_cost = perf_counter() - step_start
                    percent = progress_markers.get(step)
                    percent_text = f", progress={percent:>3}%" if percent is not None else ""
                    log_progress(
                        progress_log,
                        f"step={step + 1}/{nsteps}, model_time={ops.getTime():.6f}, "
                        f"step_cost_sec={step_cost:.6f}{percent_text}",
                    )
    except Exception as exc:
        log_progress(progress_log, f"analysis failed: {exc}")
        raise
    total_cost = perf_counter() - sample_start
    log_progress(progress_log, f"finish analysis: {sample_label}, total_cost_sec={total_cost:.6f}")
    run.update(completed_steps=nsteps, runtime_seconds=total_cost,
               actual_time=ops.getTime(), solver=stepper.diagnostics())
    return {
        "sample_id": sample_id,
        "speed_name": speed_name,
        "sample_name": sample_name,
        "dt": dt,
        "nsteps": nsteps,
        "internal_force_database": str(sample_output_dir / "tower_internal_forces.sqlite"),
        "status": "ok",
        "model_adapter": metadata,
    }


def run_sample_batch(batch_samples: list[tuple[int, str, str, Path]], *, model_factory=None,
                     initialize_model=None, node_config=None, **sample_options) -> list[dict[str, Any]]:
    node_config = load_node_config() if node_config is None else node_config
    results: list[dict[str, Any]] = []
    for sample_id, speed_name, sample_name, sample_dir in batch_samples:
        results.append(
            run_one_sample(
                sample_id=sample_id,
                speed_name=speed_name,
                sample_name=sample_name,
                sample_dir=sample_dir,
                node_config=node_config,
                model_factory=model_factory or build_base_model,
                initialize_model=initialize_model,
                **sample_options,
            )
        )
    return results


def enumerate_samples() -> list[tuple[int, str, str, Path]]:
    raw_samples = get_wind_samples()
    return [(index, speed_name, sample_name, sample_dir) for index, (speed_name, sample_name, sample_dir) in enumerate(raw_samples, start=1)]


def group_samples_by_speed(
    samples: list[tuple[int, str, str, Path]],
) -> list[list[tuple[int, str, str, Path]]]:
    grouped: dict[str, list[tuple[int, str, str, Path]]] = {}
    for sample in samples:
        speed_name = sample[1]
        grouped.setdefault(speed_name, []).append(sample)
    return [grouped[speed_name] for speed_name in sorted(grouped)]


def run_all_samples_serial() -> list[dict[str, Any]]:
    samples = enumerate_samples()
    return run_sample_batch(samples)


def run_all_samples_parallel(max_workers: int) -> list[dict[str, Any]]:
    samples = enumerate_samples()
    speed_batches = group_samples_by_speed(samples)
    if len(speed_batches) <= 1:
        return run_sample_batch(samples)

    results: list[dict[str, Any]] = []
    if max_workers <= 0:
        worker_count = len(speed_batches)
    else:
        worker_count = min(max_workers, len(speed_batches))
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(run_sample_batch, batch) for batch in speed_batches]
        for future in as_completed(futures):
            results.extend(future.result())
    return sorted(results, key=lambda item: item["sample_id"])
