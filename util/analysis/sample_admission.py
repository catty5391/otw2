"""Conservative, lossless sample accounting before fragility analysis.

No solver, curve fitting, automatic damage thresholds or censoring assumptions
are used here. Count bounds describe this supplied finite cohort under a chosen
physical criterion; they are not confidence intervals or population estimates.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .result_quality import normalize_result_quality

SCHEMA = "otw2.sample_admission.v1"
MODES = {"formal", "exploratory_legacy"}
NUMERICAL_FAILURES = {"nonconverged", "failed", "interrupted"}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_manifest_sample(
    sample_id: str, wind_speed: float, manifest_path: str | Path, *,
    response: float | None = None, maximum_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """Read one explicit manifest path; retain missing/bad files as a sample.

    ``response`` may be an explicitly precomputed old response for exploratory
    display. This function never opens response databases or starts a model.
    """
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be a positive integer")
    path = Path(manifest_path)
    sample: dict[str, Any] = {"sample_id": sample_id, "wind_speed": wind_speed,
                              "manifest_source": str(path), "manifest": None, "input_errors": []}
    if response is not None:
        sample["response"] = response
    try:
        with path.open("rb") as stream:
            data = stream.read(maximum_bytes + 1)
        if len(data) > maximum_bytes:
            sample["input_errors"].append("manifest_exceeds_read_budget")
        else:
            manifest = json.loads(data)
            if not isinstance(manifest, dict):
                sample["input_errors"].append("manifest_not_object")
            else:
                sample["manifest"] = manifest
    except FileNotFoundError:
        sample["input_errors"].append("manifest_missing")
    except (json.JSONDecodeError, UnicodeDecodeError):
        sample["input_errors"].append("manifest_invalid_json")
    except OSError as error:
        sample["input_errors"].append(f"manifest_read_error:{type(error).__name__}")
    return sample


def assess_sample(
    sample: Mapping[str, Any], *, mode: str = "formal", criteria_id: str | None = None,
) -> dict[str, Any]:
    """Produce one retained flow row, requiring a selected criterion for formal use.

    Inputs contain sample_id, wind_speed (m/s), and either manifest or the full
    result-quality object under quality. A direct quality object is wrapped with
    its execution_status, then passed through the same defensive normalizer.
    """
    if mode not in MODES:
        raise ValueError("mode must be formal or exploratory_legacy")
    if criteria_id is not None and (not isinstance(criteria_id, str) or not criteria_id.strip()):
        raise ValueError("criteria_id must be a nonempty string or None")
    if not isinstance(sample, Mapping):
        raise TypeError("each sample must be a mapping; malformed rows must be represented explicitly")
    identity = sample.get("sample_id")
    speed = sample.get("wind_speed")
    reasons: list[str] = []
    input_errors = sample.get("input_errors", [])
    if not isinstance(input_errors, (list, tuple)) or any(not isinstance(item, str) or not item for item in input_errors):
        input_errors = ["invalid_input_error_metadata"]
    else:
        input_errors = list(input_errors)
    if not isinstance(identity, str) or not identity.strip():
        reasons.append("invalid_sample_id")
    if not _finite(speed) or speed < 0:
        reasons.append("invalid_wind_speed")
    identity_valid = not reasons
    if "manifest" in sample and "quality" in sample:
        input_errors.append("ambiguous_manifest_and_quality")
    manifest = sample.get("manifest")
    if "manifest" not in sample and "quality" in sample:
        raw_quality = sample["quality"]
        manifest = {"quality": raw_quality}
        if isinstance(raw_quality, Mapping):
            manifest["status"] = raw_quality.get("execution_status", "legacy_unknown")
    quality = normalize_result_quality(manifest)
    historical_without_quality = manifest is None or (isinstance(manifest, Mapping) and "quality" not in manifest)
    reasons.extend(input_errors)
    execution = quality["execution_status"]
    if execution != "completed":
        reasons.append(execution if execution in NUMERICAL_FAILURES else "execution_not_completed")
    legacy = quality["validation_status"] == "legacy_unknown"
    if legacy:
        reasons.append("legacy")
    elif quality["validation_status"] != "validated":
        reasons.append("validation_failed" if quality["validation_status"] == "failed" else "unvalidated")
    if quality["domain_status"] == "out_of_range":
        reasons.append("out_of_domain")
    elif quality["domain_status"] != "in_range":
        reasons.append("domain_unknown")
    coverage = quality["coverage"]
    if coverage["requested"] is None or coverage["requested"] <= 0 or coverage["completed"] < coverage["requested"]:
        reasons.append("coverage_unknown_or_incomplete")
    if quality["purpose"] != "formal_research":
        reasons.append("nonformal_purpose")
    if criteria_id is None:
        reasons.append("criteria_not_selected")
    elif quality["limit_state_criteria_id"] != criteria_id:
        reasons.append("criteria_mismatch_or_missing")
    response_present = "response" in sample
    response_valid = response_present and _finite(sample["response"])
    if response_present and not response_valid:
        input_errors.append("invalid_response")
        reasons.append("invalid_response")
    formal = bool(
        identity_valid and not input_errors and quality["eligible_for_fragility"]
        and criteria_id is not None and quality["limit_state_criteria_id"] == criteria_id
    )
    physical = quality["limit_state_status"] if formal else "unknown"
    if physical == "unknown":
        reasons.append("physical_state_unknown")
    exploratory = bool(
        mode == "exploratory_legacy" and legacy and historical_without_quality and identity_valid and response_valid
        and execution in {"completed", "legacy_unknown"}
        and not set(input_errors) - {"manifest_missing"}
    )
    admission = "formal_admitted" if formal else "exploratory_legacy_only" if exploratory else "excluded"
    return {
        "sample_id": identity if isinstance(identity, str) else None,
        "wind_speed_mps": float(speed) if _finite(speed) and speed >= 0 else None,
        "manifest_source": str(sample["manifest_source"]) if sample.get("manifest_source") is not None else None,
        "response_source": str(sample["response_source"]) if sample.get("response_source") is not None else None,
        "execution_status": execution, "validation_status": quality["validation_status"],
        "domain_status": quality["domain_status"], "purpose": quality["purpose"],
        "reported_limit_state_status": quality["limit_state_status"],
        "reported_criteria_id": quality["limit_state_criteria_id"], "selected_criteria_id": criteria_id,
        "physical_state_for_selected_criterion": physical,
        "eligible_for_fragility": formal, "admission_status": admission,
        "selected_for_analysis": formal or exploratory, "analysis_mode": mode,
        "quality_flags": copy.deepcopy(quality["quality_flags"]),
        "reason_codes": list(dict.fromkeys(reasons)), "input_errors": list(dict.fromkeys(input_errors)),
        "coverage": copy.deepcopy(quality["coverage"]),
        "response": float(sample["response"]) if response_valid else None,
        "evidence": copy.deepcopy(quality["evidence"]),
        "validation_evidence_ids": copy.deepcopy(quality["validation_evidence_ids"]),
        "limit_state_evidence_ids": copy.deepcopy(quality["limit_state_evidence_ids"]),
        "limit_state_criteria_evidence_ids": copy.deepcopy(quality["limit_state_criteria_evidence_ids"]),
        "failure_reason": quality["failure_reason"],
    }


def _summarize(rows: list[dict[str, Any]], criteria_id: str | None) -> dict[str, Any]:
    total = len(rows)
    reached = sum(row["physical_state_for_selected_criterion"] == "reached" for row in rows)
    not_reached = sum(row["physical_state_for_selected_criterion"] == "not_reached" for row in rows)
    unknown = total - reached - not_reached
    failed = sum(row["execution_status"] in NUMERICAL_FAILURES for row in rows)
    unclassified_failures = sum(
        row["execution_status"] in NUMERICAL_FAILURES and row["physical_state_for_selected_criterion"] == "unknown"
        for row in rows
    )
    invalid_cohort = any(set(row["reason_codes"]) & {"duplicate_sample_identity", "invalid_sample_id", "invalid_wind_speed"} for row in rows)
    bounds_available = bool(total and criteria_id and not invalid_cohort)
    return {
        "input_records": total, "formal_admitted": sum(row["eligible_for_fragility"] for row in rows),
        "exploratory_legacy_only": sum(row["admission_status"] == "exploratory_legacy_only" for row in rows),
        "excluded": sum(row["admission_status"] == "excluded" for row in rows),
        "execution_counts": dict(sorted(Counter(row["execution_status"] for row in rows).items())),
        "reason_counts": dict(sorted(Counter(reason for row in rows for reason in row["reason_codes"]).items())),
        "numerical_failures": failed, "unclassified_numerical_failures": unclassified_failures,
        "unclassified_failure_fraction_of_failures": unclassified_failures / failed if failed else None,
        "unclassified_failure_fraction_of_all_records": unclassified_failures / total if total else None,
        "known_reached": reached, "known_not_reached": not_reached, "physical_state_unknown": unknown,
        "unknown_physical_fraction": unknown / total if total else None,
        "cohort_identity_valid": not invalid_cohort,
        "finite_cohort_event_fraction_bounds": {
            "available": bounds_available, "criteria_id": criteria_id,
            "denominator_all_records": total,
            "lower": reached / total if bounds_available else None,
            "upper": (reached + unknown) / total if bounds_available else None,
            "unavailable_reason": None if bounds_available else
                "empty_cohort" if not total else "criteria_not_selected" if not criteria_id else "invalid_cohort_identity",
            "interpretation": "Count identification bounds for this supplied cohort only; not a fitted probability or confidence interval.",
            "unknown_treatment": "Unknown outcomes remain unknown; extrema enumerate possible outcomes, not assigned collapse labels or censoring.",
        },
    }


def build_sample_flow(
    samples: Iterable[Mapping[str, Any]], *, mode: str = "formal", criteria_id: str | None = None,
    max_samples: int | None = None,
) -> dict[str, Any]:
    """Account for every supplied record and group by exact wind-speed level.

    No speed interpolation or bin rounding is performed. Duplicate (speed, ID)
    rows are retained but rejected, and their cohort's count bounds are disabled.
    A requested read budget raises instead of silently truncating the cohort.
    """
    if mode not in MODES:
        raise ValueError("unknown analysis mode")
    if criteria_id is not None and (not isinstance(criteria_id, str) or not criteria_id.strip()):
        raise ValueError("criteria_id must be a nonempty string or None")
    if max_samples is not None and (isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 0):
        raise ValueError("max_samples must be a nonnegative integer or None")
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if max_samples is not None and index >= max_samples:
            raise ValueError("sample budget exceeded; no truncated report was produced")
        row = assess_sample(sample, mode=mode, criteria_id=criteria_id)
        row["record_index"] = index
        rows.append(row)
    identities = Counter((row["wind_speed_mps"], row["sample_id"]) for row in rows)
    for row in rows:
        if identities[(row["wind_speed_mps"], row["sample_id"])] > 1:
            row["reason_codes"] = list(dict.fromkeys([*row["reason_codes"], "duplicate_sample_identity", "physical_state_unknown"]))
            row.update(eligible_for_fragility=False, selected_for_analysis=False, admission_status="excluded",
                       physical_state_for_selected_criterion="unknown")
    levels = sorted({row["wind_speed_mps"] for row in rows}, key=lambda speed: (speed is None, speed or 0.0))
    by_speed = [{"wind_speed_mps": speed, **_summarize([row for row in rows if row["wind_speed_mps"] == speed], criteria_id)} for speed in levels]
    report = {
        "schema": SCHEMA, "mode": mode, "criteria_id": criteria_id,
        "wind_speed_unit": "m/s", "rows": rows, "overall": _summarize(rows, criteria_id), "by_wind_speed": by_speed,
        "warnings": [
            "No sample was silently discarded; reason categories may overlap.",
            "Formal labels require normalized quality, selected physical criteria and complete declared coverage.",
            "Reported limit states from excluded samples are retained but not counted as verified formal outcomes.",
            "No numerical failure was automatically classified as collapse or right-censored.",
            "Counts describe only supplied samples; the caller must supply the complete predeclared cohort, including missing runs.",
        ],
    }
    json.dumps(report, allow_nan=False)
    return report
