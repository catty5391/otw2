"""Gate-controlled offline reconstruction for two actual L40x3 Q235 groups.

No FE analysis is launched. Import independently generated, zero-load monotonic
3D reference curves only after scoped G1 evidence exists. A legal v2 *subset*
cache is not a validated 194-group tower library. Missing evidence keeps the
member segmented and remains recoverable when evidence becomes available.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .calibration_cache import CalibrationCache, CacheWriteConflict, publish_json_once
from .config import AnalysisConfig, ReferenceSolverConfig, file_sha256, fingerprint
from .material import BackbonePoint, EquivalentImperfectionMaterial, MemberProperties, PushoverPoint

GATE_SCHEMA = "otw2.actual_member_calibration_gate.v1"
REFERENCE_SCHEMA = "otw2.actual_member_monotonic_reference.v1"
TARGETS = {877: ("L40x3Q235", .85), 825: ("L40x3Q235", 1.95)}
G1_CHECKS = ("same_mesh_replay", "mesh_convergence", "step_convergence", "fiber_convergence")
BOUNDARIES = {"spatial_pinned", "spatial_clamped", "spatial_rotational_springs", "spatial_recorded_6dof"}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite JSON: {value}")))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _evidence(record: Mapping[str, Any], base: Path) -> dict[str, Any]:
    path = Path(record["path"])
    path = path if path.is_absolute() else base / path
    actual = file_sha256(path)
    if actual != record.get("sha256"):
        raise ValueError(f"evidence fingerprint mismatch: {path}")
    return {"path": str(path.resolve()), "sha256": actual}


def reference_identity(member: Mapping[str, Any], *, source_sha256: str, boundary: Mapping[str, Any],
                       imperfection_vector: list[float], solver: ReferenceSolverConfig,
                       maximum_strain: float) -> str:
    """Bind geometry, full steel/profile, source, boundary, solver and range."""
    return fingerprint({"schema": REFERENCE_SCHEMA, "member": dict(member), "source_sha256": source_sha256,
                        "boundary": dict(boundary), "imperfection_vector": imperfection_vector,
                        "solver": solver.to_dict(), "maximum_strain": maximum_strain})


def _properties(member: Mapping[str, Any]) -> MemberProperties:
    section, steel = member["section"], member["steel_tower"]
    # Only the two equal-angle groups are accepted, so the analytical weak
    # principal inertia is I22-|I23|. The full coupling remains in identity.
    width, thickness = .04, .003
    return MemberProperties.from_equal_angle(name=f'L40x3Q235-L{member["length"]:.6f}',
        length=float(member["length"]), leg_width=width, thickness=thickness,
        area=float(section["area"]), inertia_weak=min(float(section["i22"]),float(section["i33"]))-abs(float(section["i23"])),
        elastic_modulus=float(steel["E0"]), yield_strength=float(steel["fy"]), steel_hardening_ratio=float(steel["b"]))


def _group_key(member: Mapping[str, Any]) -> str:
    return f'{member["section"]["section_name"]}|{member["length"]:.6f}'


def _unsupported(reason: str) -> dict[str, Any]:
    return {"status": "unsupported", "reason": reason, "retained_representation": "segmented",
            "recoverable_with_additional_evidence": True,
            "independent_validation": {"status": "not_performed", "reason": "no_accepted_candidate"}}


def _bound_identifiability(gate: Mapping[str, Any], member: Mapping[str, Any], reference: Mapping[str, Any],
                           reference_hash: str, base: Path, maximum_strain: float) -> tuple[str | None, dict[str, Any]]:
    """Verify evidence bindings, not merely a scalar-identifiable boolean.

    The scientific interpretation still requires an upstream reviewed evidence
    package. Hash/scope checks cannot prove a document's mechanical conclusion.
    """
    scope = gate.get("scope", {})
    expected = {"member_id":member["member_id"], "steel_fingerprint":fingerprint(member["steel_tower"]),
                "boundary_fingerprint":fingerprint(reference["boundary"]),
                "reference_configuration_fingerprint":reference["configuration_fingerprint"],
                "reference_sha256":reference_hash, "loading":"zero_load_monotonic_compression"}
    if any(scope.get(key) != value for key,value in expected.items()):
        return "identifiability_scope_missing_or_mismatched", {}
    if float(scope.get("maximum_compression_strain", 0.)) < maximum_strain:
        return "identifiability_scope_does_not_cover_requested_range", {}
    required = {"spatial_reference", "mesh_step_fiber_verified", "scalar_axial_identifiability"}
    if not required <= set(scope.get("validation_kinds", ())):
        return "identifiability_scope_lacks_required_validation_kinds", {}
    source = gate.get("source_run")
    evidence = gate.get("evidence")
    if not source or not evidence or not isinstance(evidence,list):
        return "identifiability_missing_source_run_or_evidence", {}
    source_record = _evidence(source,base)
    if scope.get("source_run_sha256") != source_record["sha256"]:
        return "identifiability_scope_not_bound_to_source_run_hash", {"source_run":source_record}
    source_run = _read_json(Path(source_record["path"]))
    if source_run.get("status") != "completed":
        return "identifiability_source_run_not_completed", {"source_run":source_record}
    records = [_evidence(item,base) for item in evidence]
    ident = gate.get("identifiability", {})
    spread = ident.get("maximum_conditional_force_spread_relative")
    if ident.get("status") != "supported":
        return "scalar_axial_identifiability_not_supported_in_declared_scope", {"source_run":source_record,"evidence":records}
    if (isinstance(ident.get("independent_boundary_cases"),bool) or
            not isinstance(ident.get("independent_boundary_cases"),int) or ident["independent_boundary_cases"] < 2 or
            spread is None or not math.isfinite(float(spread)) or not 0 <= float(spread) <= .05):
        return "identifiability_quantitative_evidence_missing_or_exceeds_5percent_prefilter", {"source_run":source_record,"evidence":records}
    return None, {"scope":dict(scope),"source_run":source_record,"evidence":records,
                  "identifiability":dict(ident),"scientific_review":"upstream_evidence_required_not_proved_by_boolean"}


def _curve(reference: Mapping[str, Any]) -> list[PushoverPoint]:
    points = []
    for row in reference.get("curve", ()):
        if row.get("committed") is not True:
            raise ValueError("reference curve may contain accepted committed states only")
        point = PushoverPoint(float(row["shortening_m"]),float(row["compression_force_N"]))
        if not math.isfinite(point.shortening) or not math.isfinite(point.force):
            raise ValueError("nonfinite reference curve")
        if points and point.shortening <= points[-1].shortening:
            raise ValueError("reference shortening must increase strictly; cyclic replay is not a monotonic backbone")
        points.append(point)
    return points


def _envelope_curve(material: EquivalentImperfectionMaterial) -> ResponseCurve:
    from util.postprocess.response_metrics import ResponseCurve
    points = [(0.,0.)] + [(-p.strain*material.member.length,-p.stress*material.member.area)
                           for p in material.compression_envelope]
    return ResponseCurve.from_pairs(points)


def _compare_old(old: Mapping[str, Any] | None, key: str, member: MemberProperties,
                 reference: ResponseCurve) -> tuple[dict[str, Any], ResponseCurve | None]:
    if old is None or key not in old.get("groups", {}):
        return {"status":"missing_old_group","comparison_only":True},None
    group = old["groups"][key]
    old_member = MemberProperties(**group["member"])
    if not math.isclose(old_member.length,member.length,rel_tol=0,abs_tol=1e-9):
        return {"status":"old_group_length_mismatch","comparison_only":True},None
    material = EquivalentImperfectionMaterial(old_member,[BackbonePoint(**row) for row in group["compression_envelope"]],
                source=group.get("source","legacy_unknown"),imperfection_ratio=group.get("imperfection_ratio"))
    curve = _envelope_curve(material)
    from util.postprocess.response_metrics import compare_curves
    try:
        metrics = compare_curves(reference,curve)
    except ValueError:
        return {"status":"no_common_coverage","comparison_only":True},curve
    return {"status":"compared","comparison_only":True,"legacy_validation_status":"legacy_unknown",
            "source":group.get("source","unknown"),"metrics":metrics},curve


def calibrate_batch(source: str | Path, gate_path: str | Path, references: Mapping[int,str | Path],
                    output: str | Path, *, maximum_strain: float = .03,
                    solver: ReferenceSolverConfig | None = None, old_cache: str | Path | None = None,
                    make_plots: bool = True, allow_range_extension: bool = False,
                    member_records: Mapping[int,Mapping[str,Any]] | None = None) -> dict[str, Any]:
    """Create only accepted subset groups; preserve all blocked/partial outcomes.

    ``member_records`` injects an exported catalog for fast deterministic unit
    tests; the CLI always uses the real S2K MechanicalCatalog. No built-in path
    launches reference FE, a tower calibration sweep, or a Perry fallback.
    """
    source,gate_path,output = Path(source),Path(gate_path),Path(output)
    settings = solver or ReferenceSolverConfig()
    if settings.relaxes_tolerance:
        raise ValueError("T09 requires the same convergence tolerance for primary and retry algorithms")
    if not math.isfinite(maximum_strain) or maximum_strain <= 0:
        raise ValueError("maximum_strain must be finite and positive")
    if maximum_strain > .03 and not allow_range_extension:
        raise ValueError("range beyond 3% needs explicit extension plus covering reference/evidence")
    if set(references) != set(TARGETS):
        raise ValueError("provide exactly the 877/.85m and 825/1.95m reference inputs")
    if output.exists():
        raise CacheWriteConflict(f"choose a new batch output directory: {output}")
    output.mkdir(parents=True)
    gate = _read_json(gate_path)
    source_hash = file_sha256(source)
    summary: dict[str,Any] = {"schema":"otw2.actual_member_calibration_batch.v1","source_sha256":source_hash,
        "gate_file":{"path":str(gate_path.resolve()),"sha256":file_sha256(gate_path)},
        "maximum_compression_strain":maximum_strain,"solver":settings.to_dict(),"groups":{},
        "validation_status":"unvalidated","independent_validation_status":"not_performed",
        "curve_area_semantics":"scalar_axial_curve_area_not_total_3D_work_or_hysteretic_dissipation",
        "fallback_policy":"error_no_perry","library_role":"two_group_subset_not_tower_drop_in",
        "requires_full_tower_revalidation":True}
    try:
        if gate.get("schema") != GATE_SCHEMA:
            raise ValueError("unknown gate evidence schema")
        if gate.get("source_sha256") != source_hash:
            raise ValueError("gate evidence belongs to a different source model")
        if maximum_strain > .03 and not str(gate.get("range_extension_justification", "")).strip():
            raise ValueError("range extension requires an explicit study justification in the gate evidence")
        if gate.get("gate") != "G1" or gate.get("status") != "passed":
            summary.update(status="blocked",reason="G1_not_passed")
            summary["groups"]={str(tag):{"status":"blocked","reason":"G1_not_passed",
                                        "retained_representation":"segmented","recoverable_with_additional_evidence":True}
                               for tag in TARGETS}
            publish_json_once(output/"summary.json",summary)
            return summary
        checked = {}
        for name in G1_CHECKS:
            item=gate.get("checks",{}).get(name,{})
            if item.get("passed") is not True or not item.get("evidence"):
                summary.update(status="blocked",reason=f"G1_missing_{name}_evidence")
                summary["groups"]={str(tag):{"status":"blocked","reason":summary["reason"],
                    "retained_representation":"segmented","recoverable_with_additional_evidence":True} for tag in TARGETS}
                publish_json_once(output/"summary.json",summary)
                return summary
            checked[name]=[_evidence(record,gate_path.parent) for record in item["evidence"]]
        summary["G1_evidence"]=checked
        if member_records is None:
            from model.mechanical_profile import MechanicalCatalog,MechanicalProfile
            catalog=MechanicalCatalog(source,output_dir=output/"catalog",profile=MechanicalProfile(**gate["mechanical_profile"]))
            members={tag:catalog.member(tag) for tag in TARGETS}
        else:
            members={tag:dict(member_records[tag]) for tag in TARGETS}
        old=None
        if old_cache is not None:
            old=_read_json(Path(old_cache))
            if old.get("format") not in {"otw2.equivalent_imperfection_library.v1","otw2.equivalent_imperfection_library.v2"}:
                raise ValueError("unknown old cache schema; comparison does not authorize migration")
            summary["old_cache"]={"path":str(Path(old_cache).resolve()),"sha256":file_sha256(old_cache),"read_only":True}
        groups,plot_data,reference_records={},{},{}
        for tag,(section_name,length) in TARGETS.items():
            member=members[tag]
            if member.get("member_id")!=tag or member["section"]["section_name"]!=section_name or not math.isclose(member["length"],length,rel_tol=0,abs_tol=1e-8):
                raise ValueError(f"source member {tag} is outside the frozen two-group batch")
            if member.get("profile") != gate.get("mechanical_profile"):
                raise ValueError("member mechanical profile differs from G1 evidence")
            path=Path(references[tag])
            if not path.is_file():
                summary["groups"][str(tag)]=_unsupported("reference_input_not_available")
                continue
            reference=_read_json(path); ref_hash=file_sha256(path)
            if reference.get("schema")!=REFERENCE_SCHEMA or reference.get("member_id")!=tag or reference.get("source_sha256")!=source_hash:
                raise ValueError(f"reference identity mismatch for {tag}")
            reference_records[str(tag)]={"path":str(path.resolve()),"sha256":ref_hash,
                                         "engine_version":reference.get("engine_version","unknown")}
            boundary=reference.get("boundary",{})
            if reference.get("dimension")!=3 or boundary.get("type") not in BOUNDARIES:
                summary["groups"][str(tag)]=_unsupported("reference_is_not_an_explicit_spatial_boundary_case")
                continue
            if (not str(boundary.get("description", "")).strip() or
                    boundary.get("coordinate_frame") not in {"original_member_local", "global"}):
                summary["groups"][str(tag)]=_unsupported("boundary_description_or_coordinate_frame_missing")
                continue
            if reference.get("origin_convention")!="zero_load_zero_end_shortening":
                summary["groups"][str(tag)]=_unsupported("prestressed_or_unknown_origin_requires_stateful_reference")
                continue
            if (reference.get("force_convention")!="original_member_chord_compression_positive" or
                    reference.get("shortening_convention")!="end_chord_shortening_positive"):
                summary["groups"][str(tag)]=_unsupported("reference_force_or_shortening_convention_missing")
                continue
            if (reference.get("steel")!=member["steel_tower"] or reference.get("mechanical_profile")!=member["profile"] or
                    not reference.get("engine_version") or reference.get("engine_version")=="unknown"):
                summary["groups"][str(tag)]=_unsupported("reference_material_profile_or_engine_binding_missing")
                continue
            vector=reference.get("imperfection_vector")
            if not isinstance(vector,list) or len(vector)!=3 or not all(math.isfinite(float(v)) for v in vector):
                raise ValueError("reference imperfection vector must have three finite global components")
            chord=[float(right)-float(left) for left,right in zip(*member["coordinates"])]
            if abs(math.fsum(float(v)*axis for v,axis in zip(vector,chord))) > 1e-10*float(member["length"]):
                raise ValueError("reference imperfection must be transverse to the physical member chord")
            expected=reference_identity(member,source_sha256=source_hash,boundary=boundary,
                    imperfection_vector=vector,solver=settings,maximum_strain=maximum_strain)
            if reference.get("configuration_fingerprint")!=expected or reference.get("solver")!=settings.to_dict():
                raise ValueError(f"full reference configuration/solver mismatch for {tag}")
            reason,evidence=_bound_identifiability(gate.get("groups",{}).get(str(tag),{}),member,reference,
                                                  ref_hash,gate_path.parent,maximum_strain)
            if reason:
                summary["groups"][str(tag)]={**_unsupported(reason),"bound_evidence":evidence}
                continue
            points=_curve(reference)
            if not points:
                summary["groups"][str(tag)]=_unsupported("reference_contains_no_accepted_states")
                continue
            requested=float(reference["requested_end_shortening_m"])
            actual=float(reference["actual_end_shortening_m"])
            completed,steps=reference["completed_steps"],reference["requested_steps"]
            if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in (completed,steps)) or steps<1 or completed>steps:
                raise ValueError("invalid reference completion counts")
            if reference.get("all_committed_states_included") is not True or len(points)!=completed+1:
                summary["groups"][str(tag)]=_unsupported("reference_export_does_not_include_every_committed_state")
                continue
            if not math.isfinite(actual) or not math.isfinite(requested) or actual<0 or requested<=0:
                raise ValueError("reference endpoints must be finite with nonnegative actual and positive requested shortening")
            if not math.isclose(requested,maximum_strain*length,rel_tol=1e-10,abs_tol=1e-12) or not math.isclose(actual,points[-1].shortening,rel_tol=1e-10,abs_tol=1e-12):
                raise ValueError("reference requested/actual endpoint conflicts with curve or declared range")
            coverage=min(100.,100.*actual/requested)
            details={"requested_steps":steps,"completed_steps":completed,"requested_end_shortening_m":requested,
                     "actual_end_shortening_m":actual,"coverage_percent":coverage,"reference":reference_records[str(tag)],
                     "bound_evidence":evidence}
            plot_data[tag]={"reference":points}
            with (output/f"reference_{tag}.csv").open("x",newline="",encoding="utf-8") as stream:
                writer=csv.writer(stream);writer.writerow(("shortening_m","compression_force_N"))
                writer.writerows((p.shortening,p.force) for p in points)
            if reference.get("execution_status")!="completed" or completed!=steps or not math.isclose(actual,requested,rel_tol=1e-10,abs_tol=1e-12):
                summary["groups"][str(tag)]={**_unsupported("reference_incomplete_no_full_range_backbone"),
                                            **details,"status":"partial_reference"}
                continue
            if len(points)<4 or abs(points[0].shortening)>1e-12 or abs(points[0].force)>1e-6 or any(p.shortening<=0 or p.force<=0 for p in points[1:]):
                summary["groups"][str(tag)]={**_unsupported("reference_not_a_zero_origin_positive_compression_curve"),**details}
                continue
            properties=_properties(member)
            ratio=math.sqrt(math.fsum(float(v)**2 for v in vector))/properties.length
            if ratio<=0:
                summary["groups"][str(tag)]={**_unsupported("zero_imperfection_not_the_requested_buckling_reference"),**details}
                continue
            material=EquivalentImperfectionMaterial.from_reference_curve(properties,points,imperfection_ratio=ratio)
            from util.postprocess.response_metrics import ResponseCurve,compare_curves
            refcurve=ResponseCurve.from_pairs((p.shortening,p.force) for p in points)
            fitted=_envelope_curve(material); metrics=compare_curves(refcurve,fitted)
            peak=max(p.force for p in points)
            peak_index=max(range(len(points)),key=lambda index:points[index].force)
            peak_bracket=[points[max(0,peak_index-1)].shortening,points[min(len(points)-1,peak_index+1)].shortening]
            peak_error=100.*(max(fitted.y)-peak)/peak
            reconstruction={"status":"training_reconstruction_only","peak_sample_is_inserted":True,
                            "peak_error_percent":peak_error,**metrics}
            reconstruction["peak_neighbor_bracket_m"]=peak_bracket
            old_comparison,old_curve=_compare_old(old,_group_key(member),properties,refcurve)
            plot_data[tag].update(fitted=fitted,old=old_curve)
            if abs(peak_error)>3. or metrics["domain_weighted_nrmse_percent"]>5.:
                summary["groups"][str(tag)]={**_unsupported("seven_point_training_reconstruction_exceeds_frozen_threshold"),
                    **details,"training_reconstruction":reconstruction,"old_comparison":old_comparison}
                continue
            record={"status":"calibrated_unvalidated","method":"reference","converged":True,**details,
                "source_scope":"specified_spatial_monotonic_member_only","validation_status":"unvalidated",
                "quality_flags":["independent_validation_not_performed","two_group_subset_not_tower_drop_in"],
                "training_reconstruction":reconstruction,"old_comparison":old_comparison,
                "independent_validation":{"status":"not_performed","reason":"training_peak_insertion_and_same_curve_reconstruction_are_not_holdout_validation"},
                "domain":{"compression_strain":[0.,maximum_strain],"boundary":boundary,"member_id":tag},
                "fallback_reason":None}
            summary["groups"][str(tag)]=record
            groups[_group_key(member)]={"member":asdict(properties),"compression_envelope":[asdict(p) for p in material.compression_envelope],
                "source":material.source,"imperfection_ratio":ratio,"calibration":record,
                "actual_members":[{"original_member_id":tag,"actual_length":length,"representative_length":length,"length_error":0.,"length_error_percent":0.}]}
        summary["reference_inputs"]=reference_records
        project=Path(__file__).resolve().parents[1]
        dependencies=("initial_imperfection_material/calibrate_actual_members.py","initial_imperfection_material/material.py",
            "initial_imperfection_material/config.py","initial_imperfection_material/calibration_cache.py",
            "model/mechanical_profile.py","model/tower_model.py","util/postprocess/response_metrics.py")
        code_hashes={name:file_sha256(project/name) for name in dependencies}
        config=AnalysisConfig(model={"source_sha256":source_hash,"mechanical_profile":gate["mechanical_profile"],
                    "dependency_sha256":code_hashes,
                    "library_role":"two_group_subset_not_tower_drop_in","members":members,
                    "gate_sha256":file_sha256(gate_path),"reference_files":reference_records,"algorithm_version":"actual_members_offline_v1"},
            steel={"Q235":members[877]["steel_tower"]},boundary={"group_scopes":{key:row.get("domain",row.get("reason")) for key,row in summary["groups"].items()}},
            protocol={"loading":"zero_load_monotonic_compression","maximum_compression_strain":maximum_strain},
            solver=settings.to_dict(),calibration={"method":"reference","fallback_policy":"error","max_backbone_points":7,
                "training_peak_error_limit_percent":3.,"training_nrmse_limit_percent":5.,
                "identifiability_force_spread_prefilter_relative":.05,"independent_boundary_cases_minimum":2,
                "identifiability_prefilter_status":"engineering_precheck_not_physical_G1_acceptance",
                "independent_validation":"not_performed"})
        if groups:
            for group in groups.values():
                group["group_fingerprint"]=fingerprint({"config":config.fingerprint,"member":group["member"]})
            cache=CalibrationCache(output/"calibration_library.json")
            with cache.locked():
                cache.write(config,groups)
            cache.read(config)  # Validate the actual published v2 identity immediately.
            summary["library"]={"path":str(cache.path.resolve()),"sha256":file_sha256(cache.path),
                                "config_fingerprint":config.fingerprint,"accepted_groups":len(groups),"required_for_full_tower":194}
        if make_plots and plot_data:
            _plot(output/"calibration_comparison.png",plot_data)
        summary["status"]="calibrated_subset_unvalidated" if len(groups)==2 else "partial_or_unsupported"
        publish_json_once(output/"config.json",config.to_dict())
        publish_json_once(output/"summary.json",summary)
        return summary
    except Exception as error:
        publish_json_once(output/"failure.json",{"status":"failed","error_type":type(error).__name__,"reason":str(error),
                          "completed_group_records":summary["groups"],"no_silent_fallback":True})
        raise


def _plot(path: Path, data: Mapping[int,Mapping[str,Any]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(1,len(data),figsize=(6*len(data),4),squeeze=False)
    for axis,(tag,rows) in zip(axes[0],data.items()):
        axis.plot([p.shortening*1000 for p in rows["reference"]],[p.force/1000 for p in rows["reference"]],label="3D reference (actual coverage)")
        for key,label in (("fitted","New training reconstruction"),("old","Old cache (comparison only)")):
            curve=rows.get(key)
            if curve:
                axis.plot([x*1000 for x in curve.x],[y/1000 for y in curve.y],"--",label=label)
        axis.set(xlabel="End shortening (mm)",ylabel="Compression force (kN)",title=f"Actual member {tag}; not independent validation")
        axis.grid(alpha=.25);axis.legend(fontsize=8)
    figure.tight_layout();figure.savefig(path,dpi=150);plt.close(figure)


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=Path("Source/Z30103A6.s2k"))
    parser.add_argument("--gate-evidence",type=Path,required=True)
    parser.add_argument("--reference-877",type=Path,required=True)
    parser.add_argument("--reference-825",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--old-cache",type=Path)
    parser.add_argument("--maximum-strain",type=float,default=.03)
    parser.add_argument("--tolerance",type=float,default=1e-8)
    parser.add_argument("--allow-range-extension",action="store_true")
    args=parser.parse_args(argv)
    result=calibrate_batch(args.source,args.gate_evidence,{877:args.reference_877,825:args.reference_825},args.output,
        maximum_strain=args.maximum_strain,solver=ReferenceSolverConfig(tolerance=args.tolerance,retry_tolerance=args.tolerance),
        old_cache=args.old_cache,allow_range_extension=args.allow_range_extension)
    print(json.dumps({"status":result["status"],"groups":{key:row["status"] for key,row in result["groups"].items()},
                      "output":str(args.output)},ensure_ascii=False))


if __name__=="__main__":
    main()
