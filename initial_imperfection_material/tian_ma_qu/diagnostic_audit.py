"""Read-only N00/N01 audit of saved TMQ evidence; never builds an OpenSees domain.

Only the requested output directory is written. Model identity is derived from
saved geometry, mass, constraints, member parameters and source fingerprints.
"""
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TMQ = Path(__file__).resolve().parent
DEFAULT_BASELINE = ROOT / "docs/ai_execution_plan/tmq_next_plan_20261024/BASELINE.json"
CASE_KEYS = ("bare_checked", "coupled_20_checked", "coupled_40_checked", "coupled_80_checked")
DOFS = ("ux", "uy", "uz", "rx", "ry", "rz")
EXPECTED_MUTABLE_SOURCE = "initial_imperfection_material/tian_ma_qu/publish_modal.py"
EXPECTED_MUTABLE_SOURCES = {EXPECTED_MUTABLE_SOURCE,
                            "initial_imperfection_material/tian_ma_qu/modal_viewer.html"}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    def reject(value):
        raise ValueError(f"nonfinite JSON constant {value} in {path}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def runtime_binary_identity(saved_native, root=ROOT):
    """Hash installed binaries without importing OpenSees or invoking a compiler."""
    versions, engine_candidates = {}, []
    for name in ("openseespy", "openseespylinux"):
        try:
            distribution = importlib.metadata.distribution(name)
            versions[name] = distribution.version
            if name == "openseespylinux":
                engine_candidates = [Path(distribution.locate_file(p)) for p in distribution.files or ()
                                     if str(p).endswith("/opensees.so")]
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    engine_path = engine_candidates[0] if len(engine_candidates) == 1 else None
    paths = {"opensees_engine": engine_path,
             "tmq_bridge": Path(root) / "initial_imperfection_material/tian_ma_qu/_native_cache/tmq_python_bridge.so",
             "tmq_bridge_source": Path(root) / "initial_imperfection_material/tian_ma_qu/native_bridge.cpp"}
    expected = {"opensees_engine": saved_native["signature"]["engine_sha256"],
                "tmq_bridge": saved_native["binary_sha256"], "tmq_bridge_source": saved_native["signature"]["source_sha256"]}
    records = {}
    for name, path in paths.items():
        actual = file_sha(path) if path is not None and path.is_file() else None
        records[name] = {"path": str(path) if path is not None else None, "expected_saved_sha256": expected[name],
                         "current_sha256": actual, "matches_saved": actual == expected[name]}
    return {"distribution_versions": versions, "engine_version_in_saved_evidence": saved_native["signature"]["opensees"],
            "wrapper_version_is_not_engine_version": True, "fingerprints": records,
            "all_match_saved": all(r["matches_saved"] for r in records.values()),
            "method": "read-only hashing; no engine import, FE domain or compilation"}


def array_sha(array):
    array = np.ascontiguousarray(array)
    h = hashlib.sha256(f"{array.shape}:{array.dtype.str}".encode())
    h.update(array.tobytes())
    return h.hexdigest()


def read_csv(path, required=()):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not set(required) <= set(reader.fieldnames or ()):
            raise ValueError(f"missing CSV fields in {path}: {set(required)-set(reader.fieldnames or ())}")
        return list(reader)


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def initial_snapshot(root, baseline_path):
    root, baseline_path = Path(root), Path(baseline_path)
    baseline = read_json(baseline_path)
    files = []
    for record in baseline["protected_files"]:
        path = root / record["path"]
        actual = file_sha(path) if path.is_file() else None
        files.append({**record, "actual_sha256": actual, "matches_plan_baseline": actual == record["sha256"]})
    return {"schema": "otw2.diagnostic_audit.initial_snapshot.v1", "captured_at_utc": now(),
            "baseline_path": str(baseline_path.relative_to(root)), "baseline_sha256": file_sha(baseline_path),
            "all_match": all(item["matches_plan_baseline"] for item in files), "files": files}


def compare_snapshot(snapshot, root, expected_source_changes=()):
    """Expected publisher edits remain changes; immutable evidence never gains an exception."""
    root = Path(root)
    expected = set(expected_source_changes)
    if expected - EXPECTED_MUTABLE_SOURCES:
        raise ValueError("only explicitly declared publisher/template edits may be expected in this B1 audit")
    checks = []
    for record in snapshot["files"]:
        path = root / record["path"]
        actual = file_sha(path) if path.is_file() else None
        unchanged = actual == record["actual_sha256"] and actual is not None
        status = "unchanged" if unchanged else "expected_publisher_source_change" if record["path"] in expected and actual else "unexpected_change_or_missing"
        checks.append({"path": record["path"], "plan_sha256": record["sha256"],
                       "initial_sha256": record["actual_sha256"], "current_sha256": actual,
                       "initial_matches_plan": record["matches_plan_baseline"], "status": status})
    return {"schema": "otw2.diagnostic_audit.baseline_check.v1", "checked_at_utc": now(),
            "initial_snapshot_at_utc": snapshot["captured_at_utc"],
            "initial_all_match": snapshot["all_match"],
            "current_all_match_initial": all(c["status"] == "unchanged" for c in checks),
            "expected_source_changes": sorted(expected),
            "passed": snapshot["all_match"] and not any(c["status"] == "unexpected_change_or_missing" for c in checks),
            "interpretation": "publisher source changes are disclosed, never written back to historical evidence or baseline",
            "files": checks}


def nodal_mass_audit(mass, fixed, tower_mass, line_mass):
    arrays = [np.asarray(value) for value in (mass, fixed, tower_mass, line_mass)]
    mass, fixed, tower_mass, line_mass = arrays
    if mass.ndim != 2 or mass.shape[1] != 6 or any(a.shape != mass.shape for a in arrays):
        raise ValueError("mass and constraint arrays must have identical (nodes,6) shape")
    if fixed.dtype.kind != "b":
        raise ValueError("fixed flags must be boolean")
    if any(not np.isfinite(a).all() for a in (mass, tower_mass, line_mass)):
        raise ValueError("nonfinite mass")
    if any(np.any(a < 0) for a in (mass, tower_mass, line_mass)):
        raise ValueError("negative mass")
    insulator_mass = mass - tower_mass - line_mass
    if np.min(insulator_mass) < -1e-8:
        raise ValueError("component mass exceeds system mass")
    total, free, constrained = mass.sum(axis=0), np.where(fixed, 0, mass).sum(axis=0), np.where(fixed, mass, 0).sum(axis=0)
    return {"unit": "kg for translation; kg m2 for rotation",
            "mass_model": "nodal lumped translational; no nodal rotational inertia",
            "total_XYZ_kg": total[:3].tolist(), "free_XYZ_kg": free[:3].tolist(),
            "fixed_XYZ_kg": constrained[:3].tolist(), "rotational_mass_kg_m2": total[3:].tolist(),
            "physical_mass_kg": float(total[0]),
            "physical_mass_definition": "one directional translational sum, not sum of X+Y+Z",
            "component_kg": {"tower": float(tower_mass[:, 0].sum()), "cable": float(line_mass[:, 0].sum()),
                             "insulator": float(insulator_mass[:, 0].sum())},
            "free_plus_fixed_closure_max_kg": float(np.max(abs(free + constrained - total))),
            "isotropic_translation_mass": bool(np.allclose(mass[:, :3], mass[:, :1], atol=1e-10, rtol=0))}


def line_geometry(points):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("finite (n>=2,3) coordinates required")
    horizontal = points[-1, :2] - points[0, :2]
    span2 = float(horizontal @ horizontal)
    if span2 <= 0:
        raise ValueError("nonzero horizontal span required for vertical chord sag")
    station = (points[:, :2] - points[0, :2]) @ horizontal / span2
    chord_z = points[0, 2] + station * (points[-1, 2] - points[0, 2])
    sag = chord_z - points[:, 2]
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if np.any(segment_lengths <= 0):
        raise ValueError("zero-length cable segment")
    return {"horizontal_span_m": math.sqrt(span2), "arc_length_m": float(segment_lengths.sum()),
            "maximum_chord_sag_m": float(sag.max()), "sag_node_index": int(sag.argmax()),
            "sag_definition": "vertical chord elevation at each node's current horizontal projection minus node elevation",
            "end_coordinates_m": points[[0, -1]].tolist()}


def load_first_state(path):
    """Read gravity step zero only, checking complete row identities; do not read a whole trajectory."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    result = {}
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"step", "node_tag", *DOFS} <= set(reader.fieldnames or ()):
            raise ValueError("node states missing required columns")
        for row in reader:
            if int(row["step"]) != 0:
                break
            tag = int(row["node_tag"])
            if tag in result:
                raise ValueError("duplicate node in gravity state")
            values = np.asarray([float(row[dof]) for dof in DOFS])
            if not np.isfinite(values).all():
                raise ValueError("nonfinite gravity state")
            result[tag] = values
    if not result:
        raise ValueError("missing step-zero state")
    return result


def member_parameters(rows):
    if not rows or len({int(r["element_tag"]) for r in rows}) != len(rows):
        raise ValueError("empty or duplicate physical-member parameters")
    def span(key):
        values = [float(r[key]) for r in rows]
        if not all(math.isfinite(x) for x in values):
            raise ValueError(f"nonfinite member {key}")
        return [min(values), max(values)]
    constants = {}
    for key in ("elastic_modulus", "rho", "alpha", "beta", "gamma", "tau", "mu", "nu", "zeta", "eta", "theta", "kappa", "residual_compression_ratio"):
        values = sorted({float(r[key]) for r in rows})
        constants[key] = values[0] if len(values) == 1 else values
    return {"physical_member_count": len(rows), "steel_grade_counts": dict(sorted(Counter(r["material_name"] for r in rows).items())),
            "section_counts": dict(sorted(Counter(r["section_name"] for r in rows).items())),
            "length_m_range": span("length_m"), "slenderness_K1_range": span("slenderness_K1"),
            "phi_range": span("phi"), "parameters_from_saved_rows": constants,
            "effective_length_factor": 1.0, "imperfection_ratio": 0.001,
            "coefficient_case": "p102_row_a", "physical_validation": "unvalidated",
            "evidence_level": "numerical_prototype_only", "phi_meaning": "Perry first-fiber-yield estimate, not independently calibrated ultimate buckling",
            "strain_meaning": "equivalent component axial strain, not steel fiber strain",
            "element": "one straight 3D Corotational dispBeamColumn per physical member",
            "integration": "3-point Legendre", "section": "TMQ axial P plus elastic uncoupled My/Mz/T",
            "limitations": ["tube cyclic coefficients transferred to angle steel without independent calibration",
                            "no added initial geometric bow; imperfection only enters phi estimate",
                            "I23 omitted in beam stiffness; no plastic axial-bending interaction",
                            "no damage/fracture/deletion; no calibrated whole-tower collapse criterion"],
            "provenance_values": sorted({r["provenance"] for r in rows})}


def audit_case(directory, root=ROOT):
    directory, root = Path(directory), Path(root)
    summary = read_json(directory / "summary.json")
    if summary["status"] != "complete" or summary.get("checks_passed") is not True:
        raise ValueError(f"incomplete/unaccepted modal evidence: {directory}")
    with np.load(directory / "eigenvectors.npz", allow_pickle=False) as archive:
        a = {key: archive[key] for key in ("node_tags", "initial_coordinates", "gravity_coordinates", "gravity_displacements", "mass", "fixed", "tower_mass", "line_mass")}
    tags = a["node_tags"]
    if tags.ndim != 1 or len(set(map(int, tags))) != len(tags):
        raise ValueError("unique one-dimensional node tags required")
    index = {int(tag): n for n, tag in enumerate(tags)}
    n = len(tags)
    for key, shape in (("initial_coordinates", (n, 3)), ("gravity_coordinates", (n, 3)), ("gravity_displacements", (n, 6))):
        if a[key].shape != shape or not np.isfinite(a[key]).all():
            raise ValueError(f"invalid saved {key}")
    if a["mass"].shape != (n, 6):
        raise ValueError("mass rows differ from node tags")
    mass = nodal_mass_audit(a["mass"], a["fixed"], a["tower_mass"], a["line_mass"])
    tower_nodes = read_csv(directory / "model_data/nodes.csv", ("node_tag", "x", "y", "z"))
    tower_elements = read_csv(directory / "model_data/elements.csv", ("element_tag", "node_i", "node_j"))
    tower_fixes = read_csv(directory / "model_data/fixes.csv", ("node_tag", *DOFS))
    tower_masses = read_csv(directory / "model_data/masses.csv", ("node_tag", "mx", "my", "mz"))
    parameters = read_csv(directory / "model_data/tmq_member_parameters.csv", ("element_tag", "provenance"))
    tower_tag_set = {int(row["node_tag"]) for row in tower_nodes}
    if len(tower_nodes) != len(tower_tag_set) or not tower_tag_set <= set(index):
        raise ValueError("tower node map not a unique subset of system nodes")
    tower_coordinate_error = max(float(np.max(abs(a["initial_coordinates"][index[int(r["node_tag"])]] - [float(r[v]) for v in "xyz"]))) for r in tower_nodes)
    tower_mass_error = max(float(np.max(abs(a["tower_mass"][index[int(r["node_tag"])]] - [float(r[v]) for v in ("mx", "my", "mz", "mrx", "mry", "mrz")]))) for r in tower_masses)
    with np.load(directory / "equation_modes.npz", allow_pickle=False) as eq:
        node_dofs = eq["node_dofs"]
        if not np.array_equal(eq["node_tags"], tags) or node_dofs.shape != (n, 6):
            raise ValueError("free-equation node mapping mismatch")
    if not np.array_equal(node_dofs < 0, a["fixed"]):
        raise ValueError("stored fixed flags disagree with equation mapping")
    free_dofs = node_dofs[node_dofs >= 0]
    if len(set(map(int, free_dofs))) != len(free_dofs) or not np.array_equal(np.sort(free_dofs), np.arange(len(free_dofs))):
        raise ValueError("free equations are not a unique contiguous map")
    from scipy.sparse import load_npz
    matrix_mass = load_npz(directory / "mass.npz").tocsr()
    expected_mass = np.zeros(len(free_dofs))
    expected_mass[node_dofs[node_dofs >= 0]] = a["mass"][node_dofs >= 0]
    if matrix_mass.shape != (len(free_dofs), len(free_dofs)):
        raise ValueError("mass matrix size disagrees with free equations")
    mass_diagonal_error = float(np.max(abs(matrix_mass.diagonal() - expected_mass)))
    off_diagonal = matrix_mass - __import__("scipy.sparse", fromlist=["diags"]).diags(matrix_mass.diagonal())
    mass_off_diagonal_max = float(np.max(abs(off_diagonal.data))) if off_diagonal.nnz else 0.0
    constraints = [{"node_tag": int(tag), "fixed": a["fixed"][i].astype(int).tolist()} for i, tag in enumerate(tags) if a["fixed"][i].any()]
    base_tags = sorted(int(r["node_tag"]) for r in tower_fixes)
    full_fixed_tags = sorted(int(tags[i]) for i in range(n) if a["fixed"][i].all())
    remote_tags = sorted(set(full_fixed_tags) - set(base_tags))
    lines, insulators = [], []
    source_files = [directory / f for f in ("summary.json", "eigenvectors.npz", "equation_modes.npz", "mass.npz", "stiffness.npz", "model_data/nodes.csv", "model_data/elements.csv", "model_data/fixes.csv", "model_data/masses.csv", "model_data/tmq_member_parameters.csv")]
    if summary["segments_per_span"]:
        configuration = read_json(directory / "line_model/effective_configuration.json")
        source_files.extend(directory / "line_model" / f for f in ("effective_configuration.json", "transmission_lines.csv", "insulators.csv", "system_nodes.csv", "system_elements.csv"))
        tension = {row["line_id"]: row for row in summary["cable_gravity_tensions"]}
        for row in read_csv(directory / "line_model/transmission_lines.csv", ("line_id", "node_tags", "n_seg")):
            node_tags = ast.literal_eval(row["node_tags"])
            element_tags = ast.literal_eval(row["element_tags"])
            if len(node_tags) != int(row["n_seg"]) + 1 or len(element_tags) != int(row["n_seg"]) or len(set(node_tags)) != len(node_tags):
                raise ValueError("invalid physical line topology")
            position = [index[int(tag)] for tag in node_tags]
            material = ast.literal_eval(row["material"])
            conductor = ast.literal_eval(row["conductor"])
            initial = line_geometry(a["initial_coordinates"][position])
            gravity = line_geometry(a["gravity_coordinates"][position])
            lines.append({"line_id": row["line_id"], "node_tags": node_tags, "element_tags": element_tags,
                          "segments_per_span": int(row["n_seg"]), "configured_span_m": float(row["span"]),
                          "configured_initial_sag_m": float(row["initial_sag"]), "material": material, "conductor": conductor,
                          "initial_geometry": initial, "gravity_geometry": gravity,
                          "gravity_tension_N": {"min": tension[row["line_id"]]["min_tension_N"], "max": tension[row["line_id"]]["max_tension_N"]},
                          "mass_per_initial_length_kg_m": float(row["mass_per_length"]), "mass_kg": float(row["total_conductor_mass"]),
                          "mass_geometry": "initial parabolic segmented arc; mass is not recomputed after gravity deformation",
                          "mass_vs_arc_closure_kg": float(row["total_conductor_mass"]) - float(row["mass_per_length"]) * initial["arc_length_m"],
                          "formfinding_status": "not_performed; initial shape plus initial force then one global gravity equilibrium",
                          "gravity_applied_by": row["gravity_applied_by"]})
        for row in read_csv(directory / "line_model/insulators.csv", ("insulator_id", "lower_node_tag")):
            original = configuration["insulators"][row["insulator_id"]]
            insulators.append({"insulator_id": row["insulator_id"], "lower_node_tag": int(row["lower_node_tag"]),
                               "upper_node_tags": ast.literal_eval(row["upper_node_tags"]), "element_tags": ast.literal_eval(row["element_tags"]),
                               "EA_N": float(row["EA"]), "mass_kg": float(original["material"]["mass"]),
                               "initial_lower_coord_m": ast.literal_eval(row["lower_coord"]),
                               "material": "Elastic; not tension-only"})
    identity = {"source_sha256": summary["source_sha256"], "segments_per_span": summary["segments_per_span"],
                "initial_geometry_sha256": array_sha(a["initial_coordinates"]), "node_tags_sha256": array_sha(tags),
                "mass_sha256": array_sha(a["mass"]), "fixed_sha256": array_sha(a["fixed"]),
                "members_sha256": file_sha(directory / "model_data/tmq_member_parameters.csv")}
    identity["source_sha256"] = {k: v for k, v in identity["source_sha256"].items() if not k.endswith("modal_analysis.py")}
    state = {"model_id": object_sha(identity), "gravity_displacement_sha256": array_sha(a["gravity_displacements"]),
             "gravity_coordinates_sha256": array_sha(a["gravity_coordinates"]), "saved_tangent_K_sha256": file_sha(directory / "stiffness.npz")}
    coordinate_closure = float(np.max(abs(a["gravity_coordinates"] - a["initial_coordinates"] - a["gravity_displacements"][:, :3])))
    summary_mass_error = float(np.max(abs(np.array(summary["total_mass_XYZ_kg"]) - np.array(mass["total_XYZ_kg"]))))
    summary_free_error = float(np.max(abs(np.array(summary["free_mass_XYZ_kg"]) - np.array(mass["free_XYZ_kg"]))))
    component_error = max(abs(summary["component_total_mass_kg"][k] - mass["component_kg"][k]) for k in mass["component_kg"])
    checks = {"tower_count_621_1528": len(tower_nodes) == 621 and len(tower_elements) == len(parameters) == 1528,
              "system_node_count": n == summary["node_count"],
              "system_element_count": len(tower_elements) + sum(len(x["element_tags"]) for x in lines + insulators) == summary["element_count"],
              "tower_coordinates_match": tower_coordinate_error < 1e-10, "tower_mass_matches": tower_mass_error < 1e-8,
              "gravity_coordinate_closure": coordinate_closure < 1e-10,
              "mass_summary_matches": max(summary_mass_error, summary_free_error, component_error) < 1e-6,
              "mass_matrix_matches_nodal_ledger": max(mass_diagonal_error, mass_off_diagonal_max) < 1e-8,
              "gravity_mass_matches": abs(summary["gravity_total_mass_kg"] - mass["physical_mass_kg"]) < 1e-6,
              "lines_mass_matches": abs(sum(x["mass_kg"] for x in lines) - mass["component_kg"]["cable"]) < 1e-6,
              "insulator_mass_matches": abs(sum(x["mass_kg"] for x in insulators) - mass["component_kg"]["insulator"]) < 1e-6,
              "gravity_equilibrium_passed": summary["gravity_equilibrium"]["passed"] is True,
              "virgin_gravity_material_state": summary["gravity_buckled_members"] == summary["gravity_tension_yield_members"] == 0,
              "all_cables_in_tension": all(x["gravity_tension_N"]["min"] > 0 for x in lines)}
    mass["audit_errors_kg"] = {"summary_total": summary_mass_error, "summary_free": summary_free_error,
                              "component": component_error, "matrix_diagonal": mass_diagonal_error, "matrix_off_diagonal": mass_off_diagonal_max}
    contract = {"source_directory": str(directory.relative_to(root)), "model_id": state["model_id"], "state_id": object_sha(state),
                "identity_inputs": identity, "state_inputs": state, "source_sha256": summary["source_sha256"],
                "engine_version": summary["engine_version"], "segments_per_span": summary["segments_per_span"],
                "nodes": {"system_count": n, "tower_count": len(tower_nodes), "tower_node_tags": sorted(tower_tag_set),
                          "control_node": 350, "control_initial_coordinates_m": a["initial_coordinates"][index[350]].tolist(),
                          "maximum_tower_initial_height_m": max(float(r["z"]) for r in tower_nodes)},
                "elements": {"system_count": summary["element_count"], "tower_physical_count": len(tower_elements),
                             "cable_count": sum(len(x["element_tags"]) for x in lines), "insulator_count": sum(len(x["element_tags"]) for x in insulators)},
                "constraints": {"tower_base_nodes": base_tags, "remote_fixed_nodes": remote_tags,
                                "fixed_DOF_counts_XYZRxRyRz": a["fixed"].sum(axis=0).tolist(), "free_equation_count": len(free_dofs),
                                "fixed_node_DOF_map": constraints, "multiple_point_constraints": "none in saved one-tower prototype; equation map checked"},
                "mass": mass, "lines": lines, "insulators": insulators, "material_scope": member_parameters(parameters),
                "gravity": {"state": summary["state"], "equilibrium": summary["gravity_equilibrium"],
                            "buckled_members": summary["gravity_buckled_members"], "tension_yield_members": summary["gravity_tension_yield_members"],
                            "one_mass_derived_gravity_pattern": True, "mean_wind_applied": False, "source_displacement_file": str((directory / "eigenvectors.npz").relative_to(root)),
                            "steps_from_runner": 50 if lines else 10, "time_after_loadConst_s": 0.0},
                "damping": {"analysis": "undamped eigenanalysis", "implemented_transient_damping": None,
                            "status": "not_defined_or_verified_for_transient; N04/N08 required"},
                "checks": checks, "checks_passed": all(checks.values()), "physical_validation": "unvalidated"}
    return contract, source_files


def compare_wind_initial_states(tmq, contracts):
    tmq = Path(tmq)
    wind = read_json(tmq / "wind_speed_results/summary.json")
    archive_cache, comparison, source_files = {}, [], [tmq / "wind_speed_results/summary.json"]
    for item in wind["cases"]:
        case_key = item["key"]
        path = tmq / "wind_speed_results/runs" / case_key
        s = read_json(path / "summary.json")
        coupled = s["directional_wind"]["mode"] == "tower_line_explicit"
        modal_key = "coupled_20_checked" if coupled else "bare_checked"
        directory = tmq / "modal_results/runs" / modal_key
        if modal_key not in archive_cache:
            with np.load(directory / "eigenvectors.npz", allow_pickle=False) as archive:
                archive_cache[modal_key] = {int(tag): vector for tag, vector in zip(archive["node_tags"], archive["gravity_displacements"])}
        expected = archive_cache[modal_key]
        actual = load_first_state(path / "node_states.csv.gz")
        if set(actual) != set(expected):
            raise ValueError(f"wind gravity nodes differ from matched modal case: {case_key}")
        max_diff = float(max(np.max(abs(actual[tag] - expected[tag])) for tag in expected))
        mass_difference = float(s["total_gravity_mass_kg"] - contracts[modal_key]["mass"]["physical_mass_kg"])
        members_match = file_sha(path / "model_data/tmq_member_parameters.csv") == file_sha(directory / "model_data/tmq_member_parameters.csv")
        segments = s["line_model"]["segments_per_span"] if coupled else 0
        record = {"wind_case": case_key, "matched_modal_case": modal_key, "segments_per_span": segments,
                  "nodes_compared": len(actual), "gravity_displacement_max_abs_difference": max_diff,
                  "gravity_displacement_units": "m for XYZ, rad for rotations", "gravity_mass_difference_kg": mass_difference,
                  "member_parameter_file_identical": members_match,
                  "gravity_state_matches": max_diff < 1e-10 and abs(mass_difference) < 1e-6 and members_match,
                  "wind_angle_deg": s["directional_wind"]["wind_angle_deg"],
                  "wind_analysis_status": s["status"], "scope": "step0 initial state only; no claim that subsequent nonlinear path is identical"}
        comparison.append(record)
        source_files.extend(path / file for file in ("summary.json", "node_states.csv.gz", "model_data/tmq_member_parameters.csv", "wind_config.json"))
    return comparison, source_files


def build_report(contract, baseline):
    cases, comparisons = contract["cases"], contract["wind_modal_initial_state_comparison"]
    lines = ["# N00/N01 证据与模型声明审计", "", "本批仅读取已有结果、原始参数和源码；没有新建OpenSees域或新增有限元计算。", "",
             "## 实际步骤", "", "1. 固定计划中68个输入文件的首次指纹，并将本批预期的发布器源码修改与不可变历史结果分开。",
             "2. 读取4个checked工况的float64节点、质量、约束、重力位移、方程映射及保存的M矩阵；逐项核对导出CSV与summary。",
             "3. 按每跨原始/重力节点计算弧长与弦垂度，结合配置、质量和已记录张力建立线系统声明。",
             "4. 逐个读取13个风速工况的step0六自由度节点记录，比较同网格的无风重力初态；不读取后续状态作为模态初态。",
             "5. 保存模型/状态指纹、差异表、输入索引和审计判定。测试命令与结果单独写入validation/。", "",
             "## 结果", "", f"首次基线匹配：{baseline['initial_all_match']}；68文件当前是否全部未变：{baseline['current_all_match_initial']}。预期源码变化不追写到旧基线，具体见baseline_check.json。", "",
             "| 工况 | 总节点/单元 | 总质量 kg | 自由X质量 kg | 固定X质量 kg | 每跨重力后垂度 m | 张力范围 kN |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for key, c in cases.items():
        cable = c["lines"]
        sag = f"{cable[0]['gravity_geometry']['maximum_chord_sag_m']:.9f}" if cable else "—"
        tension = f"{min(x['gravity_tension_N']['min'] for x in cable)/1000:.5f}～{max(x['gravity_tension_N']['max'] for x in cable)/1000:.5f}" if cable else "—"
        lines.append(f"| {key} | {c['nodes']['system_count']}/{c['elements']['system_count']} | {c['mass']['physical_mass_kg']:.9f} | {c['mass']['free_XYZ_kg'][0]:.9f} | {c['mass']['fixed_XYZ_kg'][0]:.9f} | {sag} | {tension} |")
    primary = cases["coupled_80_checked"]
    lines.extend(["", f"所有塔体均为621节点、1528根原始物理杆；控制节点350初始高度36.4m，塔体最高39.6m。80段体系质量分解为塔体{primary['mass']['component_kg']['tower']:.9f}kg、导线{primary['mass']['component_kg']['cable']:.9f}kg、绝缘子100kg。XYZ各方向相同质量不能相加为三倍物理质量。",
                  "", "导线网格加密时质量采用初始分段弧长，弧长逐步收敛；固定锚点承受的端部集中质量也随分段改变，所以自由质量并非跨网格完全相同。重力变形后不重新计算质量。",
                  "", f"风速/模态同网格初态比较：{sum(x['gravity_state_matches'] for x in comparisons)}/{len(comparisons)}通过，最大节点六自由度差={max(x['gravity_displacement_max_abs_difference'] for x in comparisons):.3g}。塔线旧风速为20段/跨；只能与coupled_20_checked直接对齐，不能改名成80段。比较对象仅为step0，不代表后续推覆路径已验证。",
                  "", "## 参数与传力假设", "",
                  "- S2K的E=210GPa，Q235/Q345/Q420；强化rho=0.03。TMQ循环参数来自p102_row_a管件试验系数，迁移至角钢尚未独立验证。",
                  "- phi为K=1、e0/L=0.001下Perry首次纤维屈服估计；直杆中没有再添加几何初弯曲。轴向TMQ与弹性My/Mz/T解耦，I23未进入梁刚度，无断裂/删除。",
                  "- 单塔两组V串、四跨各300m、固定远端，JL/G1A-400/50一分裂，线密度1.5103kg/m、直径0.0276m、EA=28MN、初始张力20kN；V串每组50kg、EA=100MN。",
                  "- 初始抛物线垂度8m和初应力同时作为输入，然后施加一次全局质量重力；没有求解满足指定目标垂度/张力的独立找形。空formfinding表不是找形通过证据。",
                  "- 已发布模态均为新鲜无风重力平衡态，无TMQ压屈或拉伸屈服。没有经验证的瞬态阻尼配置；阻尼由N04/N08另行处理。",
                  "- 风速扫描采用均匀流、Cx=Cy=Cd=1、yaw gain=0.2及所有杆件角钢肢宽代理，无遮挡/地形/气动阻尼校准。20√lambda是原型静风等效，不是工程极限风速。", "",
                  "## 验收与范围", "", f"4个模型声明检查：{all(c['checks_passed'] for c in cases.values())}；同网格初态对齐：{all(x['gravity_state_matches'] for x in comparisons)}。",
                  "这些结果支持G0的身份/质量/重力初态可追溯性；不证明网格收敛、模态截断、实际阻尼、角钢循环、气动力或工程容量已验证。物理状态保持unvalidated。",
                  "", "原始文件索引见evidence_index.csv；机器可读声明见model_contract.json；分段差异与风速初态核对见model_difference_table.csv。",
                  "", "## 重复执行", "", "```bash", "OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.diagnostic_audit \\",
                  "  --output initial_imperfection_material/tian_ma_qu/followup_results/B1_unique/audit \\",
                  f"  --expected-source-change {EXPECTED_MUTABLE_SOURCE}", "```", "", "输出目录不得已有model_contract.json。若计划基线已有源码变化，首次快照会如实标记，不能自动覆盖为通过；应单独解释新增基线。"])
    return "\n".join(lines) + "\n"


def run(output, *, root=ROOT, baseline_path=DEFAULT_BASELINE, expected_source_changes=()):
    root, output = Path(root).resolve(), Path(output).resolve()
    tmq = root / "initial_imperfection_material/tian_ma_qu"
    for protected in (tmq / "modal_results", tmq / "wind_speed_results"):
        if output == protected or protected in output.parents:
            raise ValueError("audit output cannot be inside historical result directories")
    if (output / "model_contract.json").exists():
        raise FileExistsError("audit output already complete; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    snapshot_path = output / "baseline_initial.json"
    if not snapshot_path.exists():
        write_json(snapshot_path, initial_snapshot(root, Path(baseline_path)))
    initial = read_json(snapshot_path)
    cases, source_files = {}, []
    for key in CASE_KEYS:
        cases[key], files = audit_case(tmq / "modal_results/runs" / key, root)
        source_files.extend(files)
    comparisons, files = compare_wind_initial_states(tmq, cases)
    source_files.extend(files)
    baseline_check = compare_snapshot(initial, root, expected_source_changes)
    first_wind = read_json(tmq / "wind_speed_results/runs/tower_line_45_disp/summary.json")
    runtime_binaries = runtime_binary_identity(first_wind["native_metadata"], root)
    contract = {"schema": "otw2.tmq_model_contract.v1", "created_at_utc": now(),
                "analysis": "read_only_saved_model_identity_and_initial_state_audit", "new_FE_runs": 0,
                "cases": cases, "wind_modal_initial_state_comparison": comparisons,
                "wind_reference": first_wind["directional_wind"], "wind_speed_mapping": "U=20*sqrt(lambda), lambda>=0; fixed reference pattern and constant gravity",
                "shared_native_metadata_from_saved_wind_run": first_wind["native_metadata"],
                "current_runtime_binary_identity": runtime_binaries,
                "unknowns": {"physical_angle_steel_calibration": None, "site_design_wind_reference": None,
                             "validated_transient_damping": None, "remote_adjacent_tower_flexibility": None},
                "physical_validation": "unvalidated", "identity_and_initial_state_checks_passed": all(c["checks_passed"] for c in cases.values()) and all(x["gravity_state_matches"] for x in comparisons) and runtime_binaries["all_match_saved"],
                "baseline_check_passed": baseline_check["passed"],
                "source_code": {"path": str(Path(__file__).relative_to(root)), "sha256": file_sha(__file__)},
                "runtime_environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                                        "workspace": str(root), "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                                        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip(),
                                        "disk_free_bytes": shutil.disk_usage(root).free}}
    write_json(output / "model_contract.json", contract)
    write_json(output / "baseline_check.json", baseline_check)
    index = []
    source_files.extend(root / item["path"] for item in initial["files"])
    for path in sorted(set(source_files)):
        index.append({"path": str(path.relative_to(root)), "size_bytes": path.stat().st_size, "sha256": file_sha(path),
                      "role": "historical_evidence" if "/runs/" in str(path) or "_results/" in str(path) else "source_or_plan",
                      "state": "existing_input_read_only"})
    write_csv(output / "evidence_index.csv", index, ("path", "size_bytes", "sha256", "role", "state"))
    differences = []
    for key, c in cases.items():
        for metric, value, unit in (("segments_per_span", c["segments_per_span"], "count"), ("system_nodes", c["nodes"]["system_count"], "count"),
                                    ("system_elements", c["elements"]["system_count"], "count"), ("total_mass", c["mass"]["physical_mass_kg"], "kg"),
                                    ("free_X_mass", c["mass"]["free_XYZ_kg"][0], "kg"), ("fixed_X_mass", c["mass"]["fixed_XYZ_kg"][0], "kg")):
            differences.append({"category": "modal_grid", "case": key, "reference": "saved_state", "metric": metric, "value": value, "unit": unit, "passed": c["checks_passed"]})
    for item in comparisons:
        differences.append({"category": "wind_modal_gravity", "case": item["wind_case"], "reference": item["matched_modal_case"],
                            "metric": "max_node_6DOF_difference", "value": item["gravity_displacement_max_abs_difference"], "unit": "m/rad by DOF", "passed": item["gravity_state_matches"]})
    write_csv(output / "model_difference_table.csv", differences, ("category", "case", "reference", "metric", "value", "unit", "passed"))
    (output / "REPORT.md").write_text(build_report(contract, baseline_check), encoding="utf-8")
    command = f"OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.diagnostic_audit --output {output.relative_to(root) if root in output.parents else output}"
    for expected in expected_source_changes:
        command += f" --expected-source-change {expected}"
    (output / "execution_log.md").write_text("# N00/N01 执行日志\n\n" + f"- 首次快照：{initial['captured_at_utc']}，68文件匹配={initial['all_match']}。\n- 审计完成：{now()}。\n- 命令：`{command}`\n- 新FE：0；现有模态工况4；静风重力初态对照{len(comparisons)}。\n- 身份/初态检查：{contract['identity_and_initial_state_checks_passed']}；基线审计：{baseline_check['passed']}。\n- 测试命令与实际日志见 validation/；不把脚本内部审计计数当作单元测试数。\n", encoding="utf-8")
    return contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--expected-source-change", action="append", default=[])
    args = parser.parse_args()
    result = run(args.output, baseline_path=args.baseline, expected_source_changes=args.expected_source_change)
    print(json.dumps({"schema": result["schema"], "new_FE_runs": 0, "cases": len(result["cases"]),
                      "wind_initial_states": len(result["wind_modal_initial_state_comparison"]),
                      "identity_and_initial_state_checks_passed": result["identity_and_initial_state_checks_passed"],
                      "baseline_check_passed": result["baseline_check_passed"]}, indent=2))
    raise SystemExit(0 if result["identity_and_initial_state_checks_passed"] and result["baseline_check_passed"] else 1)


if __name__ == "__main__":
    main()
