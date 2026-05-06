from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

import openseespy.opensees as ops
from model import OpenSeesModel

STATIC_DIR = PROJECT_ROOT / "fluctuate_wind_simulate" / "static"
CONFIG_DIR = PROJECT_ROOT / "fluctuate_wind_simulate" / ".config"
WIND_PRESS_ROOT = STATIC_DIR / "wind_press_generate"
RECORD_ROOT = STATIC_DIR / ".opensees.output"
WIND_NODE_CONFIG = CONFIG_DIR / "node_to_add_wind_press.json"
DRIFT_NODE_CONFIG = CONFIG_DIR / "node_to_record_floor_disp.json"
S2K_PATH = PROJECT_ROOT / "Source" / "Z30103A6.s2k"


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
    t_path = sample_dir / "t.csv"
    with t_path.open("r", encoding="utf-8") as file:
        times = [float(item.strip()) for item in file if item.strip()]
    if len(times) < 2:
        raise ValueError(f"时间步数不足: {t_path}")
    dt = times[1] - times[0]
    nsteps = len(times) - 1
    return dt, nsteps


def load_node_config(config_path: Path = WIND_NODE_CONFIG) -> dict[str, list[int]]:
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    return {floor: [int(node) for node in nodes] for floor, nodes in config.items()}


def build_base_model(s2k_path: Path = S2K_PATH) -> OpenSeesModel:
    """Build the base OpenSees model once in the current process."""
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
) -> tuple[list[int], list[int]]:
    floor_names = sorted(node_config.keys(), key=get_floor_index)
    ts_tags: list[int] = []
    pattern_tags: list[int] = []

    for floor_name in floor_names:
        node_list = node_config[floor_name]
        floor_file = sample_dir / f"{floor_name}_wind_press.csv"
        if not floor_file.exists():
            raise FileNotFoundError(f"缺少楼层风压文件: {floor_file}")
        if len(node_list) == 0:
            raise ValueError(f"{floor_name} 没有可施加风荷载的节点。")

        ts_tag, pattern_tag = force_control.get_next_tag_pair(
            time_series_name=f"{sample_prefix}_{floor_name}_ts",
            pattern_name=f"{sample_prefix}_{floor_name}_pattern",
        )
        node_factor = 1.0 / len(node_list)

        ops.timeSeries("Path", ts_tag, "-dt", dt, "-filePath", floor_file.as_posix())
        ops.pattern("Plain", pattern_tag, ts_tag)
        for node_tag in node_list:
            ops.load(int(node_tag), 0.0, node_factor, 0.0, 0.0, 0.0, 0.0)

        ts_tags.append(ts_tag)
        pattern_tags.append(pattern_tag)

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
) -> dict[str, Any]:
    from util import CorrectedStoryDriftTracker, ForceControl

    sample_label = f"{speed_name}/{sample_name}"
    pid = os.getpid()
    ops.reset()
    ops.setTime(0.0)

    dt, nsteps = read_time_info(sample_dir)
    progress_markers = build_progress_markers(nsteps)
    force_control = ForceControl()
    sample_prefix = f"{speed_name}_{sample_name}"
    ts_tags, pattern_tags = apply_wind_load_for_sample(
        node_config=node_config,
        sample_dir=sample_dir,
        force_control=force_control,
        sample_prefix=sample_prefix,
        dt=dt,
    )

    ops.wipeAnalysis()
    sample_output_dir = RECORD_ROOT / speed_name / sample_name
    sample_output_dir.mkdir(parents=True, exist_ok=True)
    progress_log = sample_output_dir / "progress.log"
    progress_log.write_text("", encoding="utf-8")
    sample_start = perf_counter()
    log_progress(progress_log, f"start analysis: {sample_label}, sample_id={sample_id}, pid={pid}")
    log_progress(progress_log, f"time info: dt={dt}, nsteps={nsteps}")

    ops.recorder("Node", "-file", str(sample_output_dir / "Node_accel.out"), "-time", "-node", 370, "-dof", 2, "accel")
    ops.recorder("Node", "-file", str(sample_output_dir / "Node_velocity.out"), "-time", "-node", 370, "-dof", 2, "vel")
    ops.recorder("Node", "-file", str(sample_output_dir / "Node_displacement.out"), "-time", "-node", 370, "-dof", 2, "disp")
    ops.recorder("Element", "-file", str(sample_output_dir / "Element_all_section_1.out"), "-time", "-ele", *ops.getEleTags(), "section", 1, "fiber", -0.05, 1, "stress")

    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 0.001, 40, 2)
    ops.algorithm("KrylovNewton")
    ops.integrator("Newmark", 0.5, 0.25)
    ops.analysis("Transient")

    tracker = CorrectedStoryDriftTracker(DRIFT_NODE_CONFIG)
    story_labels = tracker.get_story_labels()
    drift_csv = sample_output_dir / "drift.csv"
    not_correct_drift_csv = sample_output_dir / "not_correct_drift.csv"

    try:
        with drift_csv.open("w", encoding="utf-8") as drift_file, not_correct_drift_csv.open("w", encoding="utf-8") as not_corr_file:
            drift_file.write("step," + ",".join(story_labels) + "\n")
            not_corr_file.write("step," + ",".join(story_labels) + "\n")

            for step in range(1000):
                step_start = perf_counter()
                ok = ops.analyze(1, dt)
                if ok != 0:
                    raise RuntimeError(f"transient analyze failed at {speed_name}/{sample_name}, step={step}")

                drift_now = tracker.capture_step()
                not_corr_now = tracker.get_not_corrected_history()[-1]
                drift_file.write(f"{step}," + ",".join(str(value) for value in drift_now) + "\n")
                not_corr_file.write(f"{step}," + ",".join(str(value) for value in not_corr_now) + "\n")
                if should_log_step(step, nsteps, interval=100):
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
    finally:
        ops.remove("recorders")
        remove_wind_load(ts_tags, pattern_tags)

    total_cost = perf_counter() - sample_start
    log_progress(progress_log, f"finish analysis: {sample_label}, total_cost_sec={total_cost:.6f}")
    return {
        "sample_id": sample_id,
        "speed_name": speed_name,
        "sample_name": sample_name,
        "dt": dt,
        "nsteps": nsteps,
        "status": "ok",
    }


def run_sample_batch(batch_samples: list[tuple[int, str, str, Path]]) -> list[dict[str, Any]]:
    build_base_model()
    node_config = load_node_config()
    results: list[dict[str, Any]] = []
    for sample_id, speed_name, sample_name, sample_dir in batch_samples:
        results.append(
            run_one_sample(
                sample_id=sample_id,
                speed_name=speed_name,
                sample_name=sample_name,
                sample_dir=sample_dir,
                node_config=node_config,
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
