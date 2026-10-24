from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

from util.analysis.result_quality import MemberDomainRange, ResultQuality, normalize_result_quality


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
RESULT_ROOT = PROJECT_ROOT / "initial_imperfection_material" / "results"
CYCLIC_ROOT = RESULT_ROOT / "full_tower_cyclic"

MODEL_KEYS = {"equivalent", "segmented_reference"}
FORCE_COMPONENTS = {"p", "vy", "vz", "t", "my", "mz"}
API_SCHEMA = "otw2.results_dashboard.v2"
QUALITY_SUMMARY_SCHEMA = "otw2.result_quality_summary.v1"
FIRST_DOMAIN_PREVIEW_LIMIT = 20
TMQ_CASE_KEYS = {"p102_row_a", "p102_row_b", "p89_pf"}
TMQ_PUBLIC_FILES = {
    "README.md", "REPORT.md", "results/index.html", "results/summary.json",
    "results/full_hysteresis.png", "results/full_hysteresis.svg", "results/full_hysteresis.pdf",
    "results/loading_history.png", "results/mechanism_checks.png", "results/assumption_sensitivity.png",
} | {f"results/{case}/{filename}" for case in TMQ_CASE_KEYS
     for filename in ("history.csv", "opensees_history.csv", "events.json")}
TMQ_TOWER_RUNS = {"tmq_bounded_03", "tmq_cyclic_02", "elastic_control_02"}
TMQ_PUBLIC_FILES |= {f"tower_results/{name}" for name in (
    "publication.json", "verification.json", "index.html", "full_tower_hysteresis.svg", "full_tower_hysteresis.png",
    "full_tower_hysteresis.pdf", "critical_members.svg", "extended_hysteresis.svg")}
TMQ_PUBLIC_FILES |= {f"tower_results/{run}/{name}" for run in TMQ_TOWER_RUNS for name in (
    "summary.json", "history.csv", "member_states.csv.gz", "internal_forces.sqlite", "attempts.jsonl",
    "equilibrium.jsonl", "model_data/tmq_member_parameters.csv")}
TMQ_PUBLIC_FILES |= {f"weakness_results/{name}" for name in (
    "summary.json", "index.html", "bounded_members.csv", "extended_members.csv", "panel_history.csv",
    "panel_envelopes.csv", "amplitude_envelopes.csv", "section_nodes.csv", "verification.json")}
TMQ_PUBLIC_FILES |= {f"weakness_results/{name}.{ext}" for name in (
    "weakness_locations", "isdr_profiles", "event_sequence") for ext in ("svg", "png", "pdf")}
TMQ_PUBLIC_FILES |= {f"weakness_runs/bounded_with_nodes_01/{name}" for name in (
    "summary.json", "history.csv", "node_states.csv.gz")}
TMQ_DIRECTIONAL_ROOT = "directional_results_v2"
TMQ_DIRECTIONAL_CASES = {f"{mode}_{angle}" for mode in ("single","tower_line") for angle in (0,30,45,90)}
TMQ_PUBLIC_FILES |= {f"{TMQ_DIRECTIONAL_ROOT}/{name}" for name in (
    "summary.json","case_summary.csv","index.html","verification.json",
    "small_cycles.svg","small_cycles.png","small_cycles.pdf",
    "reference_loads.svg","reference_loads.png","reference_loads.pdf")}
TMQ_PUBLIC_FILES |= {f"{TMQ_DIRECTIONAL_ROOT}/runs/{case}/{name}" for case in TMQ_DIRECTIONAL_CASES for name in (
    "summary.json","history.csv","wind_load_plan.json","wind_nodal_loads.csv","wind_config.json",
    "equilibrium.jsonl","attempts.jsonl","support_reactions.csv","line_history.csv",
    "node_states.csv.gz","member_states.csv.gz","internal_forces.sqlite")}
TMQ_WIND_SPEED_ROOT = "wind_speed_results"
TMQ_MODAL_ROOT = "modal_results"
TMQ_MODAL_CASES = {"bare_checked","coupled_20_checked","coupled_40_checked","coupled_80_checked"}
TMQ_PUBLIC_FILES |= {f"{TMQ_MODAL_ROOT}/{name}" for name in (
    "summary.json","index.html","verification.json","tower_mode_comparison.csv")}
TMQ_PUBLIC_FILES |= {f"{TMQ_MODAL_ROOT}/{name}.{ext}" for name in (
    "frequency_comparison","modal_participation","mode_shapes") for ext in ("svg","png","pdf")}
TMQ_PUBLIC_FILES |= {f"{TMQ_MODAL_ROOT}/runs/{case}/{name}" for case in TMQ_MODAL_CASES for name in (
    "summary.json","modes.csv","eigenvectors.npz","geometry.json","viewer_data.json",
    "opensees_modal_properties.txt","opensees_modal_properties.json","stiffness.npz","mass.npz","equation_modes.npz")}
TMQ_B1_ROOT = "followup_results/B1_20261024"
TMQ_PUBLIC_FILES |= {f"{TMQ_B1_ROOT}/{name}" for name in (
    "index.html","summary.json","REPORT.md","verification.json","execution_status.json","execution_log.md","publication_manifest.json")}
TMQ_PUBLIC_FILES |= {f"{TMQ_B1_ROOT}/{group}/{name}" for group in ("audit","modal","wind_projection","damping")
    for name in ("REPORT.md","summary.json","verification.json","execution_log.md")}
TMQ_PUBLIC_FILES |= {f"{TMQ_B1_ROOT}/{name}" for name in (
    "audit/model_contract.json","audit/model_difference_table.csv","audit/baseline_check.json","audit/evidence_index.csv",
    "modal/candidate_modes.csv","modal/modal_groups.csv","modal/subspace_checks.json","modal/frozen_config.json",
    "wind_projection/static_observations.csv","wind_projection/generalized_wind_loads.csv","wind_projection/load_audits.json",
    "wind_projection/static_truncation.json","wind_projection/mesh_comparison.csv","wind_projection/load_ledger.json",
    "wind_projection/truncation_summary.csv","wind_projection/direct_static_observations.csv",
    "damping/damping_candidates.json","damping/damping_spectrum.csv","damping/transient_adapter_spec.md")}
TMQ_PUBLIC_FILES |= {f"{TMQ_B1_ROOT}/{name}.{ext}" for name in (
    "modal/selected_vs_group_tower_participation","modal/tower_modal_group_distribution","modal/low_frequency_cable_subspace",
    "wind_projection/static_truncation","wind_projection/generalized_wind_force","wind_projection/static_mesh_comparison",
    "wind_projection/primary_static_response","damping/damping_spectrum") for ext in ("svg","png","pdf")}
TMQ_PUBLIC_FILES |= {f"{TMQ_B1_ROOT}/modal_view/{p.removeprefix(TMQ_MODAL_ROOT+'/')}"
                     for p in tuple(TMQ_PUBLIC_FILES) if p.startswith(TMQ_MODAL_ROOT+'/')}
TMQ_WIND_SPEED_CASES = {case+suffix for case in TMQ_DIRECTIONAL_CASES for suffix in ("","_extended","_fine","_disp")}
TMQ_PUBLIC_FILES |= {f"{TMQ_WIND_SPEED_ROOT}/{name}" for name in (
    "summary.json","case_summary.csv","index.html","verification.json",
    "wind_response.svg","wind_response.png","wind_response.pdf",
    "pushover_response.svg","pushover_response.png","pushover_response.pdf")}
TMQ_PUBLIC_FILES |= {f"{TMQ_WIND_SPEED_ROOT}/runs/{case}/{name}" for case in TMQ_WIND_SPEED_CASES for name in (
    "summary.json","history.csv","wind_load_plan.json","wind_nodal_loads.csv","wind_config.json",
    "equilibrium.jsonl","attempts.jsonl","support_reactions.csv","line_history.csv",
    "node_states.csv.gz","member_states.csv.gz","internal_forces.sqlite","model_data/tmq_member_parameters.csv")}
DIAGNOSTIC_CASES = {
    "baseline": "原步长：历史卡点",
    "fine_sparse": "细步长：同材料完整协议",
    "elastic_877_878": "877/878临时Elastic：查因消融",
}


class DashboardData:
    """Read the generated result files without rerunning an OpenSees analysis."""

    def __init__(self, project_root: str | Path = PROJECT_ROOT) -> None:
        self.project_root = Path(project_root).resolve()
        self.result_root = self.project_root / "initial_imperfection_material" / "results"
        self.cyclic_root = self.result_root / "full_tower_cyclic"
        self.tmq_root = self.project_root / "initial_imperfection_material" / "tian_ma_qu"
        self._geometry_cache: dict[int, dict[str, Any]] | None = None
        self._diagnostic_cache: tuple[Any, dict[str, Any]] | None = None

    def _existing_file(self, path: Path) -> Path | None:
        resolved = path.resolve()
        return resolved if resolved.is_relative_to(self.project_root) and resolved.is_file() else None

    @staticmethod
    def _optional_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = DashboardData._read_json(path)
            return payload if isinstance(payload, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    @contextmanager
    def _connect_read_only(path: Path) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            yield connection
        finally:
            connection.close()

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.project_root).as_posix()

    def diagnostic_cases(self) -> dict[str, Any]:
        """Versioned, read-only historical evidence, never a new validation run."""
        root = self.result_root / "convergence_diagnosis"
        profile_path = self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "acceptance_profile.json"
        paths = [root / "evidence.json", profile_path] + [
            root / name / filename for name in DIAGNOSTIC_CASES
            for filename in ("summary.json", "run_manifest.json", "members.csv", "member_metadata.json", "calibration_library.json")
        ]
        signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.is_file())
        if self._diagnostic_cache and self._diagnostic_cache[0] == signature:
            return self._diagnostic_cache[1]
        evidence = self._optional_json(root / "evidence.json")
        comparisons = evidence.get("member_comparison_at_negative_0_6_percent", [])
        threshold = self._optional_json(profile_path).get("tower_critical_force_relative")
        local_failures = [row for row in comparisons if isinstance(threshold, (int, float))
                          and math.isfinite(threshold) and threshold > 0
                          and abs(float(row["compression_magnitude_difference_percent"])) > threshold * 100]
        cases = []
        for name, label in DIAGNOSTIC_CASES.items():
            case_root = root / name
            summary = self._optional_json(case_root / "summary.json")
            manifest = self._optional_json(case_root / "run_manifest.json")
            original_quality = normalize_result_quality(manifest)
            if not summary:
                cases.append({"id": name, "label": label, "available": False,
                              "quality": original_quality, "missing": ["summary.json"]})
                continue
            # A new in-memory assessment is explicitly distinguished from the
            # unchanged historical manifest and points to its source artifacts.
            quality = ResultQuality(purpose="diagnostic", domain_policy="diagnostic_continue")
            quality.add_evidence("summary", self._relative(case_root / "summary.json"))
            quality.set_execution("completed" if summary.get("converged") else "nonconverged")
            quality.set_coverage(summary.get("requested_targets"), summary.get("completed_targets", 0))
            if name in {"baseline", "fine_sparse"} and local_failures:
                quality.add_evidence("local-comparison", self._relative(root / "evidence.json") + "#member_comparison_at_negative_0_6_percent")
                quality.add_evidence("acceptance-profile", self._relative(profile_path) + "#tower_critical_force_relative")
                failed_members = "_".join(str(row["element"]) for row in local_failures)
                quality.set_validation("failed", scope=["historical_four_segment_reference:negative_0.6_percent:members_" + failed_members],
                                       evidence_ids=["local-comparison", "acceptance-profile"], flags=["local_response_mismatch"])
            elif name == "elastic_877_878":
                quality.set_validation("unvalidated", flags=["diagnostic_material_substitution"])
            domain_checks = []
            required = [case_root / filename for filename in ("member_metadata.json", "calibration_library.json", "members.csv")]
            if name != "elastic_877_878" and all(path.is_file() for path in required):
                metadata = {int(row["original_element_tag"]): row for row in self._read_json(required[0])}
                groups = self._read_json(required[1]).get("groups", {})
                quality.add_evidence("member-domain", self._relative(required[1]))
                quality.add_evidence("accepted-history", self._relative(required[2]))
                limits: dict[int, float] = {}
                for member in (877, 878):
                    row = metadata.get(member, {})
                    envelope = groups.get(row.get("calibration_key"), {}).get("compression_envelope", [])
                    if envelope:
                        limits[member] = max(abs(float(point["strain"])) for point in envelope)
                        quality.register_domain(MemberDomainRange(member, "compression_strain_magnitude", 0.0, limits[member],
                                                                 ("member-domain",), "dimensionless"))
                maxima = {member: 0.0 for member in limits}
                with required[2].open(encoding="utf-8-sig", newline="") as stream:
                    for row in csv.DictReader(stream):
                        member = int(row["element"])
                        if member not in limits:
                            continue
                        strain = max(0.0, -float(row["strain"]))
                        maxima[member] = max(maxima[member], strain)
                        quality.observe_member_state(member, "compression_strain_magnitude", strain,
                                                     accepted_step=int(row["step"]), stage_id=row["stage"],
                                                     evidence_ids=["accepted-history"])
                domain_checks = [{"member": member, "maximum_compression_strain": maxima[member],
                                  "calibrated_compression_limit": limit} for member, limit in limits.items()]
                # This checks two members' compression bounds, not all members,
                # tension/cycle/boundary validity: do not close a whole-run audit.
            assessment = normalize_result_quality({"status": quality.to_dict()["execution_status"], "quality": quality.to_dict()})
            cases.append({"id": name, "label": label, "available": True, "summary": summary,
                          "quality": assessment, "historical_manifest_quality": original_quality,
                          "quality_origin": "read_only_derived_historical_evidence",
                          "domain_check_scope": "members_877_878_compression_bounds_only",
                          "domain_checks": domain_checks,
                          "source": self._relative(case_root / "summary.json"),
                          "engine_version": summary.get("opensees_version", "unknown"),
                          "has_full_force_database": False,
                          "has_nodal_displacement_history": False,
                          "diagnostic_only": True})
        payload = {"api_schema": API_SCHEMA, "cases": cases, "local_comparisons": comparisons,
                   "fine_step_diagnostics": evidence.get("fine_step_diagnostics", {}),
                   "interpretation": "计算完成、局部力学验证、标定范围、物理极限状态分别判断；Elastic消融仅用于查因。"}
        self._diagnostic_cache = (signature, payload)
        return payload

    def diagnostic_curve(self, case: str) -> dict[str, Any]:
        if case not in DIAGNOSTIC_CASES:
            raise ValueError("未知诊断案例")
        path = self.result_root / "convergence_diagnosis" / case / "history.csv"
        if not self._existing_file(path):
            raise FileNotFoundError("诊断曲线尚未生成")
        rows = self._read_csv(path)
        return {"case": case, "series": [{"x": float(row["u_m"]) * 1000,
                "y": float(row["base_shear_N"]) / 1000, "step": int(row["step"]),
                "stage": int(row["stage"])} for row in rows], "x_label": "塔顶相对位移 / mm",
                "y_label": "基底剪力 / kN", "state": "committed", "coordinate": "quasi_static_protocol"}

    def diagnostic_member(self, case: str, member: int) -> dict[str, Any]:
        if case not in DIAGNOSTIC_CASES or member not in {825, 828, 877, 878, 917, 920}:
            raise ValueError("仅支持白名单案例及关键杆825/828/877/878/917/920")
        root = self.result_root / "convergence_diagnosis" / case
        if not all(self._existing_file(root / name) for name in ("members.csv", "member_metadata.json")):
            raise FileNotFoundError("诊断关键杆历程尚未生成")
        metadata = next((row for row in self._read_json(root / "member_metadata.json")
                         if int(row["original_element_tag"]) == member), None)
        points = []
        with (root / "members.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if int(row["element"]) == member:
                    points.append({"step": int(row["step"]), "stage": int(row["stage"]),
                                   "strain": float(row["strain"]), "force_kn": float(row["force_N"]) / 1000,
                                   "axial_tangent_N": float(row["axial_tangent_N"])})
        evidence = self._optional_json(root.parent / "evidence.json")
        comparisons = [row for row in evidence.get("member_comparison_at_negative_0_6_percent", []) if int(row["element"]) == member]
        return {"case": case, "member": member, "metadata": metadata, "points": points,
                "same_stage_reference_checkpoints": comparisons if case in {"baseline", "fine_sparse"} else [],
                "reference_scope": "negative_0.6_percent_first_segment_axial_force_only",
                "tangent_definition": "dN/d_equivalent_strain, unit N; divide by member length for N/m",
                "available_channels": ["equivalent_strain", "axial_force", "axial_tangent"],
                "state": "committed", "deformation_animation_available": False}

    @staticmethod
    def _quality_summary(quality: dict[str, Any], manifest_source: str) -> dict[str, Any]:
        """Compact normalized conclusions; the unchanged manifest is authoritative.

        Never truncate quality flags. The first global domain event is retained
        in full. Per-member first events are a bounded, explicitly counted
        preview, so a widespread domain failure cannot turn this into another
        multi-megabyte endpoint.
        """
        fields = (
            "purpose", "domain_policy", "execution_status", "validation_status",
            "validation_scope", "validation_evidence_ids", "domain_status",
            "domain_audit_evidence_ids", "limit_state_status", "limit_state_evidence_ids",
            "limit_state_criteria_id", "limit_state_criteria_evidence_ids", "coverage",
            "quality_flags", "first_out_of_domain_event", "failure_reason", "eligible_for_fragility",
        )
        summary = {key: quality[key] for key in fields}
        first_members = quality.get("first_out_of_domain_by_member", {})
        ordered = sorted(first_members.items(), key=lambda item: (item[1].get("accepted_step", -1), str(item[0])))
        summary.update(
            schema=QUALITY_SUMMARY_SCHEMA,
            source_quality_schema=quality["schema"],
            authoritative_manifest=manifest_source,
            first_out_of_domain_by_member=dict(ordered[:FIRST_DOMAIN_PREVIEW_LIMIT]),
            first_out_of_domain_by_member_truncated=len(ordered) > FIRST_DOMAIN_PREVIEW_LIMIT,
            first_out_of_domain_preview_limit=FIRST_DOMAIN_PREVIEW_LIMIT,
            detail_counts={
                "member_domains": len(quality.get("member_domains", {})),
                "observed_domains": len(quality.get("observed_domains", [])),
                "domain_events": len(quality.get("events", [])),
                "first_out_of_domain_members": len(first_members),
                "evidence_items": len(quality.get("evidence", {})),
            },
        )
        return summary

    def followup_runs(self) -> dict[str, Any]:
        root = self.result_root / "followup"
        runs = []
        for path in sorted(root.glob("**/run_manifest.json")):
            if not self._existing_file(path):
                continue
            manifest = self._optional_json(path)
            source = self._relative(path)
            runs.append({"id": self._relative(path.parent), "manifest": self._relative(path),
                         "quality": self._quality_summary(normalize_result_quality(manifest), source),
                         "metrics": manifest.get("metrics", {}), "parameters": manifest.get("parameters", {})})
        return {"api_schema": API_SCHEMA, "runs": runs, "count": len(runs),
                "interpretation": "新followup仅传质量结论和首事件预览，原始run_manifest是完整权威证据；少量冒烟试验不等于全协议验证。"}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))

    def overview(self) -> dict[str, Any]:
        member = self._optional_json(self.result_root / "summary.json")
        tower = self._optional_json(self.cyclic_root / "summary.json")
        equivalent = tower.get("models", {}).get("equivalent", {})
        reference = tower.get("models", {}).get("segmented_reference", {})
        comparison = tower.get("comparison", {})
        papers = list(
            (self.project_root / "literature" / "transmission_tower_wind" / "papers").glob("*.pdf")
        )
        db_size = sum(
            path.stat().st_size for model in MODEL_KEYS
            if (path := self.cyclic_root / model / "tower_internal_forces.sqlite").is_file()
        )
        validation = member.get("actual_member_validation", [])
        calibrated = member.get("metrics", {}).get("equivalent_calibrated", {})
        member_info = member.get("member", {})
        timestamps = [path.stat().st_mtime for path in (self.result_root / "summary.json", self.cyclic_root / "summary.json") if path.is_file()]
        timestamps.extend(path.stat().st_mtime for path in (self.result_root / "convergence_diagnosis").glob("*/summary.json") if self._existing_file(path))
        timestamps.extend(path.stat().st_mtime for path in (self.result_root / "followup").glob("**/run_manifest.json") if self._existing_file(path))
        diagnostics = self.diagnostic_cases()
        versions = sorted({case["engine_version"] for case in diagnostics["cases"] if case.get("available")})
        common = comparison.get("common_target_count", 0)
        targets = tower.get("protocol", {}).get("target_drift_ratios", [])[:common]
        return {
            "api_schema": API_SCHEMA,
            "project": {
                "tower": "Z30103A6",
                "analysis_engine": ", ".join("OpenSees " + version for version in versions) if versions else "unknown",
                "engine_version_source": "historical diagnostic summary.opensees_version; Python package version not inferred",
                "paper_count": len(papers),
                "database_size_mb": db_size / 1024**2,
                "result_updated": max(timestamps, default=None),
            },
            "member": {
                "available": bool(member),
                "name": member_info.get("name", "unknown"),
                "length_m": member_info.get("length"),
                "slenderness": member_info.get("slenderness_ratio"),
                "peak_force_kn": calibrated.get("peak_force", 0) / 1000 if calibrated else None,
                "nrmse_percent": calibrated.get("normalized_rmse_percent"),
                "initial_stiffness_error_percent": calibrated.get("initial_stiffness_error_percent"),
                "pre_yield_unloading_passed": member.get("pre_yield_unloading", {}).get("passed"),
                "reference_divisions": member.get("experiment", {}).get("reference_divisions"),
                "actual_validation": validation,
                "screening": member.get("actual_member_screening", {}),
            },
            "tower": {
                "available": bool(tower),
                "physical_members": comparison.get("physical_member_count", 0),
                "calibration_groups": equivalent.get("calibration", {}).get("group_count"),
                "equivalent_elements": equivalent.get("element_count"),
                "reference_elements": reference.get("element_count"),
                "common_target_count": common,
                "requested_targets": equivalent.get("requested_targets"),
                "common_drift_percent": max((abs(float(value)) * 100 for value in targets), default=None),
                "comparison_scope": "historical_common_target_global_reaction_only_not_local_validation",
                "base_shear_error_percent": comparison.get("maximum_target_base_shear_error_percent"),
                "axial_correlation": comparison.get("axial_envelope_correlation"),
                "axial_nrmse_percent": comparison.get("axial_envelope_nrmse_percent_of_reference_max"),
                "equivalent_runtime_s": equivalent.get("runtime_seconds"),
                "reference_runtime_s": reference.get("runtime_seconds"),
                "speedup": None,
                "runtime_comparison_valid": False,
                "runtime_note": "历史模型完成目标数不同；未开展相同协议、冷/热缓存分离的公平性能评估。",
                "equivalent_converged": equivalent.get("converged"),
                "reference_converged": reference.get("converged"),
                "failed_target_drift_percent": (
                    equivalent["failed_target_drift_ratio"] * 100
                    if equivalent.get("failed_target_drift_ratio") is not None
                    else None
                ),
            },
            "diagnostics": diagnostics,
            "followup": self.followup_runs(),
        }

    def pushover(self) -> dict[str, Any]:
        rows = self._read_csv(self.result_root / "pushover_curves.csv")
        grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
        for row in rows:
            grouped[row["model"]].append(
                {
                    "x": float(row["shortening_m"]) * 1000,
                    "y": float(row["force_n"]) / 1000,
                }
            )
        return {"x_label": "轴向缩短 / mm", "y_label": "轴向压力 / kN", "series": grouped}

    def cyclic(self) -> dict[str, Any]:
        series: dict[str, list[dict[str, float]]] = {}
        for model in ("segmented_reference", "equivalent"):
            rows = self._read_csv(self.cyclic_root / model / "cyclic_history.csv")
            series[model] = [
                {
                    "x": float(row["relative_displacement"]) * 1000,
                    "y": float(row["base_shear"]) / 1000,
                    "step": int(row["step"]),
                    "drift_percent": float(row["drift_ratio"]) * 100,
                }
                for row in rows
            ]
        targets = self._read_csv(self.cyclic_root / "target_comparison.csv")
        return {
            "x_label": "塔顶相对位移 / mm",
            "y_label": "基底剪力 / kN",
            "series": series,
            "targets": [
                {
                    "stage": row["stage"],
                    "displacement_mm": float(row["target_displacement_m"]) * 1000,
                    "equivalent_kn": float(row["equivalent_base_shear_n"]) / 1000,
                    "reference_kn": float(row["reference_base_shear_n"]) / 1000,
                    "error_percent": float(row["error_percent"]),
                }
                for row in targets
            ],
        }

    @staticmethod
    def normalize_model(value: str | None) -> str:
        model = value or "equivalent"
        if model not in MODEL_KEYS:
            raise ValueError(f"未知模型: {model}")
        return model

    @staticmethod
    def normalize_component(value: str | None) -> str:
        component = value or "p"
        if component not in FORCE_COMPONENTS:
            raise ValueError(f"未知内力分量: {component}")
        return component

    def _database(self, model: str) -> Path:
        path = self.cyclic_root / self.normalize_model(model) / "tower_internal_forces.sqlite"
        if not self._existing_file(path):
            raise FileNotFoundError("所选历史模型的内力数据库尚未生成")
        return path

    def force_metadata(self, model: str) -> dict[str, Any]:
        model = self.normalize_model(model)
        with self._connect_read_only(self._database(model)) as connection:
            rows = connection.execute(
                "SELECT step, time FROM force_history GROUP BY step, time ORDER BY step"
            ).fetchall()
            element_count = connection.execute("SELECT COUNT(*) FROM elements").fetchone()[0]
        return {
            "model": model,
            "dataset": "historical_full_tower_cyclic",
            "coordinate": "quasi_static_record_progress_not_physical_seconds",
            "quality": normalize_result_quality(self._optional_json(self.cyclic_root / model / "run_manifest.json")),
            "times": [{"step": int(step), "time": float(time)} for step, time in rows],
            "recorded_steps": len(rows),
            "analysis_elements": element_count,
            "physical_members": len(self._physical_geometry()),
            "components": {
                "p": {"label": "轴力 P", "unit": "kN", "scale": 0.001},
                "vy": {"label": "剪力 Vy", "unit": "kN", "scale": 0.001},
                "vz": {"label": "剪力 Vz", "unit": "kN", "scale": 0.001},
                "t": {"label": "扭矩 T", "unit": "kN·m", "scale": 0.001},
                "my": {"label": "弯矩 My", "unit": "kN·m", "scale": 0.001},
                "mz": {"label": "弯矩 Mz", "unit": "kN·m", "scale": 0.001},
            },
        }

    def _physical_geometry(self) -> dict[int, dict[str, Any]]:
        if self._geometry_cache is not None:
            return self._geometry_cache
        data_root = self.cyclic_root / "equivalent" / "model_data"
        node_rows = self._read_csv(data_root / "nodes.csv")
        nodes = {
            int(row["node_tag"]): (float(row["x"]), float(row["y"]), float(row["z"]))
            for row in node_rows
        }
        geometry: dict[int, dict[str, Any]] = {}
        for row in self._read_csv(data_root / "elements.csv"):
            original = int(row["original_element_tag"])
            node_i = int(row["node_i"])
            node_j = int(row["node_j"])
            if node_i not in nodes or node_j not in nodes:
                continue
            geometry[original] = {
                "element": original,
                "frame": row["frame_name"],
                "section": row["section_name"],
                "node_i": node_i,
                "node_j": node_j,
                "a": nodes[node_i],
                "b": nodes[node_j],
            }
        self._geometry_cache = geometry
        return geometry

    @staticmethod
    def _robust_scale(values: list[float]) -> dict[str, float]:
        absolute = sorted(abs(value) for value in values if math.isfinite(value))
        if not absolute:
            return {"maximum": 0.0, "p98": 0.0}
        index = min(len(absolute) - 1, math.floor(0.98 * (len(absolute) - 1)))
        return {"maximum": absolute[-1], "p98": absolute[index]}

    def force_snapshot(self, model: str, requested_time: float, component: str) -> dict[str, Any]:
        model = self.normalize_model(model)
        component = self.normalize_component(component)
        database = self._database(model)
        if not math.isfinite(float(requested_time)):
            raise ValueError("查询进度必须是有限数")
        with self._connect_read_only(database) as connection:
            connection.row_factory = sqlite3.Row
            nearest = connection.execute(
                "SELECT time, step FROM force_history GROUP BY time, step "
                "ORDER BY ABS(time - ?) LIMIT 1",
                (float(requested_time),),
            ).fetchone()
            if nearest is None:
                raise ValueError("内力数据库没有记录。")
            rows = connection.execute(
                f"SELECT e.original_element_tag, e.section_name, h.{component}_i AS value_i, "
                f"h.{component}_j AS value_j FROM force_history h "
                "JOIN elements e USING(element_tag) WHERE h.time = ?",
                (nearest["time"],),
            ).fetchall()

        members: dict[int, dict[str, Any]] = {}
        for row in rows:
            original = int(row["original_element_tag"])
            value_i = float(row["value_i"] or 0.0)
            value_j = float(row["value_j"] or 0.0)
            candidate = value_i if abs(value_i) >= abs(value_j) else value_j
            current = members.get(original)
            if current is None or abs(candidate) > abs(current["value"]):
                members[original] = {
                    "value": candidate,
                    "value_i": value_i,
                    "value_j": value_j,
                }
        payload = self._attach_geometry(members)
        values = [record["value"] for record in payload]
        return {
            "mode": "snapshot",
            "dataset": "historical_full_tower_cyclic",
            "model": model,
            "component": component,
            "requested_time": float(requested_time),
            "actual_time": float(nearest["time"]),
            "step": int(nearest["step"]),
            "members": payload,
            "scale": self._robust_scale(values),
        }

    def force_envelope(
        self,
        model: str,
        component: str,
        start_time: float | None,
        end_time: float | None,
    ) -> dict[str, Any]:
        model = self.normalize_model(model)
        component = self.normalize_component(component)
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("起始时刻不能大于结束时刻。")
        if any(value is not None and not math.isfinite(float(value)) for value in (start_time, end_time)):
            raise ValueError("查询区间必须是有限数")
        clauses: list[str] = []
        parameters: list[float] = []
        if start_time is not None:
            clauses.append("h.time >= ?")
            parameters.append(float(start_time))
        if end_time is not None:
            clauses.append("h.time <= ?")
            parameters.append(float(end_time))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = (
            "SELECT e.original_element_tag, MAX(ABS(h."
            f"{component}_i)) AS abs_i, MAX(ABS(h.{component}_j)) AS abs_j, "
            "MIN(h.time) AS start_time, MAX(h.time) AS end_time "
            "FROM force_history h JOIN elements e USING(element_tag)"
            f"{where} GROUP BY e.original_element_tag"
        )
        with self._connect_read_only(self._database(model)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
        members = {
            int(row["original_element_tag"]): {
                "value": max(float(row["abs_i"] or 0.0), float(row["abs_j"] or 0.0)),
                "value_i": float(row["abs_i"] or 0.0),
                "value_j": float(row["abs_j"] or 0.0),
            }
            for row in rows
        }
        payload = self._attach_geometry(members)
        values = [record["value"] for record in payload]
        actual_start = min((float(row["start_time"]) for row in rows), default=None)
        actual_end = max((float(row["end_time"]) for row in rows), default=None)
        return {
            "mode": "envelope",
            "dataset": "historical_full_tower_cyclic",
            "model": model,
            "component": component,
            "requested_start": start_time,
            "requested_end": end_time,
            "actual_start": actual_start,
            "actual_end": actual_end,
            "members": payload,
            "scale": self._robust_scale(values),
        }

    def _attach_geometry(self, members: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        geometry = self._physical_geometry()
        result = []
        for element, force in members.items():
            shape = geometry.get(element)
            if shape is None:
                continue
            result.append({**shape, **force})
        return result

    def member_history(self, model: str, component: str, element: int) -> dict[str, Any]:
        model = self.normalize_model(model)
        component = self.normalize_component(component)
        if element not in self._physical_geometry():
            raise ValueError(f"物理杆件 {element} 不存在。")
        with self._connect_read_only(self._database(model)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT h.time, h.step, h.{component}_i AS value_i, h.{component}_j AS value_j "
                "FROM force_history h JOIN elements e USING(element_tag) "
                "WHERE e.original_element_tag = ? ORDER BY h.time, h.element_tag",
                (int(element),),
            ).fetchall()
        points: dict[float, dict[str, float | int]] = {}
        for row in rows:
            value_i = float(row["value_i"] or 0.0)
            value_j = float(row["value_j"] or 0.0)
            candidate = value_i if abs(value_i) >= abs(value_j) else value_j
            time = float(row["time"])
            current = points.get(time)
            if current is None or abs(candidate) > abs(float(current["value"])):
                points[time] = {
                    "x": time,
                    "y": candidate,
                    "step": int(row["step"]),
                    "value": candidate,
                }
        return {
            "model": model,
            "component": component,
            "element": element,
            "dataset": "historical_full_tower_cyclic",
            "coordinate": "quasi_static_record_progress_not_physical_seconds",
            "geometry": self._physical_geometry()[element],
            "points": list(points.values()),
        }

    def resources(self) -> dict[str, Any]:
        literature = self.project_root / "literature" / "transmission_tower_wind"
        papers = []
        for path in sorted((literature / "papers").glob("*.pdf")):
            papers.append(
                {
                    "key": f"paper:{path.name}",
                    "name": path.stem.replace("_", " "),
                    "size_mb": path.stat().st_size / 1024**2,
                }
            )
        reports = [
                {"key": "tmq-report", "name": "Tian–Ma–Qu 新材料：实施步骤与完整滞回结果", "type": "Markdown"},
                {"key": "tmq-sources", "name": "Tian–Ma–Qu 文献公式、参数与缺项核查", "type": "Markdown"},
                {"key": "tmq-readme", "name": "Tian–Ma–Qu 运行与测试说明", "type": "Markdown"},
                {"key": "material-report", "name": "等效初始缺陷材料详细报告", "type": "Markdown"},
                {"key": "tower-report", "name": "全塔往复试验报告", "type": "Markdown"},
                {"key": "literature-index", "name": "输电塔抗风文献索引", "type": "Markdown"},
                {"key": "conductor-params", "name": "输电线质量参数与定义", "type": "Markdown"},
                {"key": "graduation-scope", "name": "毕业工作量对照建议", "type": "Markdown"},
                {"key": "convergence-report", "name": "原卡点、细步长和局部失配诊断", "type": "Markdown"},
                {"key": "execution-plan", "name": "25项后续执行计划", "type": "Markdown"},
                {"key": "quality-report", "name": "T03质量状态实施步骤与结果", "type": "Markdown"},
                {"key": "mechanics-report", "name": "空间力学审计、边界重放与网格试验", "type": "Markdown"},
                {"key": "config-cache-report", "name": "T02配置、缓存版本与测试结果", "type": "Markdown"},
                {"key": "dashboard-report", "name": "T23网页实施步骤与验证结果", "type": "Markdown"},
                {"key": "browser-summary", "name": "真实Chromium网页检查结果", "type": "JSON"},
                {"key": "execution-log", "name": "本批实施记录", "type": "Markdown"},
                {"key": "decisions", "name": "研究路线与阶段门决策", "type": "Markdown"},
                {"key": "execution-results", "name": "本批全部步骤与最终结果总览", "type": "Markdown"},
                {"key": "full-reference-report", "name": "完整空间参考、局部真值与残差结果", "type": "Markdown"},
                {"key": "tower-solver-regression", "name": "全塔三种求解配置实际回归结果", "type": "Markdown"},
                {"key": "actual-calibration-report", "name": "T09实际杆两组标定与参考门控", "type": "Markdown"},
                {"key": "cyclic-protocol-preparation", "name": "T10循环训练/留出协议冻结与准备", "type": "Markdown"},
                {"key": "tower-regression-plot", "name": "四案例全塔曲线与验收边界总图", "type": "PNG"},
        ]
        return {"reports": [report for report in reports if self.downloadable(report["key"])], "papers": papers}

    def tmq_file(self, relative_path: str) -> Path | None:
        """Expose only published TMQ artifacts, never source/cache/arbitrary paths."""
        if relative_path not in TMQ_PUBLIC_FILES:
            return None
        candidate = self._existing_file(self.tmq_root / relative_path)
        return candidate if candidate and candidate.is_relative_to(self.tmq_root.resolve()) else None

    def tian_ma_qu(self) -> dict[str, Any]:
        b1_path=self.tmq_file(f"{TMQ_B1_ROOT}/summary.json")
        b1=self._read_json(b1_path) if b1_path else None
        if b1 is not None and b1.get("schema")!="otw2.tmq_b1_diagnostics.v1":
            raise ValueError("不支持的塔线首批诊断格式")
        modal_path=self.tmq_file(f"{TMQ_MODAL_ROOT}/summary.json")
        modal=self._read_json(modal_path) if modal_path else None
        if modal is not None and (modal.get("schema_version") != 1 or
                modal.get("analysis") != "single_tower_cable_gravity_modal_analysis"):
            raise ValueError("不支持的塔线模态结果格式")
        speed_path=self.tmq_file(f"{TMQ_WIND_SPEED_ROOT}/summary.json")
        speed=self._read_json(speed_path) if speed_path else None
        if speed is not None and (speed.get("schema_version") != 1 or
                speed.get("analysis") != "conditional_wind_speed_limit_exploration"):
            raise ValueError("不支持的等效风速探索格式")
        directional_path=self.tmq_file(f"{TMQ_DIRECTIONAL_ROOT}/summary.json")
        directional=self._read_json(directional_path) if directional_path else None
        if directional is not None and (directional.get("schema_version") != 1 or
                directional.get("analysis") != "directional_wind_single_tower_and_explicit_cables_verification"):
            raise ValueError("不支持的多风角加载验证格式")
        weakness_path = self.tmq_file("weakness_results/summary.json")
        weakness = self._read_json(weakness_path) if weakness_path else None
        if weakness is not None and (weakness.get("schema_version") != 1 or
                weakness.get("analysis") != "luo_inspired_quasi_static_weakness_screening"):
            raise ValueError("不支持的薄弱位置分析格式")
        tower_path = self.tmq_file("tower_results/publication.json")
        tower = self._read_json(tower_path) if tower_path else None
        if tower is not None and (tower.get("schema_version") != 1 or not isinstance(tower.get("run"), dict)):
            raise ValueError("不支持的 Tian–Ma–Qu 全塔发布格式")
        path = self.tmq_file("results/summary.json")
        if path is None:
            return {"available": False, "summary": None, "full_tower": tower, "weakness": weakness,
                    "directional_wind":directional,"wind_speed":speed,"modal_analysis":modal,"b1_diagnostics":b1,"reason": "Tian–Ma–Qu 单杆结果尚未生成"}
        summary = self._read_json(path)
        if summary.get("schema_version") != 1 or not isinstance(summary.get("cases"), list):
            raise ValueError("不支持的 Tian–Ma–Qu 结果格式")
        return {"available": True, "summary": summary, "source": self._relative(path),
                "full_tower": tower,
                "weakness": weakness,
                "directional_wind":directional,
                "wind_speed":speed,
                "modal_analysis":modal,
                "b1_diagnostics":b1,
                "viewer_url": "/tmq/results/index.html",
                "interpretation": "单杆与全塔结果分别呈现；已接入独立全塔试验，不等于角钢材料标定或全塔验证通过。"}

    def downloadable(self, key: str) -> Path | None:
        literature = self.project_root / "literature" / "transmission_tower_wind"
        tmq_downloads = {"tmq-report": "REPORT.md", "tmq-readme": "README.md",
                         "tmq-summary": "results/summary.json", "tmq-hysteresis": "results/full_hysteresis.pdf"}
        if key in tmq_downloads:
            return self.tmq_file(tmq_downloads[key])
        allowed = {
            "tmq-sources": literature / "tian_ma_qu_sources.md",
            "material-report": self.project_root / "initial_imperfection_material" / "REPORT.md",
            "tower-report": self.project_root
            / "initial_imperfection_material"
            / "FULL_TOWER_CYCLIC_REPORT.md",
            "literature-index": literature / "README.md",
            "conductor-params": literature / "conductor_mass_parameters.md",
            "graduation-scope": literature / "graduation_scope_benchmark.md",
            "single-summary": self.result_root / "summary.json",
            "tower-summary": self.cyclic_root / "summary.json",
            "target-comparison": self.cyclic_root / "target_comparison.csv",
            "axial-envelope": self.cyclic_root / "axial_force_envelope_comparison.csv",
            "convergence-report": self.project_root / "initial_imperfection_material" / "CONVERGENCE_DIAGNOSIS.md",
            "convergence-evidence": self.result_root / "convergence_diagnosis" / "evidence.json",
            "execution-plan": self.project_root / "docs" / "ai_execution_plan" / "PLAN.md",
            "quality-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "QUALITY.md",
            "mechanics-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "MECHANICS.md",
            "config-cache-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "CONFIG_CACHE.md",
            "dashboard-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "DASHBOARD_VALIDATION.md",
            "browser-summary": self.result_root / "followup" / "execution_20261022" / "dashboard_browser_v5" / "browser_result.json",
            "execution-log": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "execution_log.md",
            "decisions": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "decisions.md",
            "execution-results": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "RESULTS.md",
            "full-reference-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "FULL_REFERENCE.md",
            "tower-solver-regression": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "TOWER_SOLVER_REGRESSION.md",
            "actual-calibration-report": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "T09_ACTUAL_CALIBRATION.md",
            "cyclic-protocol-preparation": self.project_root / "docs" / "ai_execution_plan" / "execution_20261022" / "CYCLIC_PROTOCOL_PREPARATION.md",
            "tower-regression-plot": self.result_root / "followup" / "execution_20261022" / "tower_four_case_plot_v1" / "base_shear_displacement.png",
        }
        if key.startswith("paper:"):
            filename = key.removeprefix("paper:")
            if filename == Path(filename).name and filename.endswith(".pdf"):
                candidate = literature / "papers" / filename
                if self._existing_file(candidate):
                    return self._existing_file(candidate)
        path = allowed.get(key)
        return self._existing_file(path) if path else None

    def asset(self, key: str) -> Path | None:
        allowed = {
            "pushover": self.result_root / "pushover_comparison.png",
            "unloading": self.result_root / "pre_yield_unloading.png",
            "convergence": self.result_root / "convergence_study.png",
            "validation": self.result_root / "actual_member_validation.png",
            "sensitivity": self.result_root / "imperfection_sensitivity.png",
            "cyclic": self.cyclic_root / "base_shear_displacement.png",
            "axial-envelope": self.cyclic_root / "axial_force_envelope_comparison.png",
            "dashboard-desktop": self.result_root / "followup" / "execution_20261022" / "dashboard_browser_v5" / "desktop_diagnostics.png",
            "dashboard-mobile": self.result_root / "followup" / "execution_20261022" / "dashboard_browser_v5" / "mobile_diagnostics.png",
            "full-reference-local": self.result_root / "followup" / "execution_20261022" / "reference_full_truth_v1" / "local_reference_response.png",
            "tower-regression-plot": self.result_root / "followup" / "execution_20261022" / "tower_four_case_plot_v1" / "base_shear_displacement.png",
            "buckling-model": self.project_root / "static" / "2026_05_27" / "image.png",
            "imperfection-pushover": self.project_root
            / "static"
            / "2026_05_27"
            / "70d94026-5c1c-41d7-88b4-5114d519db5f.png",
            "imperfection-isdr": self.project_root
            / "static"
            / "2026_05_27"
            / "plot_reaction_drift.png",
            "line-formfinding": self.project_root
            / "static"
            / "2026_05_27"
            / "ae829b7d-85a1-4158-8ed9-5169b0aad105.png",
            "line-modes": self.project_root / "static" / "2026_05_27" / "modes_3x2.png",
            "fragility-drift": self.project_root
            / "static"
            / "2026_04_15"
            / "fragility_curve_drift.png",
            "fragility-node": self.project_root
            / "static"
            / "2026_04_15"
            / "fragility_curve_node_displacement.png",
        }
        path = allowed.get(key)
        return self._existing_file(path) if path else None


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "OTW2Dashboard/2.0"

    @property
    def data(self) -> DashboardData:
        return self.server.data  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}")

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        if isinstance(payload, dict):
            payload = {"api_schema": API_SCHEMA, **payload}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, *, download: bool = False) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        else:
            # Refresh application entry points after deployment, without asking
            # users to wait for an old HTML/JS version to expire.
            self.send_header("Cache-Control", "no-cache" if path.suffix in {".html", ".js", ".css", ".json"}
                             else "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _first(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
        values = query.get(key)
        return values[0] if values else default

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/index.html"}:
                self._send_file(STATIC_ROOT / "index.html")
                return
            if parsed.path.startswith("/static/"):
                name = parsed.path.removeprefix("/static/")
                if name not in {"styles.css", "app.js"}:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(STATIC_ROOT / name)
                return
            if parsed.path == "/health":
                self._send_json({"status": "ok", "service": "Z30103A6 results dashboard"})
                return
            if parsed.path == "/api/tian-ma-qu":
                self._send_json(self.data.tian_ma_qu())
                return
            if parsed.path in {"/tmq", "/tmq/"}:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/tmq/results/index.html")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if parsed.path.startswith("/tmq/"):
                artifact = self.data.tmq_file(parsed.path.removeprefix("/tmq/"))
                if artifact is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._send_file(artifact)
                return
            if parsed.path == "/api/overview":
                self._send_json(self.data.overview())
                return
            if parsed.path == "/api/pushover":
                self._send_json(self.data.pushover())
                return
            if parsed.path == "/api/cyclic":
                self._send_json(self.data.cyclic())
                return
            if parsed.path == "/api/resources":
                self._send_json(self.data.resources())
                return
            if parsed.path == "/api/diagnostics":
                self._send_json(self.data.diagnostic_cases())
                return
            if parsed.path == "/api/diagnostics/curve":
                self._send_json(self.data.diagnostic_curve(self._first(query, "case", "baseline") or "baseline"))
                return
            if parsed.path == "/api/diagnostics/member":
                self._send_json(self.data.diagnostic_member(self._first(query, "case", "baseline") or "baseline",
                                                           int(self._first(query, "member", "877") or "877")))
                return
            if parsed.path == "/api/followup":
                self._send_json(self.data.followup_runs())
                return
            if parsed.path == "/api/internal-force/meta":
                model = self.data.normalize_model(self._first(query, "model"))
                self._send_json(self.data.force_metadata(model))
                return
            if parsed.path == "/api/internal-force/snapshot":
                model = self.data.normalize_model(self._first(query, "model"))
                component = self.data.normalize_component(self._first(query, "component"))
                time = float(self._first(query, "time", "0") or 0)
                self._send_json(self.data.force_snapshot(model, time, component))
                return
            if parsed.path == "/api/internal-force/envelope":
                model = self.data.normalize_model(self._first(query, "model"))
                component = self.data.normalize_component(self._first(query, "component"))
                start = self._first(query, "start")
                end = self._first(query, "end")
                self._send_json(
                    self.data.force_envelope(
                        model,
                        component,
                        float(start) if start not in (None, "") else None,
                        float(end) if end not in (None, "") else None,
                    )
                )
                return
            if parsed.path == "/api/internal-force/history":
                model = self.data.normalize_model(self._first(query, "model"))
                component = self.data.normalize_component(self._first(query, "component"))
                element = int(self._first(query, "element", "0") or 0)
                self._send_json(self.data.member_history(model, component, element))
                return
            if parsed.path.startswith("/asset/"):
                asset = self.data.asset(parsed.path.removeprefix("/asset/"))
                if asset is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._send_file(asset)
                return
            if parsed.path == "/download":
                path = self.data.downloadable(self._first(query, "key", "") or "")
                if path is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._send_file(path, download=True)
                return
            if parsed.path.startswith("/api/"):
                self._send_json({"error": "未知API接口"}, HTTPStatus.NOT_FOUND)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, FileNotFoundError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # pragma: no cover - last-resort HTTP boundary
            self._send_json({"error": f"服务器读取结果失败: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def create_server(
    host: str = "0.0.0.0",
    port: int = 9999,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.data = DashboardData(project_root)  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Z30103A6 OpenSees 成果网页驾驶舱")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9999)
    arguments = parser.parse_args()
    server = create_server(arguments.host, arguments.port)
    print(f"Z30103A6 成果驾驶舱已启动: http://127.0.0.1:{arguments.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
