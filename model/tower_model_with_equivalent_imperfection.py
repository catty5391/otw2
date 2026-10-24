from __future__ import annotations

import math
import time
import uuid
from contextlib import nullcontext
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from initial_imperfection_material.calibration_cache import (
    CalibrationCache, CacheCorruptionError, CacheIdentityMismatch,
    ReferenceNonconvergence, publish_json_once,
)
from initial_imperfection_material.config import (
    AnalysisConfig, ReferenceSolverConfig, file_sha256, fingerprint,
    grouped_length, positive_finite, positive_integer,
)
from initial_imperfection_material.experiment import run_segmented_reference
from initial_imperfection_material.material import (
    BackbonePoint,
    EquivalentImperfectionMaterial,
    MemberProperties,
)

from .tower_model import OpenSeesModel
from .mechanical_profile import Steel02Parameters


class OpenSeesModelWithEquivalentImperfection(OpenSeesModel):
    """Full tower beams with member-level equivalent laws in the axial channel.

    One uniaxial material is registered for each physical member.  Calibration
    curves are shared only by members having the same section and binned length;
    the OpenSees material state itself is never shared between elements.
    """

    def __init__(
        self,
        *args: Any,
        imperfection_ratio: float = 1.0 / 1000.0,
        calibration_method: str = "reference",
        calibration_length_bin: float = 0.01,
        calibration_steps: int = 120,
        calibration_divisions: int = 16,
        calibration_cache: str | Path | None = None,
        allow_legacy_calibration_cache: bool = False,
        calibration_fallback_policy: str = "error",
        reference_solver_config: ReferenceSolverConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        positive_finite(imperfection_ratio, "imperfection_ratio")
        if calibration_method not in {"reference", "perry"}:
            raise ValueError("calibration_method 仅支持 reference 或 perry。")
        positive_finite(calibration_length_bin, "calibration_length_bin")
        positive_integer(calibration_steps, "calibration_steps")
        positive_integer(calibration_divisions, "calibration_divisions")
        if calibration_divisions < 2 or calibration_divisions % 2:
            raise ValueError("calibration_divisions must be an even integer >= 2")
        if calibration_fallback_policy not in {"error", "perry_exploratory"}:
            raise ValueError("unsupported calibration_fallback_policy")
        self.imperfection_ratio = float(imperfection_ratio)
        self.calibration_method = calibration_method
        self.calibration_length_bin = float(calibration_length_bin)
        self.calibration_steps = int(calibration_steps)
        self.calibration_divisions = int(calibration_divisions)
        self.calibration_cache = Path(calibration_cache) if calibration_cache else None
        self.allow_legacy_calibration_cache = bool(allow_legacy_calibration_cache)
        self.calibration_fallback_policy = calibration_fallback_policy
        # Historical paths keep their actual numerical settings explicitly;
        # new validation callers should pass ReferenceSolverConfig() instead.
        self.reference_solver_config = reference_solver_config or ReferenceSolverConfig.legacy()
        self.calibration_config: AnalysisConfig | None = None
        self.calibration_cache_info: dict[str, Any] = {}
        self.calibration_group_members: dict[str, list[dict[str, Any]]] = {}
        self.equivalent_materials: dict[int, EquivalentImperfectionMaterial] = {}
        self.calibration_library: dict[str, EquivalentImperfectionMaterial] = {}
        self.calibration_records: dict[str, dict[str, Any]] = {}

    def _length_group(self, length: float) -> float:
        return grouped_length(length, self.calibration_length_bin)

    def _calibration_key(self, section_name: str, length: float) -> str:
        return f"{section_name}|{self._length_group(length):.6f}"

    def _steel_properties(self) -> dict[str, dict[str, float]]:
        basics = {
            self._parse_key_values(line)["Material"]: self._parse_key_values(line)
            for line in self._table_lines("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")
        }
        result: dict[str, dict[str, float]] = {}
        for line in self._table_lines("MATERIAL PROPERTIES 03A - STEEL DATA"):
            steel = self._parse_key_values(line)
            name = steel["Material"]
            basic = basics[name]
            result[name] = {
                "elastic_modulus": float(basic["E1"]),
                "yield_strength": float(steel["Fy"]) * 1e6,
                "steel_hardening_ratio": self.steel01_b,
            }
        return result

    def _member_properties(
        self,
        section_name: str,
        length: float,
        section_properties: dict[str, dict[str, Any]],
        steel_properties: dict[str, dict[str, float]],
    ) -> MemberProperties:
        section = section_properties[section_name]
        material_name = str(section["material_name"])
        leg_width, thickness = self._l_section_dimensions(section_name)
        inertia_weak = min(
            float(section["i22"]) - abs(float(section["i23"])),
            float(section["i33"]) - abs(float(section["i23"])),
        )
        if inertia_weak <= 0.0:
            raise ValueError(f"{section_name} 的弱轴惯性矩无效: {inertia_weak}")
        return MemberProperties.from_equal_angle(
            name=f"{section_name}-L{length:.6f}",
            length=length,
            leg_width=leg_width,
            thickness=thickness,
            area=float(section["area"]),
            inertia_weak=inertia_weak,
            **steel_properties[material_name],
        )

    def _make_calibration_config(self, section_properties, steel_properties) -> AnalysisConfig:
        root = Path(__file__).resolve().parents[1]
        source_files = (
            "initial_imperfection_material/experiment.py",
            "initial_imperfection_material/material.py",
            "initial_imperfection_material/config.py",
            "initial_imperfection_material/calibration_cache.py",
            "model/mechanical_profile.py",
            "model/tower_model.py",
            "model/tower_model_with_equivalent_imperfection.py",
        )
        steel = {
            name: Steel02Parameters.legacy_member(
                E0=item["elastic_modulus"], fy=item["yield_strength"],
                b=item["steel_hardening_ratio"],
            ).as_dict()
            for name, item in steel_properties.items()
        }
        package_versions = {}
        for package in ("openseespy", "openseespylinux"):
            try:
                package_versions[package] = version(package)
            except PackageNotFoundError:
                package_versions[package] = None
        return AnalysisConfig(
            model={
                "family": "2d_pin_ended_dispBeamColumn_reference_v1",
                "source_s2k_sha256": file_sha256(self.s2k_path),
                "code_sha256": {name: file_sha256(root / name) for name in source_files},
                "engine_version": str(self.ops.version()),
                "package_versions": package_versions,
                "sections": section_properties, "group_members": self.calibration_group_members,
                "units": {"length": "m", "force": "N", "stress": "Pa"},
                "steel_profile": "baseline_legacy_member",
                "imperfection": {"shape": "half_sine", "ratio": self.imperfection_ratio,
                                 "direction": "weak_axis_plane", "seed": None},
                "discretization": {"divisions": self.calibration_divisions,
                                   "fiber_long_divisions": 30, "fiber_thickness_divisions": 3,
                                   "integration": "Legendre", "integration_points": 6},
                "tower_consumer": {"family": "dispBeamColumn_Aggregator_independent_P_My_Mz_T",
                                   "integration": "Legendre", "integration_points": 3,
                                   "coupled_I23_retained": False},
            }, steel=steel,
            boundary={"type": "pinned_pinned_2d", "rotations": "free",
                      "transverse_end_translations": "fixed", "history_sha256": None},
            protocol={"type": "monotonic_compression", "gravity": False,
                      "maximum_compressive_strain": 0.03, "steps": self.calibration_steps},
            solver=self.reference_solver_config.to_dict(),
            calibration={"method": self.calibration_method,
                         "fallback_policy": self.calibration_fallback_policy,
                         "length_bin": self.calibration_length_bin,
                         "length_rounding": "python_round_binary_float_half_even",
                         "sampling_algorithm": "EquivalentImperfectionMaterial.from_reference_curve.v1",
                         "reference_requires_full_convergence": True,
                         "training_protocol": "specified_monotonic_case",
                         "holdout_validation": "not_performed"},
        )

    def _load_calibration_cache(self) -> bool:
        if self.calibration_cache is None:
            return False
        assert self.calibration_config is not None
        data = CalibrationCache(self.calibration_cache,
                                allow_legacy=self.allow_legacy_calibration_cache).read(self.calibration_config)
        if data is None:
            return False
        if data["legacy"]:
            expected = {"imperfection_ratio": self.imperfection_ratio,
                        "length_bin": self.calibration_length_bin,
                        "steps": self.calibration_steps, "divisions": self.calibration_divisions,
                        "reference_requires_full_convergence": True}
            if any(data.get("settings", {}).get(key) != value for key, value in expected.items()):
                raise CacheIdentityMismatch("legacy settings differ; use a new cache path")
            methods = {item.get("calibration", {}).get("method") for item in data["groups"].values()}
            allowed = {"perry"} if self.calibration_method == "perry" else {"reference", "perry_fallback"}
            if not methods.issubset(allowed):
                raise CacheIdentityMismatch("legacy cache was produced by a different calibration method")
        self.calibration_cache_info.update(
            cache_hit=True, legacy=data["legacy"], file_sha256=data["file_sha256"],
            validation_status="legacy_unknown" if data["legacy"] else "unvalidated",
            actual_config_fingerprint=None if data["legacy"] else data["config_fingerprint"],
            dependency_verification="unavailable_legacy" if data["legacy"] else "full_v2_fingerprint",
        )
        for key, item in data.get("groups", {}).items():
            if key not in self.calibration_group_members:
                continue
            member = MemberProperties(**item["member"])
            for field in ("length", "area", "inertia_weak", "elastic_modulus", "yield_strength"):
                positive_finite(getattr(member, field), field)
            if not data["legacy"] and item.get("group_fingerprint") != fingerprint({
                "config": self.calibration_config.fingerprint, "member": item["member"],
            }):
                raise CacheCorruptionError(f"invalid member fingerprint: {key}")
            material = EquivalentImperfectionMaterial(
                member,
                [BackbonePoint(**point) for point in item["compression_envelope"]],
                source=item["source"],
                imperfection_ratio=item["imperfection_ratio"],
            )
            self.calibration_library[key] = material
            self.calibration_records[key] = dict(item["calibration"])
            if data["legacy"]:
                self.calibration_records[key]["validation_status"] = "legacy_unknown"
                self.calibration_records[key].setdefault("quality_flags", []).append("legacy_configuration_unverified")
        missing = set(self.calibration_group_members).difference(self.calibration_library)
        if missing:
            raise CacheCorruptionError(f"cache is missing required groups: {sorted(missing)}")
        return True

    def _write_calibration_cache(self) -> None:
        if self.calibration_cache is None:
            return
        assert self.calibration_config is not None
        groups: dict[str, Any] = {}
        for key, material in self.calibration_library.items():
            groups[key] = {
                "member": asdict(material.member),
                "compression_envelope": [
                    asdict(point) for point in material.compression_envelope
                ],
                "source": material.source,
                "imperfection_ratio": material.imperfection_ratio,
                "calibration": self.calibration_records[key],
                "actual_members": self.calibration_group_members[key],
                "group_fingerprint": fingerprint({"config": self.calibration_config.fingerprint,
                                                   "member": asdict(material.member)}),
            }
        CalibrationCache(self.calibration_cache).write(self.calibration_config, groups)
        self.calibration_cache_info["file_sha256"] = file_sha256(self.calibration_cache)

    def prepare_calibration_library(self) -> dict[str, EquivalentImperfectionMaterial]:
        """Calibrate every section/length group before the tower domain is built."""

        started = time.perf_counter()
        nodes = self._parse_node_coordinates()
        connectivity = self._parse_element_connectivity()
        assignments = self._element_section_assignments()
        section_properties = self._frame_section_properties()
        steel_properties = self._steel_properties()
        required: dict[str, tuple[str, float]] = {}
        self.calibration_group_members = {}
        for element_tag, item in connectivity.items():
            node_i = nodes[item["node_i"]]
            node_j = nodes[item["node_j"]]
            length = math.dist(
                (node_i["x"], node_i["y"], node_i["z"]),
                (node_j["x"], node_j["y"], node_j["z"]),
            )
            section_name = assignments[element_tag]["section_name"]
            grouped_length = self._length_group(length)
            required[self._calibration_key(section_name, length)] = (
                section_name,
                grouped_length,
            )
            self.calibration_group_members.setdefault(self._calibration_key(section_name, length), []).append({
                "original_member_id": element_tag, "actual_length": length,
                "representative_length": grouped_length,
                "length_error": grouped_length - length,
                "length_error_percent": 100 * (grouped_length - length) / length,
            })

        self.calibration_config = self._make_calibration_config(section_properties, steel_properties)
        self.calibration_cache_info = {
            "cache_hit": False, "legacy": False, "validation_status": "unvalidated",
            "config_fingerprint": self.calibration_config.fingerprint,
            "requested_config_fingerprint": self.calibration_config.fingerprint,
            "actual_config_fingerprint": self.calibration_config.fingerprint,
            "dependency_verification": "full_v2_fingerprint",
            "cache_path": str(self.calibration_cache) if self.calibration_cache else None,
            "cache_lookup_seconds": 0.0, "calibration_seconds": 0.0, "cache_write_seconds": 0.0,
        }
        lock = CalibrationCache(self.calibration_cache).locked() if self.calibration_cache else nullcontext()
        # Existing immutable files need no lock/write, including rejected v1 files.
        if self.calibration_cache and self.calibration_cache.exists():
            lock = nullcontext()
        with lock:
            self.calibration_library = {}
            self.calibration_records = {}
            lookup_started = time.perf_counter()
            hit = self._load_calibration_cache()
            self.calibration_cache_info["cache_lookup_seconds"] = time.perf_counter() - lookup_started
            if hit:
                self.calibration_cache_info["cache_mode"] = "warm_legacy" if self.calibration_cache_info["legacy"] else "warm_v2"
                self.calibration_cache_info["runtime_seconds"] = time.perf_counter() - started
                return self.calibration_library
            calibration_started = time.perf_counter()
            self._calibrate_required_groups(required, section_properties, steel_properties)
            self.calibration_cache_info["calibration_seconds"] = time.perf_counter() - calibration_started
            write_started = time.perf_counter()
            self._write_calibration_cache()
            self.calibration_cache_info["cache_write_seconds"] = time.perf_counter() - write_started
            self.calibration_cache_info["cache_mode"] = "cold_v2" if self.calibration_cache else "uncached"
        self.calibration_cache_info["runtime_seconds"] = time.perf_counter() - started
        return self.calibration_library

    def _calibrate_required_groups(self, required, section_properties, steel_properties) -> None:

        for key, (section_name, grouped_length) in sorted(required.items()):
            if key in self.calibration_library:
                continue
            member = self._member_properties(
                section_name,
                grouped_length,
                section_properties,
                steel_properties,
            )
            if self.calibration_method == "reference":
                try:
                    result = run_segmented_reference(
                        member,
                        imperfection_ratio=self.imperfection_ratio,
                        maximum_shortening=0.03 * member.length,
                        steps=self.calibration_steps,
                        divisions=self.calibration_divisions,
                        strict=False,
                        solver_config=self.reference_solver_config,
                    )
                    if not result.converged:
                        raise ReferenceNonconvergence(result)
                    material = EquivalentImperfectionMaterial.from_reference_curve(
                        member,
                        result.curve,
                        imperfection_ratio=self.imperfection_ratio,
                    )
                    record = {
                        "method": "reference",
                        "converged": result.converged,
                        "completed_steps": result.completed_steps,
                        "requested_steps": result.requested_steps,
                        "actual_end_shortening": result.actual_end_shortening,
                        "runtime_seconds": result.runtime_seconds,
                        "fallback_reason": "",
                    }
                except ReferenceNonconvergence as exc:
                    record = exc.as_record()
                    if self.calibration_cache is not None:
                        failure_path = self.calibration_cache.with_name(
                            f"{self.calibration_cache.name}.failed.{uuid.uuid4().hex}.json")
                        publish_json_once(failure_path, {
                            "format": "otw2.calibration_failure.v1", "status": "failed",
                            "group": key, "member": asdict(member), "failure": record,
                            "config": self.calibration_config.to_dict(),
                            "completed_groups": list(self.calibration_library),
                        })
                        record["failure_evidence"] = str(failure_path)
                    if self.calibration_fallback_policy != "perry_exploratory":
                        self.calibration_records[key] = record
                        raise
                    material = EquivalentImperfectionMaterial.from_perry(
                        member, imperfection_ratio=self.imperfection_ratio
                    )
                    record.update(method="perry_fallback",
                                  validation_status="unvalidated",
                                  quality_flags=["exploratory_perry_fallback", "reference_nonconvergence"])
            else:
                material = EquivalentImperfectionMaterial.from_perry(
                    member, imperfection_ratio=self.imperfection_ratio
                )
                record = {
                    "method": "perry",
                    "converged": True,
                    "completed_steps": 0,
                    "requested_steps": 0,
                    "actual_end_shortening": 0.0,
                    "runtime_seconds": 0.0,
                    "fallback_reason": "",
                }
            self.calibration_library[key] = material
            record.setdefault("validation_status", "unvalidated")
            record.setdefault("quality_flags", [] if self.calibration_method == "reference" else ["analytical_perry_trial"])
            if self.reference_solver_config.relaxes_tolerance:
                record["quality_flags"].append("legacy_retry_tolerance_relaxed")
            self.calibration_records[key] = record

    def element(self) -> dict[int, dict[str, Any]]:
        if not self.calibration_library:
            raise RuntimeError("必须先调用 prepare_calibration_library()。")
        connectivity = self._parse_element_connectivity()
        assignments = self._element_section_assignments()
        section_properties = self._frame_section_properties()
        rows: list[dict[str, Any]] = []
        material_rows: list[dict[str, Any]] = []
        self.element_map = {}
        self.material_tag_map = {}
        self.section_tag_map = {}
        self.transf_map = {}
        self.integration_map = {}
        self.equivalent_materials = {}

        for element_tag, item in sorted(connectivity.items()):
            node_i = self.node_map[item["node_i"]]
            node_j = self.node_map[item["node_j"]]
            length = math.dist(
                (node_i["x"], node_i["y"], node_i["z"]),
                (node_j["x"], node_j["y"], node_j["z"]),
            )
            section_name = assignments[element_tag]["section_name"]
            section = section_properties[section_name]
            material = self.calibration_library[
                self._calibration_key(section_name, length)
            ]
            material_tag = self.tag_manager.get_next_tag(namespace="material")
            material.register_opensees(
                self.ops,
                material_tag,
                response_mode="reversible",
                # Aggregator 的 P 通道是轴力—轴向应变，而材料原型保存的是
                # 应力—应变，因此必须在这里乘截面面积。
                stress_scale=float(section["area"]),
            )

            elastic_modulus = material.member.elastic_modulus
            shear_modulus = elastic_modulus / (2.0 * (1.0 + 0.3))
            mz_material_tag = self.tag_manager.get_next_tag(namespace="material")
            my_material_tag = self.tag_manager.get_next_tag(namespace="material")
            torsion_material_tag = self.tag_manager.get_next_tag(namespace="material")
            self.ops.uniaxialMaterial(
                "Elastic", mz_material_tag, elastic_modulus * float(section["i33"])
            )
            self.ops.uniaxialMaterial(
                "Elastic", my_material_tag, elastic_modulus * float(section["i22"])
            )
            self.ops.uniaxialMaterial(
                "Elastic", torsion_material_tag, shear_modulus * float(section["tors_const"])
            )
            section_tag = self.tag_manager.get_next_tag(namespace="section")
            self.ops.section(
                "Aggregator",
                section_tag,
                material_tag,
                "P",
                mz_material_tag,
                "Mz",
                my_material_tag,
                "My",
                torsion_material_tag,
                "T",
            )
            vec_x, vec_y, vec_z = self._geom_transf_vector(node_i, node_j)
            transf_tag = self.tag_manager.get_next_tag(namespace="transf")
            self.ops.geomTransf("Corotational", transf_tag, vec_x, vec_y, vec_z)
            integration_tag = self.tag_manager.get_next_tag(namespace="integration")
            self.ops.beamIntegration("Legendre", integration_tag, section_tag, 3)
            self.ops.element(
                "dispBeamColumn",
                element_tag,
                item["node_i"],
                item["node_j"],
                transf_tag,
                integration_tag,
            )
            record = {
                "tower_id": self.tower_id,
                "element_tag": element_tag,
                "local_element_tag": item.get("local_element_tag"),
                "original_element_tag": element_tag,
                "frame_name": item.get("frame_name", ""),
                "node_i": item["node_i"],
                "node_j": item["node_j"],
                "section_name": section_name,
                "material_name": section["material_name"],
                "mat_tag": material_tag,
                "section_tag": section_tag,
                "transf_tag": transf_tag,
                "integration_tag": integration_tag,
                "integration_type": "Legendre",
                "num_intgr_pts": 3,
                "length": length,
                "area": float(section["area"]),
                "ops_type": "dispBeamColumn-equivalent-axial",
                "calibration_key": self._calibration_key(section_name, length),
            }
            self.element_map[element_tag] = record
            self.section_tag_map[section_tag] = {
                "section_tag": section_tag,
                "element_tag": element_tag,
                "section_name": section_name,
                "axial_mat_tag": material_tag,
                "mz_mat_tag": mz_material_tag,
                "my_mat_tag": my_material_tag,
                "torsion_mat_tag": torsion_material_tag,
            }
            self.transf_map[element_tag] = {
                "transf_tag": transf_tag,
                "element_tag": element_tag,
                "vec_x": vec_x,
                "vec_y": vec_y,
                "vec_z": vec_z,
            }
            self.integration_map[integration_tag] = {
                "integration_tag": integration_tag,
                "element_tag": element_tag,
                "section_tag": section_tag,
                "integration_type": "Legendre",
                "num_intgr_pts": 3,
            }
            self.equivalent_materials[element_tag] = material
            rows.append(record)
            material_record = {
                "mat_tag": material_tag,
                "element_tag": element_tag,
                "section_name": section_name,
                "length": length,
                "calibration_key": record["calibration_key"],
                "source": material.source,
                "peak_compressive_load": material.peak_compressive_load,
            }
            self.material_tag_map[material_tag] = material_record
            material_rows.append(material_record)

        self._write_csv(self.output_dir / "elements.csv", rows, list(rows[0]))
        self._write_csv(
            self.output_dir / "equivalent_materials.csv",
            material_rows,
            list(material_rows[0]),
        )
        return self.element_map

    def model_tower(self) -> dict[str, Any]:
        self.prepare_calibration_library()
        self.node()
        self.fix()
        self.mass()
        self.element()
        return {
            "nodes": self.node_map,
            "fixes": self.fix_map,
            "masses": self.mass_map,
            "materials": self.material_tag_map,
            "sections": self.section_tag_map,
            "geomtransf": self.transf_map,
            "integrations": self.integration_map,
            "elements": self.element_map,
            "calibration_groups": self.calibration_records,
            "tower_id": self.tower_id,
            "tag_summary": self.tag_manager.summary(),
        }
