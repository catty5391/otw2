"""Evidence-backed result quality, independent of numerical completion.

This module does not invoke OpenSees, stop an analysis or classify nonconvergence
as physical failure. Domain actions are instructions for an owning workflow to
persist and stop (or explicitly continue a diagnostic). Evidence references are
provenance, not an automatic scientific verification of the referenced report.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

SCHEMA = "otw2.result_quality.v1"
EXECUTION = {"not_started", "running", "completed", "nonconverged", "failed", "interrupted", "legacy_unknown"}
VALIDATION = {"unvalidated", "validated", "failed", "legacy_unknown"}
DOMAIN = {"unknown", "in_range", "out_of_range", "legacy_unknown"}
LIMIT_STATE = {"not_evaluated", "not_reached", "reached", "indeterminate", "legacy_unknown"}
PURPOSES = {"training_fit", "independent_validation", "diagnostic", "formal_research", "legacy_unknown"}
POLICIES = {"stop", "fail", "diagnostic_continue"}


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class MemberDomainRange:
    """One actual member/quantity validity interval, including optional context.

    Bounds are inclusive and signed; no universal 3% limit is assumed. Multiple
    quantities may be registered for one original member. Direction and boundary
    restrictions are labels supplied by the declaring calibration, not inferred
    from the sign of an observation.
    """

    member_id: str | int
    quantity: str
    lower: float
    upper: float
    evidence_ids: tuple[str, ...]
    unit: str = "dimensionless"
    allowed_directions: tuple[str, ...] = ()
    allowed_boundaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.member_id).strip() or not self.quantity or not self.unit:
            raise ValueError("member_id, quantity and unit are required")
        if _finite(self.lower, "lower") >= _finite(self.upper, "upper"):
            raise ValueError("lower must be smaller than upper")
        for name in ("evidence_ids", "allowed_directions", "allowed_boundaries"):
            values = getattr(self, name)
            if isinstance(values, str) or any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"{name} must contain nonempty strings")
            object.__setattr__(self, name, tuple(values))
        if not self.evidence_ids:
            raise ValueError("domain evidence is required")
        object.__setattr__(self, "member_id", str(self.member_id))

    @property
    def key(self) -> str:
        # JSON encoding avoids collisions when IDs or quantities contain colons.
        return json.dumps([self.member_id, self.quantity], ensure_ascii=False)


class ResultQuality:
    """Mutable assessment with conservative, derived statistical eligibility."""

    def __init__(self, *, purpose: str = "diagnostic", domain_policy: str = "stop") -> None:
        if purpose not in PURPOSES or domain_policy not in POLICIES:
            raise ValueError("unknown purpose or domain policy")
        self._data: dict[str, Any] = {
            "schema": SCHEMA, "purpose": purpose, "domain_policy": domain_policy,
            "execution_status": "not_started", "validation_status": "unvalidated",
            "validation_scope": [], "validation_evidence_ids": [],
            "domain_status": "unknown", "domain_audit_evidence_ids": [],
            "limit_state_status": "not_evaluated", "limit_state_evidence_ids": [],
            "limit_state_criteria_id": None, "limit_state_criteria_evidence_ids": [],
            "coverage": {"requested": None, "completed": 0, "unit": "steps"},
            "quality_flags": [], "evidence": {}, "member_domains": {},
            "observed_domains": [], "first_out_of_domain_event": None,
            "first_out_of_domain_by_member": {}, "events": [], "failure_reason": None,
        }
        self._last_steps: dict[str, int] = {}

    def add_evidence(self, evidence_id: str, source: str, description: str = "") -> None:
        if not evidence_id or not source or not isinstance(evidence_id, str) or not isinstance(source, str):
            raise ValueError("evidence requires a nonempty ID and source reference")
        item = {"source": source, "description": description}
        if evidence_id in self._data["evidence"] and self._data["evidence"][evidence_id] != item:
            raise ValueError("an evidence ID cannot be silently reassigned")
        self._data["evidence"][evidence_id] = item

    def _evidence(self, evidence_ids: Iterable[str]) -> list[str]:
        if isinstance(evidence_ids, str):
            raise ValueError("evidence_ids must be a sequence, not a string")
        ids = list(dict.fromkeys(evidence_ids))
        if not ids or any(item not in self._data["evidence"] for item in ids):
            raise ValueError("nonempty registered evidence IDs are required")
        return ids

    def _flag(self, flag: str) -> None:
        if flag not in self._data["quality_flags"]:
            self._data["quality_flags"].append(flag)

    def set_execution(self, status: str, *, failure_reason: str | None = None) -> None:
        if status not in EXECUTION:
            raise ValueError("unknown execution status")
        self._data.update(execution_status=status, failure_reason=failure_reason)

    def set_coverage(self, requested: int | None, completed: int, *, unit: str = "targets") -> None:
        _integer(completed, "completed")
        if requested is not None:
            _integer(requested, "requested")
        if not isinstance(unit, str) or not unit:
            raise ValueError("coverage unit is required")
        self._data["coverage"] = {"requested": requested, "completed": completed, "unit": unit}

    def set_validation(self, status: str, *, scope: Iterable[str] = (),
                       evidence_ids: Iterable[str] = (), flags: Iterable[str] = ()) -> None:
        if status not in VALIDATION:
            raise ValueError("unknown validation status")
        if isinstance(scope, str) or isinstance(flags, str):
            raise ValueError("scope and flags must be sequences")
        scope, flags = list(scope), list(flags)
        if any(not isinstance(item, str) or not item for item in (*scope, *flags)):
            raise ValueError("scope and flags must contain nonempty strings")
        evidence = self._evidence(evidence_ids) if status in {"validated", "failed"} else []
        if status == "validated" and not scope:
            raise ValueError("validated needs an explicit validation scope")
        self._data.update(validation_status=status, validation_scope=scope, validation_evidence_ids=evidence)
        for flag in flags:
            self._flag(flag)

    def register_domain(self, domain: MemberDomainRange) -> None:
        self._evidence(domain.evidence_ids)
        if domain.key in self._data["member_domains"]:
            raise ValueError("member/quantity domain already registered")
        if self._data["domain_audit_evidence_ids"]:
            raise ValueError("domain audit is already closed")
        self._data["member_domains"][domain.key] = asdict(domain)

    def observe_member_state(
        self, member_id: str | int, quantity: str, value: float, *, accepted_step: int,
        evidence_ids: Iterable[str], stage_id: str | int | None = None,
        direction: str | None = None, boundary: str | None = None, committed: bool = True,
    ) -> str:
        """Return continue/stop/fail/diagnostic_continue; trial data are ignored.

        Callers must not reinterpret a post-commit stop as an uncommitted retry.
        A missing domain/context is unknown (not evidence of in-range behavior).
        """
        if not isinstance(committed, bool):
            raise ValueError("committed must be boolean")
        if not committed:
            return "ignored_trial"
        if self._data["domain_audit_evidence_ids"]:
            raise ValueError("domain audit is closed; finish it only after the final observation")
        step = _integer(accepted_step, "accepted_step")
        value = _finite(value, "value")
        evidence = self._evidence(evidence_ids)
        key = json.dumps([str(member_id), quantity], ensure_ascii=False)
        if step < self._last_steps.get(key, -1):
            raise ValueError("committed observations must be chronological per member/quantity")
        self._last_steps[key] = step
        domain = self._data["member_domains"].get(key)
        reasons: list[str] = []
        unknown = False
        if domain is None:
            reasons, unknown = ["unregistered_member_domain"], True
        else:
            if not domain["lower"] <= value <= domain["upper"]:
                reasons.append("quantity_out_of_range")
            for label, actual in (("directions", direction), ("boundaries", boundary)):
                allowed = domain[f"allowed_{label}"]
                if allowed and actual is None:
                    reasons.append(f"missing_{label}_context")
                    unknown = True
                elif allowed and actual not in allowed:
                    reasons.append(f"unsupported_{label}")
            if not reasons and key not in self._data["observed_domains"]:
                self._data["observed_domains"].append(key)
        if not reasons:
            return "continue"
        event = {
            "event_id": f"domain-{len(self._data['events']) + 1}", "member_id": str(member_id),
            "quantity": quantity, "value": value, "accepted_step": step, "stage_id": stage_id,
            "direction": direction, "boundary": boundary, "committed": True,
            "allowed_range": None if domain is None else [domain["lower"], domain["upper"]],
            "unit": None if domain is None else domain["unit"], "reasons": reasons,
            "evidence_ids": evidence, "domain_evidence_ids": [] if domain is None else list(domain["evidence_ids"]),
            "action": self._data["domain_policy"],
        }
        self._data["events"].append(event)
        # A numerical bound violation remains known even when context is missing.
        known_violation = "quantity_out_of_range" in reasons or any(item.startswith("unsupported_") for item in reasons)
        if known_violation:
            self._data["domain_status"] = "out_of_range"
            self._flag("out_of_calibration_range")
            first = self._data["first_out_of_domain_event"]
            if first is None or event["accepted_step"] < first["accepted_step"]:
                self._data["first_out_of_domain_event"] = event
            first_member = self._data["first_out_of_domain_by_member"].get(str(member_id))
            if first_member is None or event["accepted_step"] < first_member["accepted_step"]:
                self._data["first_out_of_domain_by_member"][str(member_id)] = event
        if unknown:
            self._flag("unknown_domain_context")
        return self._data["domain_policy"]

    def finish_domain_audit(self, *, evidence_ids: Iterable[str]) -> None:
        evidence = self._evidence(evidence_ids)
        domains = self._data["member_domains"]
        if not domains:
            raise ValueError("no member domains declared")
        self._data["domain_audit_evidence_ids"] = evidence
        if self._data["domain_status"] == "out_of_range":
            return
        if set(domains) <= set(self._data["observed_domains"]) and not self._data["events"]:
            self._data["domain_status"] = "in_range"
        else:
            self._flag("incomplete_domain_audit")

    def set_limit_state(self, status: str, *, criteria_id: str | None = None,
                        criteria_evidence_ids: Iterable[str] = (), evidence_ids: Iterable[str] = ()) -> None:
        if status not in LIMIT_STATE:
            raise ValueError("unknown limit-state status")
        assessed = status in {"reached", "not_reached"}
        evidence = self._evidence(evidence_ids) if assessed else []
        criteria_evidence = self._evidence(criteria_evidence_ids) if assessed else []
        if assessed and not criteria_id:
            raise ValueError("physical assessment requires a frozen criteria ID")
        self._data.update(limit_state_status=status, limit_state_criteria_id=criteria_id,
                          limit_state_evidence_ids=evidence, limit_state_criteria_evidence_ids=criteria_evidence)

    def to_dict(self) -> dict[str, Any]:
        data = copy.deepcopy(self._data)
        json.dumps(data, allow_nan=False)
        data["eligible_for_fragility"] = _eligible(data)
        return data


def _eligible(data: Mapping[str, Any]) -> bool:
    coverage = data["coverage"]
    return bool(
        data["execution_status"] == "completed" and data["purpose"] == "formal_research"
        and data["validation_status"] == "validated" and data["domain_status"] == "in_range"
        and data["limit_state_status"] in {"reached", "not_reached"}
        and coverage["requested"] is not None and coverage["requested"] > 0
        and coverage["completed"] >= coverage["requested"] and not data["quality_flags"]
        and data["validation_scope"] and data["validation_evidence_ids"]
        and data["domain_audit_evidence_ids"] and data["limit_state_criteria_id"]
        and data["limit_state_evidence_ids"] and data["limit_state_criteria_evidence_ids"]
    )


def normalize_result_quality(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Read a manifest conservatively; never trust a stored eligible=True.

    Legacy/unknown/malformed payloads are returned as quarantined metadata, not
    raised exceptions. This reader does not rewrite historical files.
    """
    fallback = ResultQuality(purpose="legacy_unknown").to_dict()
    fallback.update(validation_status="legacy_unknown", domain_status="legacy_unknown",
                    limit_state_status="legacy_unknown", execution_status="legacy_unknown")
    if isinstance(manifest, Mapping) and isinstance(manifest.get("status"), str) and manifest["status"] in EXECUTION:
        fallback["execution_status"] = manifest["status"]
    try:
        data = copy.deepcopy(manifest["quality"])
        if data["schema"] != SCHEMA:
            raise ValueError("unknown quality schema")
        json.dumps(data, allow_nan=False)
        for key in ResultQuality()._data:
            if key not in data:
                raise ValueError(f"missing {key}")
        for key, allowed in (("execution_status", EXECUTION), ("validation_status", VALIDATION),
                             ("domain_status", DOMAIN), ("limit_state_status", LIMIT_STATE),
                             ("purpose", PURPOSES), ("domain_policy", POLICIES)):
            if data[key] not in allowed:
                raise ValueError(f"unknown {key}")
        if manifest.get("status", data["execution_status"]) != data["execution_status"]:
            raise ValueError("execution status conflicts with legacy status")
        evidence = data["evidence"]
        def check_ids(ids: Any) -> None:
            if not isinstance(ids, list) or not ids or any(
                not isinstance(item, str) or item not in evidence
                or not isinstance(evidence[item], dict) or not isinstance(evidence[item].get("source"), str)
                or not evidence[item]["source"] for item in ids
            ):
                raise ValueError("invalid evidence references")
        for key in ("quality_flags", "validation_scope", "observed_domains", "events"):
            if not isinstance(data[key], list):
                raise ValueError(f"invalid {key}")
        for key in ("quality_flags", "validation_scope", "observed_domains"):
            if any(not isinstance(item, str) or not item for item in data[key]):
                raise ValueError(f"invalid {key} entries")
        coverage = data["coverage"]
        _integer(coverage["completed"], "completed")
        if coverage["requested"] is not None:
            _integer(coverage["requested"], "requested")
        if not isinstance(coverage["unit"], str) or not coverage["unit"]:
            raise ValueError("missing coverage unit")
        if data["validation_status"] in {"validated", "failed"}:
            check_ids(data["validation_evidence_ids"])
        if data["validation_status"] == "validated" and not data["validation_scope"]:
            raise ValueError("missing validation scope")
        if data["domain_status"] == "in_range":
            check_ids(data["domain_audit_evidence_ids"])
            if not data["member_domains"] or data["events"] or not set(data["member_domains"]) <= set(data["observed_domains"]):
                raise ValueError("incomplete or contradictory domain audit")
            for item in data["member_domains"].values():
                domain = MemberDomainRange(**item)
                check_ids(list(domain.evidence_ids))
        if data["limit_state_status"] in {"reached", "not_reached"}:
            check_ids(data["limit_state_evidence_ids"])
            check_ids(data["limit_state_criteria_evidence_ids"])
            if not data["limit_state_criteria_id"]:
                raise ValueError("missing physical criteria")
        data["eligible_for_fragility"] = _eligible(data)
        return data
    except (TypeError, ValueError, KeyError, AttributeError):
        fallback["quality_flags"] = ["missing_or_invalid_quality_metadata"]
        return fallback
