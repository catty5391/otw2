"""Compare accepted cyclic histories by stage, direction and monotone progress.

Displacement is never globally sorted. Repeated progress represents an explicit
jump; ``jump_before`` marks an interval that must not be interpolated. No data
are extrapolated and no-common-coverage is a regular result, not an exception.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def _truth(value: Any) -> bool:
    return value is True or value == 1 or str(value).lower() in {"true", "1"}


def _groups(records: Iterable[Mapping[str, Any]], fields: tuple[str, ...], maximum_gap: float | None):
    groups: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
    excluded = 0
    previous_key = None
    for record in records:
        if (not _truth(record.get("accepted", True)) or not _truth(record.get("committed", True)) or
                record.get("state", "committed") != "committed"):
            excluded += 1
            continue
        stage, direction = str(record["stage_id"]), int(record["direction"])
        if direction not in (-1, 0, 1):
            raise ValueError("direction must be -1, 0 or +1")
        key = stage, direction
        if key != previous_key and key in groups:
            raise ValueError(f"stage {key} reappears non-contiguously; use a unique stage/cycle identifier")
        previous_key = key
        progress = float(record["stage_progress"])
        values = {field: float(record[field]) for field in fields}
        if not math.isfinite(progress) or not 0 <= progress <= 1:
            raise ValueError("stage_progress must be finite and lie in [0, 1]")
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("nonfinite accepted response")
        group = groups.setdefault(key, {"points": [], "segments": [], "jumps": []})
        point = {"progress": progress, **values}
        if group["points"]:
            previous = group["points"][-1]
            delta = progress - previous["progress"]
            if delta < 0:
                raise ValueError(f"stage progress reverses within {key}; do not sort cyclic displacement")
            jump = delta == 0 or _truth(record.get("jump_before", False))
            gap = maximum_gap is not None and delta > maximum_gap
            if jump or gap:
                group["jumps"].append({"progress_before": previous["progress"], "progress_after": progress,
                                       "reason": "sampling_gap" if gap and not jump else "jump",
                                       "before": previous, "after": point,
                                       "increments": {field: point[field] - previous[field] for field in fields}})
            else:
                group["segments"].append((previous, point))
        group["points"].append(point)
    return groups, excluded


def _value(segment, progress: float, field: str) -> float:
    left, right = segment
    fraction = (progress - left["progress"]) / (right["progress"] - left["progress"])
    return left[field] + fraction * (right[field] - left[field])


def compare_protocol_histories(
    reference: Iterable[Mapping[str, Any]],
    candidate: Iterable[Mapping[str, Any]],
    *,
    value_fields: Iterable[str] = ("base_shear",),
    maximum_progress_gap: float | None = None,
    protocol_stages: Iterable[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Exact progress-integrated RMSE on shared, non-jumping linear intervals.

    Input rows require ``stage_id``, signed loading ``direction`` and normalized
    ``stage_progress``. Include stage start rows (including gravity endpoint) to
    claim full coverage. Automatic force-jump detection is deliberately absent:
    a jump must come from an event detector or an explicit repeated-progress
    pair. The output always states that unmarked jumps remain a limitation.
    """
    fields = tuple(value_fields)
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("value_fields must be nonempty and unique")
    if maximum_progress_gap is not None and (not math.isfinite(maximum_progress_gap) or maximum_progress_gap <= 0):
        raise ValueError("maximum_progress_gap must be finite and positive")
    refs, ref_excluded = _groups(reference, fields, maximum_progress_gap)
    cands, cand_excluded = _groups(candidate, fields, maximum_progress_gap)
    stage_results = []
    common_total = 0.0
    squared_totals = {field: 0.0 for field in fields}
    reference_scale = {field: 0.0 for field in fields}
    if protocol_stages is None:
        keys = list(refs) + [key for key in cands if key not in refs]
    else:
        keys = [(str(stage), int(direction)) for stage, direction in protocol_stages]
        if not keys or len(set(keys)) != len(keys) or any(direction not in (-1, 0, 1) for _, direction in keys):
            raise ValueError("protocol_stages must contain unique stage/direction keys")
        if not (set(refs) | set(cands)) <= set(keys):
            raise ValueError("observed stage is outside the declared protocol")
    for key in keys:
        ref, cand = refs.get(key), cands.get(key)
        result: dict[str, Any] = {"stage_id": key[0], "direction": key[1],
                                  "status": "no_common_coverage", "common_progress": 0.0,
                                  "reference_jumps": ref["jumps"] if ref else [],
                                  "candidate_jumps": cand["jumps"] if cand else [], "metrics": {}}
        if ref is None or cand is None:
            result["reason"] = ("stage_missing_in_both" if ref is None and cand is None else
                                "stage_missing_in_candidate" if cand is None else "stage_missing_in_reference")
            stage_results.append(result)
            continue
        overlaps = []
        for r_segment in ref["segments"]:
            for c_segment in cand["segments"]:
                start = max(r_segment[0]["progress"], c_segment[0]["progress"])
                end = min(r_segment[1]["progress"], c_segment[1]["progress"])
                if start < end:
                    overlaps.append((start, end, r_segment, c_segment))
        length = math.fsum(end - start for start, end, _, _ in overlaps)
        result["common_progress"] = length
        result["common_intervals"] = [[start, end] for start, end, _, _ in overlaps]
        result["reference_sampled_span"] = ref["points"][-1]["progress"] - ref["points"][0]["progress"]
        result["candidate_sampled_span"] = cand["points"][-1]["progress"] - cand["points"][0]["progress"]
        result["full_stage_coverage_percent"] = length * 100
        if length > 0:
            result["status"] = "compared"
            for field in fields:
                terms, errors, scales = [], [], []
                for start, end, r_segment, c_segment in overlaps:
                    r0, r1 = _value(r_segment, start, field), _value(r_segment, end, field)
                    e0 = _value(c_segment, start, field) - r0
                    e1 = _value(c_segment, end, field) - r1
                    terms.append((end - start) * (e0 * e0 + e0 * e1 + e1 * e1) / 3)
                    errors.extend((abs(e0), abs(e1)))
                    scales.extend((abs(r0), abs(r1)))
                squared, scale = math.fsum(terms), max(scales)
                rmse = math.sqrt(squared / length)
                result["metrics"][field] = {"rmse": rmse, "maximum_absolute_error": max(errors),
                                             "reference_scale": scale,
                                             "nrmse_percent": rmse / scale * 100 if scale else None}
                squared_totals[field] += squared
                reference_scale[field] = max(reference_scale[field], scale)
            common_total += length
        elif key[1] == 0:
            # Stationary stages have no path length. Compare matching points only.
            matches = [(r, c) for r in ref["points"] for c in cand["points"]
                       if r["progress"] == c["progress"]]
            if matches:
                result["status"] = "point_only"
                result["metrics"] = {field: {"maximum_absolute_error": max(abs(c[field] - r[field])
                                                                                for r, c in matches)}
                                      for field in fields}
            else:
                result["reason"] = "stationary_stage_has_no_matching_point"
        else:
            result["reason"] = "no_positive_shared_nonjumping_interval"
        stage_results.append(result)
    aggregate = {}
    for field in fields:
        rmse = math.sqrt(squared_totals[field] / common_total) if common_total else None
        aggregate[field] = {"rmse": rmse,
                            "nrmse_percent": 100 * rmse / reference_scale[field]
                            if rmse is not None and reference_scale[field] else None}
    return {"schema": "otw2.protocol_comparison.v1",
            "status": "compared" if common_total else "no_common_coverage",
            "reason": None if common_total else "no_positive_shared_nonjumping_protocol_interval",
            "common_progress": common_total,
            "reference_stage_count": len(refs), "candidate_stage_count": len(cands),
            "declared_protocol_stage_count": len(keys) if protocol_stages is not None else None,
            "coverage_basis": "declared_protocol_stages" if protocol_stages is not None else "observed_stages",
            "reference_protocol_coverage_percent": 100 * common_total / (len(keys) if protocol_stages is not None else len(refs)) if refs else 0.0,
            "candidate_protocol_coverage_percent": 100 * common_total / (len(keys) if protocol_stages is not None else len(cands)) if cands else 0.0,
            "excluded_reference_trial_rows": ref_excluded, "excluded_candidate_trial_rows": cand_excluded,
            "unmarked_jump_detection": "not_performed_use_event_flags_or_maximum_progress_gap",
            "metrics": aggregate, "stages": stage_results}


def normalize_legacy_diagnostic_history(
    records: Iterable[Mapping[str, Any]], target_displacements: Iterable[float]
) -> list[dict[str, Any]]:
    """Adapt old diagnose_tower_convergence CSV with explicit protocol targets.

    Targets are displacement in metres, supplied by the caller from the source
    run's frozen protocol. No tower height, material range or case path is
    hardcoded. Initial stage 0 is required; each new stage gains its exact
    preceding committed endpoint as progress 0. No missing stage is invented.
    This adapter cannot recover unrecorded local jump flags or fiber states.
    """
    source, targets = tuple(records), tuple(float(value) for value in target_displacements)
    if not source or int(source[0]["stage"]) != 0:
        raise ValueError("legacy diagnostic history must start with its committed stage 0")
    if not targets or not all(math.isfinite(value) for value in targets):
        raise ValueError("supply the actual finite target displacements explicitly")
    previous = {"u_m": float(source[0]["u_m"]), "base_shear": float(source[0]["base_shear_N"])}
    normalized = []
    current_stage = 0
    start = target = 0.0
    direction = 0
    for record in source[1:]:
        stage = int(record["stage"])
        if stage != current_stage:
            if stage != current_stage + 1 or not 1 <= stage <= len(targets):
                raise ValueError("legacy diagnostic stage order is missing, repeated or outside protocol")
            start, target = previous["u_m"], targets[stage - 1]
            direction = 1 if target > start else -1 if target < start else 0
            normalized.append({"stage_id": str(stage), "direction": direction, "stage_progress": 0.,
                               "base_shear": previous["base_shear"], "u_m": start})
            current_stage = stage
        displacement, force = float(record["u_m"]), float(record["base_shear_N"])
        progress = (displacement - start) / (target - start) if target != start else 0.
        if -1e-12 <= progress <= 1 + 1e-12:
            progress = min(1., max(0., progress))
        normalized.append({"stage_id": str(stage), "direction": direction, "stage_progress": progress,
                           "base_shear": force, "u_m": displacement})
        previous = {"u_m": displacement, "base_shear": force}
    return normalized


def normalize_tower_cyclic_history(
    records: Iterable[Mapping[str, Any]], target_displacements: Iterable[float]
) -> list[dict[str, Any]]:
    """Adapt committed full_tower_cyclic CSV without losing reversal order.

    The actual target displacements must be supplied from the run protocol.
    This does not recover unrecorded jump flags or certify solver/physics.
    """
    source, targets = tuple(records), tuple(float(value) for value in target_displacements)
    if not source or source[0].get("stage") != "gravity":
        raise ValueError("tower cyclic history must start with its gravity endpoint")
    adapted = []
    for index, record in enumerate(source):
        if index == 0:
            stage = 0
        else:
            label = str(record.get("stage", ""))
            pieces = label.split("_")
            if len(pieces) != 3 or pieces[0] != "target" or not pieces[1].isdigit():
                raise ValueError("unexpected tower stage; cannot infer a protocol")
            stage = int(pieces[1])
            if not 1 <= stage <= len(targets) or not math.isclose(
                float(record["target_displacement"]), targets[stage - 1], rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("tower target does not match the declared protocol")
        adapted.append({"stage": stage, "u_m": record["relative_displacement"],
                        "base_shear_N": record["base_shear"]})
    return normalize_legacy_diagnostic_history(adapted, targets)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fields", nargs="+", default=["base_shear"])
    parser.add_argument("--maximum-progress-gap", type=float)
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--legacy-diagnostic-targets", nargs="+", type=float,
                        help="explicit target displacements in m for old diagnostic CSVs")
    formats.add_argument("--tower-cyclic-targets", nargs="+", type=float,
                        help="explicit target displacements in m for full_tower_cyclic CSVs")
    arguments = parser.parse_args(argv)
    with arguments.reference.open(encoding="utf-8-sig", newline="") as stream:
        reference = list(csv.DictReader(stream))
    with arguments.candidate.open(encoding="utf-8-sig", newline="") as stream:
        candidate = list(csv.DictReader(stream))
    stages = None
    targets = arguments.legacy_diagnostic_targets if arguments.legacy_diagnostic_targets is not None else arguments.tower_cyclic_targets
    if targets is not None:
        adapter = normalize_legacy_diagnostic_history if arguments.legacy_diagnostic_targets is not None else normalize_tower_cyclic_history
        reference = adapter(reference, targets)
        candidate = adapter(candidate, targets)
        previous = 0.
        stages = []
        for index, target in enumerate(targets, 1):
            stages.append((str(index), 1 if target > previous else -1 if target < previous else 0))
            previous = target
    result = compare_protocol_histories(reference, candidate, value_fields=arguments.fields,
                                        maximum_progress_gap=arguments.maximum_progress_gap,
                                        protocol_stages=stages)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    # New output only: evidence from a prior comparison is never overwritten.
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": result["status"], "common_progress": result["common_progress"],
                      "output": str(arguments.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
