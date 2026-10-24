"""Pre-frozen cyclic experiment design without importing/running OpenSees.

Numerical amplitudes are resolved only from accepted reference fiber/peak
observations. Resolving a recipe does not validate its cyclic mechanical result.
The design package and later reference bindings are separate immutable inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

PACKAGE_SCHEMA = "otw2.cyclic_protocol_design.v1"
BINDINGS_SCHEMA = "otw2.cyclic_reference_bindings.v1"
DEFAULT_PACKAGE = Path(__file__).with_name("protocols") / "t10_pre_frozen_v1.json"


class ProtocolContractError(ValueError):
    pass


class ReferenceNotReadyError(ProtocolContractError):
    pass


def fingerprint(package: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(package, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ProtocolContractError(f"{name} must be finite")
    return float(value)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Validate design/split integrity, not missing future reference results."""
    try:
        if package["schema"] != PACKAGE_SCHEMA or package["design_frozen"] is not True:
            raise ProtocolContractError("unknown schema or design not frozen")
        if package["amplitude_status"] != "pending_reference_bindings":
            raise ProtocolContractError("the frozen design must not fabricate numerical reference amplitudes")
        groups, sources, anchors = package["groups"], package["response_sources"], package["anchor_definitions"]
        case_ids = set()
        roles = Counter()
        training_boundaries, held_out_boundaries = set(), set()
        for case in package["cases"]:
            case_id = case["case_id"]
            if not isinstance(case_id, str) or not case_id or case_id in case_ids:
                raise ProtocolContractError("case IDs must be unique nonempty strings")
            case_ids.add(case_id)
            role = case["split"]
            if role not in {"training", "holdout", "diagnostic"}:
                raise ProtocolContractError("unknown split role")
            if case.get("fitting_allowed") is not (role == "training"):
                raise ProtocolContractError("fitting_allowed must match the frozen training split")
            roles[role] += 1
            group = groups[case["group_id"]]
            if _finite(group["length_m"], "length") <= 0 or case["member_id"] not in group["actual_member_ids"]:
                raise ProtocolContractError("case does not identify an actual member in its declared group")
            if case["boundary_id"] not in package["boundaries"]:
                raise ProtocolContractError("unknown boundary")
            source = sources[case["response_source_id"]]
            if source["split"] != role or source["group_id"] != case["group_id"]:
                raise ProtocolContractError("response source conflicts with frozen case split/group")
            if role == "holdout" and (source["previously_used_for_diagnosis"] or not source["reserved_before_calibration"]):
                raise ProtocolContractError("seen diagnostic data cannot be relabeled as independent holdout")
            if role == "training":
                training_boundaries.add(case["boundary_id"])
            if role == "holdout":
                held_out_boundaries.add(case["boundary_id"])
            if case["protocol"] == "C0" and case["reference_material"] != "Elastic":
                raise ProtocolContractError("strict C0 reversibility requires pure Elastic steel")
            if case["path_kind"] == "reference_anchored_axial":
                amplitude_source = package["amplitude_references"][case["amplitude_reference_id"]]
                if any(amplitude_source[key] != case[key] for key in ("group_id", "boundary_id")) or amplitude_source["material_model"] != case["reference_material"]:
                    raise ProtocolContractError("amplitude reference belongs to a different group, boundary or material")
                points = case["targets"]
                if not points or points[0]["anchor"] != "zero" or points[-1]["anchor"] != "zero":
                    raise ProtocolContractError("axial protocols must start and finish at zero end shortening")
                for point in points:
                    if set(point) != {"anchor", "factor"} or point["anchor"] not in anchors:
                        raise ProtocolContractError("targets must reference measured anchors, not raw/equivalent strain")
                    factor = _finite(point["factor"], "anchor factor")
                    if not 0 <= factor <= 1:
                        raise ProtocolContractError("anchor scaling cannot extrapolate beyond accepted reference")
            elif case["path_kind"] == "two_end_6dof_history":
                if case["targets"] or case["boundary_id"] != "tower_6dof_replay":
                    raise ProtocolContractError("6DOF history cannot be fabricated from scalar targets")
            else:
                raise ProtocolContractError("unknown path kind")
        if not roles["training"] or not roles["holdout"] or not held_out_boundaries - training_boundaries:
            raise ProtocolContractError("reserve both training and a non-training boundary class for holdout")
        return {"schema": PACKAGE_SCHEMA, "design_valid": True, "package_sha256": fingerprint(package),
                "cases": len(case_ids), "split_counts": dict(roles), "resolved_cases": 0,
                "amplitude_status": "pending_reference_bindings", "physical_validation_passed": False}
    except (KeyError, TypeError, OverflowError) as error:
        raise ProtocolContractError(f"incomplete or malformed design: {error}") from error


def validate_usage(package: Mapping[str, Any], *, fit_case_ids=(), model_selection_case_ids=(), response_fingerprints=()) -> None:
    """Reject holdout leakage, including identical response files under new IDs."""
    validate_package(package)
    roles = {case["case_id"]: case["split"] for case in package["cases"]}
    for case_id in fit_case_ids:
        if roles.get(case_id) != "training":
            raise ProtocolContractError(f"parameter fitting requires training-only case: {case_id}")
    for case_id in model_selection_case_ids:
        if case_id not in roles or roles[case_id] == "holdout":
            raise ProtocolContractError(f"holdout/unknown case used for model selection: {case_id}")
    seen: dict[str, set[str]] = {}
    for item in response_fingerprints:
        if item.get("case_id") not in roles or not _sha256(item.get("sha256")):
            raise ProtocolContractError("response provenance needs a known case and SHA256")
        seen.setdefault(item["sha256"], set()).add(roles[item["case_id"]])
    if any("holdout" in values and len(values) > 1 for values in seen.values()):
        raise ProtocolContractError("identical response data cross holdout/training-or-diagnostic boundaries")


def _evidence(bindings: Mapping[str, Any], ids: Any) -> None:
    if not isinstance(ids, list) or not ids:
        raise ReferenceNotReadyError("accepted reference evidence IDs are required")
    registry = bindings.get("evidence", {})
    for identity in ids:
        item = registry.get(identity, {})
        if not item.get("source") or not _sha256(item.get("sha256")):
            raise ReferenceNotReadyError(f"unresolved source/fingerprint for evidence {identity}")


def resolve_case(package: Mapping[str, Any], case_id: str, bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve measured SI control targets; never run or claim validation of FE."""
    validate_package(package)
    case = next((item for item in package["cases"] if item["case_id"] == case_id), None)
    if case is None:
        raise ProtocolContractError(f"unknown case {case_id}")
    if bindings.get("schema") != BINDINGS_SCHEMA or bindings.get("package_sha256") != fingerprint(package):
        raise ReferenceNotReadyError("reference bindings must match the exact frozen package hash")
    for gate, status in (("G1", "passed"), ("T09", "completed")):
        record = bindings.get("gates", {}).get(gate, {})
        if record.get("status") != status:
            raise ReferenceNotReadyError(f"{gate} is not {status}; do not invent amplitudes")
        _evidence(bindings, record.get("evidence_ids"))
    usage = bindings.get("usage", {})
    validate_usage(package, fit_case_ids=usage.get("fit_case_ids", []),
                   model_selection_case_ids=usage.get("model_selection_case_ids", []),
                   response_fingerprints=usage.get("response_fingerprints", []))
    resolved = {"case_id": case_id, "split": case["split"], "group_id": case["group_id"],
                "member_id": case["member_id"], "boundary_id": case["boundary_id"],
                "package_sha256": fingerprint(package), "reference_bindings_sha256": fingerprint(bindings),
                "recipe_ready": True, "analysis_executed": False, "physical_validation_passed": False,
                "preyield_reversibility": "to_measure_not_assumed", "path_kind": case["path_kind"]}
    if case["path_kind"] == "two_end_6dof_history":
        history = bindings.get("histories", {}).get(case["response_source_id"], {})
        required_true = ("completed", "includes_initial_unloaded_state", "includes_gravity", "both_end_6dof", "committed_only")
        if any(history.get(key) is not True for key in required_true):
            raise ReferenceNotReadyError("history requires complete initial/gravity/committed two-end 6DOF data")
        if history.get("member_id") != case["member_id"] or history.get("group_id") != case["group_id"]:
            raise ProtocolContractError("history belongs to a different actual member")
        if not history.get("path") or not _sha256(history.get("sha256")):
            raise ReferenceNotReadyError("history path and fingerprint are required")
        _evidence(bindings, history.get("evidence_ids"))
        if case["split"] == "holdout" and (history.get("used_for_parameter_fit") is not False or history.get("independent_future_path") is not True):
            raise ProtocolContractError("holdout requires an independent future path unused for fitting")
        resolved["history"] = dict(history)
        return resolved
    reference = bindings.get("references", {}).get(case["amplitude_reference_id"], {})
    if reference.get("completed") is not True or reference.get("mesh_and_fiber_accepted") is not True:
        raise ReferenceNotReadyError("complete mesh/fiber-accepted reference is required")
    for key in ("group_id", "boundary_id"):
        if reference.get(key) != case[key]:
            raise ProtocolContractError(f"reference {key} does not match the case")
    if reference.get("material_model") != case["reference_material"] or reference.get("control_quantity") != "end_shortening_m":
        raise ProtocolContractError("reference material/control mismatch; equivalent strain is not a fiber criterion")
    _evidence(bindings, reference.get("evidence_ids"))
    if reference.get("fiber_coverage") != "all_declared_sections_and_fibers":
        raise ReferenceNotReadyError("first-yield classification requires declared complete reference fiber coverage")
    if case["reference_material"] == "Steel02":
        yielding = reference.get("first_nominal_fy_crossing", {})
        if not isinstance(yielding.get("observed"), bool) or yielding.get("criterion") != "first_committed_max_abs_sigma_over_fy_ge_1":
            raise ReferenceNotReadyError("reference must report whether nominal fiber fy was crossed, not guess from equivalent strain")
        _evidence(bindings, yielding.get("evidence_ids"))
        if yielding["observed"]:
            _finite(yielding.get("end_shortening_m"), "first nominal fy-crossing control")
            if _finite(yielding.get("max_abs_fiber_stress_over_fy"), "fy-crossing ratio") < 1:
                raise ProtocolContractError("reported nominal fy crossing contradicts recorded fiber stress")
    lower, upper = reference.get("accepted_control_range_m", [None, None])
    lower, upper = _finite(lower, "lower control bound"), _finite(upper, "upper control bound")
    if not lower <= 0 <= upper or lower == upper:
        raise ProtocolContractError("reference control domain must bracket the unloaded endpoint")
    targets = []
    for target in case["targets"]:
        anchor_id = target["anchor"]
        if anchor_id == "zero":
            value = 0.0
        else:
            definition = package["anchor_definitions"][anchor_id]
            anchor = reference.get("anchors", {}).get(anchor_id, {})
            if anchor.get("committed") is not True or anchor.get("observation_kind") != definition["observation_kind"]:
                raise ReferenceNotReadyError(f"{anchor_id} lacks committed fiber/peak state evidence")
            _evidence(bindings, anchor.get("evidence_ids"))
            value = _finite(anchor.get("end_shortening_m"), anchor_id)
            if not lower <= value <= upper:
                raise ProtocolContractError("anchor itself lies outside the accepted reference domain")
            fiber_ratio = _finite(anchor.get("max_abs_fiber_stress_over_fy"), "reference fiber ratio")
            if fiber_ratio < 0 or value * definition["expected_sign"] <= 0:
                raise ProtocolContractError("fiber ratio or axial-control sign is inconsistent")
            ceiling = definition.get("fiber_stress_ratio_ceiling")
            if ceiling is not None and fiber_ratio > ceiling:
                raise ProtocolContractError("reference fiber state violates the pre-frozen small-cycle margin")
            if definition.get("requires_after_peak") and anchor.get("after_observed_peak") is not True:
                raise ReferenceNotReadyError("postpeak amplitude needs an observed reference peak")
            value *= target["factor"]
        if not lower <= value <= upper:
            raise ProtocolContractError("target exceeds accepted reference domain; extrapolation forbidden")
        targets.append(value)
    resolved.update(control_quantity="end_shortening_m", compression_positive=True, targets_m=targets,
                    amplitude_reference_id=case["amplitude_reference_id"], reference_evidence_ids=reference["evidence_ids"])
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate frozen cyclic design or resolve reference-backed recipes; never run FE.")
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--case")
    parser.add_argument("--bindings", type=Path)
    args = parser.parse_args(argv)
    package = json.loads(args.package.read_text(encoding="utf-8"))
    try:
        result = validate_package(package)
        if args.case:
            if args.bindings is None:
                raise ReferenceNotReadyError("--case requires --bindings from accepted reference observations")
            result = resolve_case(package, args.case, json.loads(args.bindings.read_text(encoding="utf-8")))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except ProtocolContractError as error:
        print(json.dumps({"recipe_ready": False, "reason": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
