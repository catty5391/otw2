"""Read-only modal group diagnostics of saved gravity-state evidence (no OpenSees).

This module never constructs a finite-element domain or solves new eigenpairs.
It compares saved vectors on common tower DOFs and common cable arc stations.
"""
from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CASES = ("bare_checked", "coupled_20_checked", "coupled_40_checked", "coupled_80_checked")
DEFAULT_CONFIG = {
    "schema": "otw2.modal_group_config.v1",
    "frequency_window_Hz": [1.8, 2.7],
    "relative_cluster_gap": 0.001,
    "svd_relative_rank_tolerance": 1e-10,
    "dominant_tower_energy_retention": 0.999,
    "minimum_principal_cosine_squared": 0.98,
    "reference_projection_coverage_min": 0.98,
    "relative_frequency_change_max": 0.005,
    "representative_method": "maximum MAC times full-mode tower kinetic share, for comparison only",
    "family_MAC_min": 0.9,
    "family_tower_share_min": 0.005,
    "cable_station_count_per_span": 161,
    "cable_station_coordinate": "normalized initial arc length, not gravity-deformed node ordering",
    "cable_reference_quadrature": "80-segment initial span arc length and line density, trapezoidal station weights",
    "scope": "saved zero-wind gravity states; no forced-response or physical validation",
}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fingerprint(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "size_bytes": path.stat().st_size, "sha256": h.hexdigest()}


def _weighted_columns(vectors, weights):
    a = np.asarray(vectors, dtype=float)
    w = np.asarray(weights, dtype=float)
    if a.ndim != 2 or w.ndim != 1 or a.shape[0] != len(w) or a.shape[1] == 0:
        raise ValueError("expected nonempty DOF-by-mode matrix and matching diagonal weights")
    if not np.isfinite(a).all() or not np.isfinite(w).all() or np.any(w < 0) or not np.any(w > 0):
        raise ValueError("finite vectors and nonnegative weights with positive support required")
    positive = w > 0
    b = a[positive] * np.sqrt(w[positive, None])
    if not np.any(b):
        raise ValueError("group has zero weighted norm")
    return b


def weighted_basis(vectors, weights, *, rank_tolerance=1e-10, energy_retention=None):
    """Return an SVD basis and explicit rank/energy diagnostics.

    Zero-weight DOFs are excluded. Rank loss is reported, never silently called
    equality. Optional energy truncation is a declared supplementary diagnostic.
    """
    if not 0 < rank_tolerance < 1:
        raise ValueError("rank tolerance must lie between zero and one")
    if energy_retention is not None and not 0 < energy_retention <= 1:
        raise ValueError("energy retention must lie in (0,1]")
    b = _weighted_columns(vectors, weights)
    u, singular, _ = np.linalg.svd(b, full_matrices=False)
    rank = int(np.count_nonzero(singular > singular[0] * rank_tolerance))
    retained = rank
    energy = singular ** 2
    if energy_retention is not None:
        retained = min(rank, int(np.searchsorted(np.cumsum(energy) / energy.sum(), energy_retention) + 1))
    info = {"columns": int(b.shape[1]), "positive_weight_dofs": int(b.shape[0]),
            "numerical_rank": rank, "rank_deficient": rank < b.shape[1], "retained_rank": retained,
            "singular_values": singular.tolist(), "weighted_trace": float(energy.sum()),
            "retained_trace_fraction": float(energy[:retained].sum() / energy.sum()),
            "relative_rank_tolerance": rank_tolerance, "requested_energy_retention": energy_retention}
    return u[:, :retained], info


def compare_subspaces(a, b, weights, *, rank_tolerance=1e-10, energy_retention=None):
    qa, ia = weighted_basis(a, weights, rank_tolerance=rank_tolerance, energy_retention=energy_retention)
    qb, ib = weighted_basis(b, weights, rank_tolerance=rank_tolerance, energy_retention=energy_retention)
    cosines = np.clip(np.linalg.svd(qa.T @ qb, compute_uv=False), 0, 1)
    overlap = float(np.sum(cosines ** 2))
    ra, rb = qa.shape[1], qb.shape[1]
    # Both directional losses are required: a contained subspace is not equality.
    loss_a = float(np.sqrt(max(0, 1 - overlap / ra)))
    loss_b = float(np.sqrt(max(0, 1 - overlap / rb)))
    return {"a": ia, "b": ib, "principal_cosines_squared": (cosines ** 2).tolist(),
            "minimum_principal_cosine_squared": float(cosines[-1] ** 2),
            "a_to_b_normalized_projection_residual": loss_a,
            "b_to_a_normalized_projection_residual": loss_b,
            "same_retained_rank": ra == rb,
            "unmatched_dimension_count": abs(ra - rb)}


def projection_coverage(group, references, weights, *, rank_tolerance=1e-10):
    q, info = weighted_basis(group, weights, rank_tolerance=rank_tolerance)
    r = _weighted_columns(references, weights)
    norm = np.einsum("ij,ij->j", r, r)
    if np.any(norm <= 0):
        raise ValueError("reference has zero weighted norm")
    projected = q.T @ r
    return np.clip(np.sum(projected ** 2, axis=0) / norm, 0, 1), info


def weighted_mac_matrix(references, candidates, weights):
    a = _weighted_columns(references, weights)
    b = _weighted_columns(candidates, weights)
    an = np.sum(a ** 2, axis=0)
    bn = np.sum(b ** 2, axis=0)
    if np.any(an <= 0) or np.any(bn <= 0):
        raise ValueError("individual vector has zero weighted norm")
    return np.clip((a.T @ b) ** 2 / (an[:, None] * bn[None, :]), 0, 1)


def common_node_indices(reference_tags, candidate_tags):
    ref, cand = np.asarray(reference_tags), np.asarray(candidate_tags)
    if ref.ndim != 1 or cand.ndim != 1 or len(np.unique(ref)) != len(ref) or len(np.unique(cand)) != len(cand):
        raise ValueError("unique one-dimensional node tags required")
    index = {int(tag): i for i, tag in enumerate(cand)}
    missing = [int(tag) for tag in ref if int(tag) not in index]
    if missing:
        raise ValueError(f"missing common tower nodes: {missing[:5]}")
    return np.array([index[int(tag)] for tag in ref], dtype=int)


def frequency_clusters(frequencies, relative_gap=0.001):
    f = np.asarray(frequencies, float)
    if f.ndim != 1 or not len(f) or not np.isfinite(f).all() or np.any(f <= 0) or np.any(np.diff(f) < 0):
        raise ValueError("positive finite ascending frequencies required")
    if relative_gap < 0 or not np.isfinite(relative_gap):
        raise ValueError("nonnegative finite frequency cluster gap required")
    cuts = np.flatnonzero(np.diff(f) / np.maximum(f[:-1], f[1:]) > relative_gap) + 1
    return [g for g in np.split(np.arange(len(f)), cuts)]


def complete_cluster_window(frequencies, lower, upper, relative_gap=0.001):
    if not 0 < lower < upper:
        raise ValueError("positive increasing frequency window required")
    f = np.asarray(frequencies, float)
    groups = frequency_clusters(f, relative_gap)
    core = np.flatnonzero((f >= lower) & (f <= upper))
    if not len(core):
        raise ValueError("no modes inside declared frequency window")
    selected = np.concatenate([g for g in groups if np.intersect1d(g, core).size])
    return selected, {"requested_bounds_Hz": [lower, upper],
                      "actual_bounds_Hz": [float(f[selected[0]]), float(f[selected[-1]])],
                      "added_edge_modes": (np.setdiff1d(selected, core) + 1).tolist(),
                      "upper_spectrum_censored": bool(selected[-1] == len(f) - 1)}


def interpolate_span_modes(coordinates, vectors, stations):
    """Interpolate along a physically ordered span; never match mesh node labels."""
    xyz, v, stations = np.asarray(coordinates, float), np.asarray(vectors, float), np.asarray(stations, float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 2 or v.ndim != 3 or v.shape[1:] != xyz.shape:
        raise ValueError("span coordinates must be nodes x 3 and vectors modes x nodes x 3")
    if not np.isfinite(xyz).all() or not np.isfinite(v).all() or not np.isfinite(stations).all():
        raise ValueError("finite span data required")
    lengths = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
    if np.any(lengths <= 0) or stations.ndim != 1 or len(stations) < 2 or stations[0] != 0 or stations[-1] != 1 or np.any(np.diff(stations) <= 0):
        raise ValueError("positive segments and increasing stations spanning [0,1] required")
    s = np.r_[0, np.cumsum(lengths)] / lengths.sum()
    out = np.empty((len(v), len(stations), 3))
    for mode in range(len(v)):
        for axis in range(3):
            out[mode, :, axis] = np.interp(stations, s, v[mode, :, axis])
    return out, float(lengths.sum())


def load_case(directory: Path):
    with np.load(directory / "eigenvectors.npz", allow_pickle=False) as saved:
        a = {k: saved[k] for k in saved.files}
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if summary.get("status") != "complete" or not summary.get("checks_passed"):
        raise ValueError(f"unaccepted modal source: {directory}")
    v, mass, fixed = a["vectors"], a["mass"], a["fixed"]
    if v.ndim != 3 or v.shape[1:] != mass.shape or mass.shape[1] != 6 or fixed.shape != mass.shape:
        raise ValueError("invalid saved nodal modal shapes")
    if v.dtype != np.float64 or not np.isfinite(v).all() or not np.isfinite(mass).all() or np.any(mass < 0):
        raise ValueError("finite float64 vectors and nonnegative mass required")
    free = mass * ~fixed
    gram = np.einsum("ind,nd,jnd->ij", v, free, v)
    if np.max(np.abs(gram - np.eye(len(v)))) > 1e-6:
        raise ValueError("source vectors fail mass normalization/orthogonality")
    frequencies = np.sqrt(a["eigenvalues"]) / (2 * np.pi)
    frequency_clusters(frequencies)
    tower = np.einsum("mnd,nd,mnd->m", v, a["tower_mass"] * ~fixed, v)
    line = np.einsum("mnd,nd,mnd->m", v, a["line_mass"] * ~fixed, v)
    ratio = np.einsum("mnd,nd->md", v, free)[:, :3] ** 2 / free.sum(axis=0)[:3]
    # Re-evaluate existing equation evidence by matrix multiplication, not eigensolution.
    from scipy.sparse import load_npz
    with np.load(directory / "equation_modes.npz", allow_pickle=False) as eq:
        k, m = load_npz(directory / "stiffness.npz"), load_npz(directory / "mass.npz")
        kv, mv = k @ eq["vectors"], (m @ eq["vectors"]) * eq["values"]
        residual = np.linalg.norm(kv - mv, axis=0) / (np.linalg.norm(kv, axis=0) + np.linalg.norm(mv, axis=0))
    if not np.isfinite(residual).all() or residual.max() > 1e-6:
        raise ValueError("saved eigen-equation residual exceeds project tolerance")
    a.update(summary=summary, frequencies=frequencies, tower_share=tower, cable_share=line,
             insulator_share=1 - tower - line, effective_ratios=ratio,
             orthogonality_max=float(np.max(np.abs(gram - np.eye(len(v))))),
             eigen_residual_max=float(residual.max()), directory=directory)
    return a


def read_lines(case):
    path = case["directory"] / "line_model/transmission_lines.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        if row["line_id"] in result:
            raise ValueError("duplicate physical line ID")
        result[row["line_id"]] = {"node_tags": ast.literal_eval(row["node_tags"]),
                                  "mass_per_length": float(row["mass_per_length"])}
    return result


def cable_station_vectors(case, reference_case, stations):
    lines, ref_lines = read_lines(case), read_lines(reference_case)
    if set(lines) != set(ref_lines):
        raise ValueError("physical spans differ across meshes")
    index = {int(tag): i for i, tag in enumerate(case["node_tags"])}
    ref_index = {int(tag): i for i, tag in enumerate(reference_case["node_tags"])}
    pieces, weights, records = [], [], []
    ds = np.diff(stations)
    trapezoid = np.r_[ds[0] / 2, (ds[:-1] + ds[1:]) / 2, ds[-1] / 2]
    for line_id in sorted(lines):
        row, ref = lines[line_id], ref_lines[line_id]
        if not np.isclose(row["mass_per_length"], ref["mass_per_length"], rtol=1e-12):
            raise ValueError("line density differs across comparison cases")
        indices = np.array([index[int(tag)] for tag in row["node_tags"]])
        ref_indices = np.array([ref_index[int(tag)] for tag in ref["node_tags"]])
        xyz = case["initial_coordinates"][indices]
        reference_xyz = reference_case["initial_coordinates"][ref_indices]
        if not np.allclose(xyz[[0, -1]], reference_xyz[[0, -1]], atol=1e-10, rtol=0):
            raise ValueError("span endpoints or ordering differ")
        v, length = interpolate_span_modes(xyz, case["vectors"][:, indices, :3], stations)
        ref_length = np.linalg.norm(np.diff(reference_xyz, axis=0), axis=1).sum()
        pieces.append(v.reshape(len(v), -1).T)
        weights.append(np.repeat(trapezoid * ref_length * ref["mass_per_length"], 3))
        records.append({"line_id": line_id, "initial_arc_length_m": length,
                        "reference_arc_length_m": float(ref_length), "mass_per_length_kg_m": row["mass_per_length"],
                        "stations": len(stations), "source_nodes": len(indices)})
    return np.concatenate(pieces, axis=0), np.concatenate(weights), records


def group_record(case_id, case, indices, label, tower_vectors, weights, refs, rank_tol):
    coverage, basis = projection_coverage(tower_vectors[:, indices], refs, weights, rank_tolerance=rank_tol)
    return {"case": case_id, "group": label, "mode_count": len(indices), "modes": (indices + 1).tolist(),
            "frequency_min_Hz": float(case["frequencies"][indices[0]]),
            "frequency_max_Hz": float(case["frequencies"][indices[-1]]),
            "tower_kinetic_trace": float(case["tower_share"][indices].sum()),
            "cable_kinetic_trace": float(case["cable_share"][indices].sum()),
            "insulator_kinetic_trace": float(case["insulator_share"][indices].sum()),
            "tower_trace_per_mode": float(case["tower_share"][indices].mean()),
            "effective_mass_ratio_X_sum": float(case["effective_ratios"][indices, 0].sum()),
            "effective_mass_ratio_Y_sum": float(case["effective_ratios"][indices, 1].sum()),
            "effective_mass_ratio_Z_sum": float(case["effective_ratios"][indices, 2].sum()),
            "tower_numerical_rank": basis["numerical_rank"],
            "reference_shape_coverage": dict(zip(("torsion", "X", "Y"), coverage.tolist()))}


def _csv(path, rows):
    if not rows:
        raise ValueError("cannot write empty diagnostic table")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def analyze(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    config = dict(DEFAULT_CONFIG)
    write_json(output / "frozen_config.json", config)
    cases = {key: load_case(source / "runs" / key) for key in CASES}
    bare = cases["bare_checked"]
    common_mass = (bare["mass"][:, :3] * ~bare["fixed"][:, :3]).ravel()
    refs = bare["vectors"][:3, :, :3].reshape(3, -1).T
    indices, tower_vectors, macs, output_cases, groups, candidates = {}, {}, {}, {}, [], []
    rank_tol = config["svd_relative_rank_tolerance"]
    for key, case in cases.items():
        order = common_node_indices(bare["node_tags"], case["node_tags"])
        if not np.allclose(case["tower_mass"][order, :3], bare["mass"][:, :3], rtol=1e-12, atol=1e-12):
            raise ValueError(f"common tower component mass differs: {key}")
        if not np.array_equal(case["fixed"][order], bare["fixed"]):
            raise ValueError(f"common tower constraints differ: {key}")
        if not np.allclose(case["initial_coordinates"][order], bare["initial_coordinates"], atol=1e-10, rtol=0):
            raise ValueError(f"common initial tower geometry differs: {key}")
        v = case["vectors"][:, order, :3].reshape(len(case["vectors"]), -1).T
        tower_vectors[key] = v
        mac = weighted_mac_matrix(refs, v, common_mass)
        macs[key] = mac
        window, info = complete_cluster_window(case["frequencies"], *config["frequency_window_Hz"], config["relative_cluster_gap"])
        indices[key] = window
        window_record = group_record(key, case, window, "tower_frequency_window", v, common_mass, refs, rank_tol)
        window_record["window"] = info
        groups.append(window_record)
        representatives, families = [], []
        for ref_mode, label in enumerate(("torsion", "X", "Y")):
            best = int(np.argmax(mac[ref_mode] * case["tower_share"]))
            representatives.append({"reference_mode": ref_mode + 1, "label": label, "mode": best + 1,
                                   "frequency_Hz": float(case["frequencies"][best]), "MAC": float(mac[ref_mode, best]),
                                   "tower_kinetic_share": float(case["tower_share"][best]),
                                   "effective_mass_ratio_X": float(case["effective_ratios"][best, 0]),
                                   "frequency_change_from_bare_percent": float((case["frequencies"][best] / bare["frequencies"][ref_mode] - 1) * 100)})
            family = window[(mac[ref_mode, window] >= config["family_MAC_min"]) &
                            (case["tower_share"][window] >= config["family_tower_share_min"])]
            if len(family):
                family_row = group_record(key, case, family, f"{label}_shape_family_screen", v, common_mass, refs, rank_tol)
                families.append(family_row); groups.append(family_row)
        for mode in range(len(case["vectors"])):
            candidates.append({"case": key, "mode": mode + 1, "frequency_Hz": float(case["frequencies"][mode]),
                               "inside_complete_window": bool(mode in window),
                               "tower_kinetic_share": float(case["tower_share"][mode]),
                               "cable_kinetic_share": float(case["cable_share"][mode]),
                               "insulator_kinetic_share": float(case["insulator_share"][mode]),
                               "MAC_bare_torsion": float(mac[0, mode]), "MAC_bare_X": float(mac[1, mode]),
                               "MAC_bare_Y": float(mac[2, mode]),
                               **{f"effective_mass_ratio_{axis}": float(case["effective_ratios"][mode, j]) for j, axis in enumerate("XYZ")}})
        low_groups = []
        if key != "bare_checked":
            for cluster in frequency_clusters(case["frequencies"], config["relative_cluster_gap"]):
                if cluster[0] >= 6:
                    break
                row = group_record(key, case, cluster, f"low_frequency_cluster_{len(low_groups) + 1}", v, common_mass, refs, rank_tol)
                low_groups.append(row);groups.append(row)
        output_cases[key] = {"segments_per_span": case["summary"]["segments_per_span"],
                             "saved_modes": len(case["vectors"]),
                             "highest_saved_frequency_Hz": float(case["frequencies"][-1]),
                             "source_state": case["summary"]["state"],
                             "eigen_equation_relative_residual_max": case["eigen_residual_max"],
                             "mass_orthogonality_error_max": case["orthogonality_max"],
                             "window": window_record, "representative_tower_modes": representatives,
                             "shape_families": families, "low_frequency_clusters": low_groups}
    stations = np.linspace(0, 1, config["cable_station_count_per_span"])
    cable_vectors, cable_weights, cable_records = {}, None, {}
    for key in CASES[1:]:
        cable_vectors[key], weights, cable_records[key] = cable_station_vectors(cases[key], cases[CASES[-1]], stations)
        if cable_weights is not None and not np.array_equal(cable_weights, weights):
            raise ValueError("cable quadrature weights not identical")
        cable_weights = weights
    comparisons = []
    for left, right in zip(CASES[1:-1], CASES[2:]):
        a, b = cases[left], cases[right]
        full = compare_subspaces(tower_vectors[left][:, indices[left]], tower_vectors[right][:, indices[right]],
                                 common_mass, rank_tolerance=rank_tol)
        dominant = compare_subspaces(tower_vectors[left][:, indices[left]], tower_vectors[right][:, indices[right]],
                                     common_mass, rank_tolerance=rank_tol,
                                     energy_retention=config["dominant_tower_energy_retention"])
        low_a = np.array([mode - 1 for row in output_cases[left]["low_frequency_clusters"] for mode in row["modes"]])
        low_b = np.array([mode - 1 for row in output_cases[right]["low_frequency_clusters"] for mode in row["modes"]])
        low_cable = compare_subspaces(cable_vectors[left][:, low_a], cable_vectors[right][:, low_b], cable_weights,
                                      rank_tolerance=rank_tol)
        window_cable = compare_subspaces(cable_vectors[left][:, indices[left]], cable_vectors[right][:, indices[right]],
                                         cable_weights, rank_tolerance=rank_tol)
        reps_a, reps_b = output_cases[left]["representative_tower_modes"], output_cases[right]["representative_tower_modes"]
        representative_changes = [{"label": aa["label"], "frequency_relative_change": bb["frequency_Hz"] / aa["frequency_Hz"] - 1,
                                   "tower_share_change_percentage_points": 100 * (bb["tower_kinetic_share"] - aa["tower_kinetic_share"]),
                                   "from_mode": aa["mode"], "to_mode": bb["mode"]} for aa, bb in zip(reps_a, reps_b)]
        low_freq_change = float(np.max(np.abs(b["frequencies"][:6] / a["frequencies"][:6] - 1)))
        comparisons.append({"from": left, "to": right, "tower_subspace": full,
                            "dominant_tower_subspace": dominant, "cable_low_frequency_subspace": low_cable,
                            "cable_window_subspace": window_cable,
                            "representative_changes": representative_changes,
                            "first_six_frequency_max_relative_change": low_freq_change,
                            "low_frequency_shape_and_frequency_pass": bool(low_cable["same_retained_rank"] and
                                low_cable["minimum_principal_cosine_squared"] >= config["minimum_principal_cosine_squared"] and
                                low_freq_change <= config["relative_frequency_change_max"]),
                            "full_window_shape_pass": bool(full["same_retained_rank"] and
                                full["minimum_principal_cosine_squared"] >= config["minimum_principal_cosine_squared"] and
                                window_cable["same_retained_rank"] and window_cable["minimum_principal_cosine_squared"] >= config["minimum_principal_cosine_squared"]),
                            "forced_response_convergence_certified": False})
    source_paths = [Path(__file__)]
    for case in cases.values():
        source_paths.extend(case["directory"] / f for f in ["eigenvectors.npz", "summary.json", "equation_modes.npz", "stiffness.npz", "mass.npz"])
        if case["summary"]["segments_per_span"]:
            source_paths.append(case["directory"] / "line_model/transmission_lines.csv")
    summary = {"schema": "otw2.modal_group_diagnostics.v1", "execution_status": "complete", "assessment": "limited",
               "physical_validation": "unvalidated", "new_FE_runs": 0, "new_eigen_solves": 0,
               "created_at_utc": datetime.now(timezone.utc).isoformat(), "configuration": config,
               "case_order": list(CASES), "cases": output_cases, "mesh_comparisons": comparisons,
               "common_tower_nodes": len(bare["node_tags"]), "positive_weight_tower_translation_dofs": int(np.count_nonzero(common_mass)),
               "cable_station_mapping": cable_records,
               "limitations": ["Tower subspace shape similarity does not establish force-response or truncation convergence.",
                               "Fixed 160 modes cover different frequency bands on the three cable grids.",
                               "Shape-family filtering is a labelled diagnostic; every saved mode is retained in candidate_modes.csv.",
                               "Group kinetic traces are basis-invariant sums, not percentages; trace per mode is diagnostic only.",
                               "Cable interpolation compares saved piecewise-linear fields and does not add new FE accuracy.",
                               "No new wind transient, damping validation, physical angle-member validation, or engineering capacity is claimed."],
               "inputs": [fingerprint(p) for p in source_paths],
               "runtime_seconds": time.monotonic() - started}
    _csv(output / "candidate_modes.csv", candidates)
    # All group rows share common fields; window-specific info is kept in JSON.
    _csv(output / "modal_groups.csv", [{k: v for k, v in row.items() if k != "window"} for row in groups])
    write_json(output / "subspace_checks.json", {"schema": "otw2.modal_subspace_checks.v1", "configuration": config,
                                                "comparisons": comparisons})
    plot_results(summary, candidates, output)
    write_report(summary, output)
    summary["artifacts"] = [p.name for p in sorted(output.iterdir()) if p.is_file()] + ["summary.json"]
    write_json(output / "summary.json", summary)
    (output / "execution_log.md").write_text(
        "# N02 实际执行记录\n\n1. 冻结窗口、近重根、SVD与公共导线站点配置。\n"
        "2. 读取四个checked工况float64振型及K/M；仅矩阵乘法复核残差，无新特征值求解。\n"
        "3. 按原始塔节点映射，核查质量、约束和初始坐标，计算全部模态MAC。\n"
        "4. 对完整频窗、目标形状族、低频近重根计算组迹量和子空间。\n"
        "5. 将四跨模态按初始弧长插值到161公共站点，采用统一80段参考质量积分权。\n"
        "6. 比较20→40→80，输出全部候选、组表、科学图与适用边界。\n\n"
        f"运行时长：{summary['runtime_seconds']:.3f} s（主体分析，不含后续独立单元测试）。\n"
        "新FE：0；新特征值求解：0；旧结果未写入。具体测试命令/结果另存validation。\n", encoding="utf-8")
    return summary


def plot_results(summary, candidates, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = ["20 segments", "40 segments", "80 segments"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), constrained_layout=True)
    for ax, key, label in zip(axes, CASES[1:], labels):
        rows = [r for r in candidates if r["case"] == key and r["inside_complete_window"]]
        for row in rows:
            color = "#de6a32" if row["MAC_bare_X"] >= .9 else "#55778b"
            ax.vlines(row["frequency_Hz"], 0, row["tower_kinetic_share"], color=color, alpha=.75,
                      linewidth=1.3 if row["MAC_bare_X"] >= .9 else .7)
        ax.set(xlabel="Frequency (Hz)", xlim=(1.8, 2.7), ylim=(0, 1.05), title=label,
               ylabel="Single-mode tower kinetic share")
        ax.grid(alpha=.2)
    fig.suptitle("Same frequency window; orange: tower-X MAC >= 0.9 (all candidates retained)")
    _save_figure(fig, output, "tower_modal_group_distribution")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    x = np.array([20, 40, 80])
    share = [summary["cases"][k]["representative_tower_modes"][1]["tower_kinetic_share"] * 100 for k in CASES[1:]]
    family = [next(r for r in summary["cases"][k]["shape_families"] if r["group"] == "X_shape_family_screen")["tower_kinetic_trace"] for k in CASES[1:]]
    axes[0].plot(x, share, "o-", color="#be4b37");axes[0].set(xlabel="Segments per span", ylabel="Selected X-mode tower share (%)", xticks=x)
    axes[1].plot(x, family, "o-", color="#217e92");axes[1].set(xlabel="Segments per span", ylabel="X-family tower kinetic trace (sum)", xticks=x)
    for ax in axes:ax.grid(alpha=.25)
    fig.suptitle("A selected mode redistributes participation; group trace is not a response prediction")
    _save_figure(fig, output, "selected_vs_group_tower_participation")
    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    for comparison, label in zip(summary["mesh_comparisons"], ["20 to 40", "40 to 80"]):
        values = comparison["cable_low_frequency_subspace"]["principal_cosines_squared"]
        ax.plot(np.arange(1, len(values) + 1), values, "o-", label=label)
    ax.set(xlabel="Principal-angle index, first six cable modes as a group", ylabel="Squared cosine", ylim=(.98, 1.001))
    ax.grid(alpha=.25);ax.legend();ax.set_title("Common-arc cable shape comparison; frequency/response limits reported separately")
    _save_figure(fig, output, "low_frequency_cable_subspace")


def _save_figure(fig, output, stem):
    import matplotlib.pyplot as plt
    for suffix in ("svg", "png", "pdf"):
        fig.savefig(output / f"{stem}.{suffix}", dpi=160)
    plt.close(fig)


def write_report(summary, output):
    cases = summary["cases"]
    lines = ["# N02 成组模态与公共坐标复核", "", "本项只读取已有四个checked工况；新FE和新特征值求解均为0。当前评估为 limited，物理验证仍为 unvalidated。", "",
             "## 实际方法与数据", "", "使用float64原始六自由度振型，重算质量正交和特征方程残差。共同塔节点平动质量作为内积；1.8～2.7Hz窗口与0.1%近重根规则运行前冻结。完整SVD采用1e−10相对秩阈值，另报告保留99.9%塔体迹量的主导子空间，不以其替代完整子空间。", "",
             "全部保存模态均在candidate_modes.csv中；X形状族使用MAC≥0.9且塔体份额≥0.005作标记。形状族不是任意风激励下的响应参与率。四跨导线按归一化初始弧长插值到每跨161站点，并统一采用80段参考弧长/线密度的梯形积分权。", "",
             "## 工况与单阶/成组结果", "", "| 网格 | 窗口内模态数 | 塔体数值秩 | 代表X频率/Hz | 代表X塔体份额 | X族塔体迹量 | X族模式 |", "|---|---:|---:|---:|---:|---:|---|"]
    for key in CASES[1:]:
        c = cases[key];x = c["representative_tower_modes"][1];family = next(r for r in c["shape_families"] if r["group"] == "X_shape_family_screen")
        lines.append(f"| {c['segments_per_span']} | {c['window']['mode_count']} | {c['window']['tower_numerical_rank']} | {x['frequency_Hz']:.6f} | {100*x['tower_kinetic_share']:.4f}% | {family['tower_kinetic_trace']:.6f} | {family['modes']} |")
    lines += ["", "组迹量是全质量归一化模态的塔体分量之和，可以大于1；不是百分比。完整频窗包含不同数量的线模态，不能把trace/mode-count变化直接解释为实际能量转移。", "", "## 相邻网格比较", ""]
    for c in summary["mesh_comparisons"]:
        full, dom, low, cable = [c[k] for k in ("tower_subspace", "dominant_tower_subspace", "cable_low_frequency_subspace", "cable_window_subspace")]
        x = c["representative_changes"][1]
        lines.extend([f"### {c['from']} → {c['to']}", "",
                      f"- 代表X频率变化 {100*x['frequency_relative_change']:+.4f}%；单阶塔体份额变化 {x['tower_share_change_percentage_points']:+.4f} 个百分点。",
                      f"- 完整频窗塔子空间秩 {full['a']['retained_rank']}→{full['b']['retained_rank']}，最小主夹角余弦平方 {full['minimum_principal_cosine_squared']:.6g}；双向投影残差 {full['a_to_b_normalized_projection_residual']:.6g}/{full['b_to_a_normalized_projection_residual']:.6g}。",
                      f"- 主导99.9%塔体迹量子空间秩 {dom['a']['retained_rank']}→{dom['b']['retained_rank']}，最小余弦平方 {dom['minimum_principal_cosine_squared']:.6g}（仅主导塔体形状诊断）。",
                      f"- 首六阶导线公共弧长子空间秩 {low['a']['retained_rank']}→{low['b']['retained_rank']}，最小余弦平方 {low['minimum_principal_cosine_squared']:.9f}；首六阶最大频率变化 {100*c['first_six_frequency_max_relative_change']:.5f}%。",
                      f"- 1.8～2.7Hz导线子空间秩 {cable['a']['retained_rank']}→{cable['b']['retained_rank']}，最小余弦平方 {cable['minimum_principal_cosine_squared']:.6g}。完整窗口形状门槛通过：{c['full_window_shape_pass']}；低频形状/频率门槛通过：{c['low_frequency_shape_and_frequency_pass']}。", ""])
    lines += ["## 适用结论与下一步", "",
              "1. 单阶MAC接近1且频率接近，只说明所选塔体形状相似；不能据此忽略附近多个耦合模态。组表和全部候选已公开。",
              "2. 公共塔DOF上的参考形状覆盖、主导塔子空间与导线公共站点子空间分别报告；秩不一致或遗漏方向时不判成完全相同。",
              "3. 低频组形状/频率通过只适用于这组无风重力态特征，不代表160阶截断、整个窗口或实际风响应通过。",
              "4. 下一步应将N03实际空间风荷载与指定响应投影结果结合，决定N06是否需要扩阶/加密；本项不单独宣布80段或160阶已收敛。",
              "5. 未进行阻尼实施、风时程、角钢物理标定和工程容量验证。塔与线的质量迹量也不是加载后的振动能量或风参与率。", "",
              "## 输出与复现", "", "`summary.json`为集成入口；`subspace_checks.json`保留主角度和全部奇异值；`modal_groups.csv`和`candidate_modes.csv`可逐行复核。三组图均有SVG/PNG/PDF。", "",
              "```bash", "OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.modal_diagnostics \\",
              "  --output initial_imperfection_material/tian_ma_qu/followup_results/<new_unique_batch>/modal", "```", "",
              "输出目录已有文件时拒绝覆盖。执行器不导入OpenSees，也不构造或求解任何新FE域。测试与执行日志存于本输出目录。", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).with_name("modal_results"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = analyze(args.source, args.output)
    print(json.dumps({"assessment": summary["assessment"], "cases": list(summary["cases"]),
                      "new_FE_runs": 0, "runtime_seconds": summary["runtime_seconds"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
