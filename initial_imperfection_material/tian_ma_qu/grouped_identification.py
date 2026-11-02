"""Evidence-gated, staged TMQ identification of complete ordered histories.

The optimizer never estimates E, fy, A or L. Every stage replays the whole
history from its verified initial state; a stage mask only selects residuals.
Unordered scans and elastic-only records cannot calibrate postbuckling laws.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from .material import TMQParameters
from .parameter_identification import (
    Bound, decode, genetic_minimize, ordered_data, response, write_json, write_csv,
)

STAGE_PARAMETERS = {
    "first_compression": {"phi", "alpha", "beta", "gamma"},
    "unload_reload": {"tau", "mu", "nu", "zeta", "rho"},
    "subsequent_compression": {"eta", "theta", "kappa"},
}
CHECKS = ("E", "fy", "geometry", "boundary", "displacement", "initial_state", "order", "phases", "group")


def admission_reasons(manifest, *, evidence_policy="strict"):
    """Return explicit missing evidence, without correcting or reordering data."""
    errors = []
    if evidence_policy not in ("strict", "conditional_nominal_geometry"):
        raise ValueError("Unknown evidence policy")
    if manifest.get("data_kind") != "experiment":
        errors.append("Only experimental evidence can enter this physical-identification workflow")
    verification = manifest.get("verification", {})
    for key in CHECKS:
        check = verification.get(key, {})
        if check.get("status") != "verified" or not str(check.get("source_reference", "")).strip():
            errors.append(f"Unverified {key}")
    for key in ("E", "fy"):
        if verification.get(key, {}).get("basis") != "measured_coupon":
            errors.append(f"{key} must be fixed from a measured coupon, not inferred from member stiffness")
    geometry_basis = verification.get("geometry", {}).get("basis")
    if geometry_basis != "measured_specimen":
        if evidence_policy != "conditional_nominal_geometry" or geometry_basis != "reported_nominal":
            errors.append("Strict geometry admission needs measured specimen dimensions; nominal geometry needs explicit conditional policy")
        elif not manifest.get("conditions"):
            errors.append("Conditional nominal geometry requires explicit limitations")
    if verification.get("order", {}).get("basis") not in (
        "instrument_sequence", "author_sequence", "curator_sequence_crosschecked",
    ):
        errors.append("Unordered scan points or unreviewed curator row order are not an admitted loading history")
    try:
        ordered_data(manifest)
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    if not manifest.get("group_key"):
        errors.append("Missing reviewed group_key")
    return errors


def require_admitted(manifest, *, evidence_policy="strict"):
    errors = admission_reasons(manifest, evidence_policy=evidence_policy)
    if errors:
        raise ValueError("; ".join(errors))
    return ordered_data(manifest)


def phase_mask(data, stage):
    if stage not in STAGE_PARAMETERS:
        raise ValueError("Unknown identification stage")
    return np.array([row.get("phase") == stage for row in data["manifest"]["samples"]])


def require_excitation(data, stage, names):
    """Conservative observable checks, in addition to a source-reviewed phase map."""
    mask = phase_mask(data, stage)
    indices = np.flatnonzero(mask)
    if len(indices) < 6:
        raise ValueError(f"{stage}: at least six reviewed observations required")
    u, f = data["displacement_m"][mask], data["force_N"][mask]
    noise = float(data["manifest"].get("force_resolution_N", 0.))
    if not np.isfinite(noise) or noise <= 0:
        raise ValueError("Positive force_resolution_N required for excitation checks")
    if stage in ("first_compression", "subsequent_compression"):
        # A loading leg must be contiguous and move into compression. Reversed
        # displacement samples must first be resolved by source review, not sorted.
        resolution = float(data["manifest"].get("displacement_resolution_m", 0.))
        if not np.isfinite(resolution) or resolution < 0:
            raise ValueError("Invalid displacement resolution")
        # Allow only bounded coordinate quantization, without changing any point.
        backtrack = u-np.minimum.accumulate(u)
        if np.any(np.diff(indices) != 1) or np.any(backtrack > resolution+1e-12):
            raise ValueError("Compression phase must be one contiguous reviewed compression leg")
        peak = int(np.argmin(f))
        if peak < 1 or peak > len(f)-3 or f[peak] >= -5*noise:
            raise ValueError("No resolved interior compression peak and descending branch")
        if f[-1]-f[peak] <= max(5*noise, .05*abs(f[peak])):
            raise ValueError("Elastic-only or unresolved postbuckling record cannot identify softening")
        if stage == "first_compression" and indices[0] > 1:
            raise ValueError("First-compression calibration requires verified virgin compression-first history")
        if stage == "subsequent_compression":
            prior = phase_mask(data, "unload_reload")[:indices[0]]
            if not np.any(prior):
                raise ValueError("Subsequent buckling needs its preceding unloading/reloading history")
    else:
        if not np.any(phase_mask(data, "first_compression")[:indices[0]]):
            raise ValueError("Unloading/reloading must follow the initial buckling leg")
        if f.min() >= -5*noise or f.max() <= 5*noise:
            raise ValueError("Unloading/reloading must resolve both compression and tension")
        if "rho" in names and f.max() <= data["area_m2"]*data["manifest"]["yield_stress_Pa"]+5*noise:
            raise ValueError("rho requires resolved tensile postyield observations")
    return mask


def stage_residual(parameters, data, mask):
    """Advance through every earlier reversal, even when it is not scored."""
    if len(mask) != len(data["strain"]) or not np.any(mask):
        raise ValueError("A nonempty complete-history mask is required")
    last = int(np.flatnonzero(mask)[-1])+1
    # Replay every preceding sample. Future observations cannot affect a causal
    # stage objective; evaluate those separately in the complete-history check.
    predicted = response(parameters, data["strain"][:last])*data["area_m2"]
    weights = data["weights"][mask]
    weights = weights/weights.sum()
    scale = max(float(np.max(np.abs(data["force_N"]))), 1.)
    return (predicted[mask[:last]]-data["force_N"][mask])*np.sqrt(weights)/scale


def _signature(data):
    m = data["manifest"]
    return (m["group_key"], m["elastic_modulus_Pa"], m["yield_stress_Pa"], m["area_m2"], m["length_m"])


def _sensitivity(residual, genes):
    columns = []
    for i in range(len(genes)):
        low, high = genes.copy(), genes.copy()
        low[i], high[i] = max(0., genes[i]-1e-4), min(1., genes[i]+1e-4)
        columns.append((residual(high)-residual(low))/(high[i]-low[i]))
    singular = np.linalg.svd(np.column_stack(columns), compute_uv=False)
    rank = int(np.count_nonzero(singular > max(1e-8, singular[0]*1e-6)))
    return {"local_rank": rank, "parameter_count": len(genes), "singular_values": singular.tolist(),
            "interpretation": "local numerical sensitivity only; not a confidence interval or physical validation"}


def fit_group(training, holdout, template, stages, *, seeds=(17, 29, 43), population=28,
              generations=35, timeout_seconds=90., evidence_policy="strict"):
    """Fit reviewed identical-geometry groups; held-out specimens never score GA.

    This conservative first implementation requires equal frozen E/fy/A/L within
    each group. Pooling different lengths or end details requires a separate,
    validated parameter scaling model, and is deliberately not implicit here.
    """
    from scipy.optimize import least_squares
    if not seeds:
        raise ValueError("At least one declared random seed required")
    if not training or not holdout:
        raise ValueError("Separate training and held-out specimens required")
    train = [require_admitted(m, evidence_policy=evidence_policy) for m in training]
    test = [require_admitted(m, evidence_policy=evidence_policy) for m in holdout]
    identifiers = [m["specimen_id"] for m in training+holdout]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate specimen or training/holdout leakage")
    if len({_signature(d) for d in train+test}) != 1:
        raise ValueError("Group must share reviewed boundary/section and identical fixed E, fy, A, L")
    m = training[0]
    if template.elastic_modulus != m["elastic_modulus_Pa"] or template.yield_stress != m["yield_stress_Pa"]:
        raise ValueError("Template E/fy differ from fixed measured properties")
    if [s["name"] for s in stages] != list(STAGE_PARAMETERS):
        raise ValueError("Run first compression, unload/reload, then subsequent compression in that order")
    p, results, masks = template, [], {}
    # Check the full plan before invoking the optimizer, including later stages.
    for stage in stages:
        name = stage["name"]
        bounds = [Bound(**b) for b in stage["bounds"]]
        names = [b.name for b in bounds]
        if not names or len(set(names)) != len(names) or not set(names) <= STAGE_PARAMETERS[name]:
            raise ValueError("Stage bounds must contain only its identifiable coefficients; E/fy/geometry stay fixed")
        masks[name] = [require_excitation(d, name, names) for d in train]
        lim = {b.name: (b.lower, b.upper) for b in bounds}
        if lim.get("mu", (p.mu, p.mu))[1] >= lim.get("nu", (p.nu, p.nu))[0]:
            raise ValueError("Search rectangle must preserve nu > mu")
        if lim.get("gamma", (p.gamma, p.gamma))[0] <= p.residual_compression_ratio:
            raise ValueError("Search rectangle must preserve gamma > residual ratio")
        for b in bounds:
            decode(p, [b], [0.]); decode(p, [b], [1.])
    for stage in stages:
        name = stage["name"]
        bounds = [Bound(**b) for b in stage["bounds"]]
        fixed = p
        def residual(genes):
            q = decode(fixed, bounds, genes)
            return np.concatenate([stage_residual(q, d, mask)/np.sqrt(len(train))
                for d, mask in zip(train, masks[name])])
        def objective(genes):
            r = residual(genes)
            return float(r @ r)
        runs = []
        for seed in seeds:
            ga = genetic_minimize(objective, len(bounds), seed=seed, population=population,
                generations=generations, timeout_seconds=timeout_seconds)
            polished = least_squares(residual, ga["genes"], bounds=(np.zeros(len(bounds)), np.ones(len(bounds))),
                                     max_nfev=100, ftol=1e-9, xtol=1e-9, gtol=1e-9)
            genes = polished.x if float(polished.fun @ polished.fun) <= ga["objective"] else np.array(ga["genes"])
            runs.append({"ga": ga, "genes": genes.tolist(), "objective": objective(genes),
                         "local_refinement_success": bool(polished.success)})
        best = min(runs, key=lambda r: r["objective"])
        p = replace(decode(fixed, bounds, best["genes"]), provenance=
            f"Staged experimental candidate; group={m['group_key']}; training={','.join(x['specimen_id'] for x in training)}; non-production")
        diagnostic = _sensitivity(residual, np.array(best["genes"]))
        result = {"stage": name, "fitted_names": [b.name for b in bounds], "parameters": p.to_dict(),
                  "training_nrmse": float(np.sqrt(best["objective"])), "runs": runs, "sensitivity": diagnostic}
        results.append(result)
        if diagnostic["local_rank"] < len(bounds):
            return {"status": "nonidentifiable_stage", "stages": results,
                    "evidence_policy": evidence_policy,
                    "strict_geometry_admitted": evidence_policy == "strict",
                    "template_parameters": template.to_dict(),
                    "full_hysteresis_validation": False, "production_parameters_changed": False}
    # Evaluate holdout only after the entire frozen optimization plan is finished.
    predictions, scores = {}, []
    for role, datasets in (("training", train), ("holdout", test)):
        for d in datasets:
            pred = response(p, d["strain"])*d["area_m2"]
            scale = max(float(np.max(np.abs(d["force_N"]))), 1.)
            scores.append({"role": role, "specimen_id": d["manifest"]["specimen_id"],
                "full_history_nrmse": float(np.sqrt(np.dot(d["weights"], ((pred-d["force_N"])/scale)**2)))})
            predictions[d["manifest"]["specimen_id"]] = pred.tolist()
    return {"status": "candidate_evaluated_not_automatically_validated", "stages": results,
            "evidence_policy": evidence_policy, "strict_geometry_admitted": evidence_policy == "strict",
            "best_parameters": p.to_dict(), "scores": scores, "predictions_N": predictions,
            "fixed_properties": {key: m[key] for key in ("elastic_modulus_Pa", "yield_stress_Pa", "area_m2", "length_m")},
            "template_parameters": template.to_dict(),
            "full_hysteresis_validation": False, "production_parameters_changed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="Frozen plan referencing reviewed history manifests")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    plan = json.loads(args.plan.read_text())
    manifests = {}
    for role in ("training", "holdout"):
        manifests[role] = [json.loads((args.plan.parent/path).read_text()) for path in plan[role]]
        for m in manifests[role]:
            require_admitted(m, evidence_policy=plan.get("evidence_policy", "strict"))
    args.output.mkdir(parents=True)
    write_json(args.output/"frozen_plan.json", plan)
    write_json(args.output/"input_hashes.json", {m["specimen_id"]: hashlib.sha256(
        json.dumps(m, sort_keys=True, allow_nan=False).encode()).hexdigest() for role in manifests for m in manifests[role]})
    try:
        fit = fit_group(manifests["training"], manifests["holdout"], TMQParameters(**plan["template"]),
                        plan["stages"], evidence_policy=plan.get("evidence_policy", "strict"), **plan.get("optimizer", {}))
        predictions = fit.pop("predictions_N", {})
        for role, rows in manifests.items():
            for m in rows:
                if m["specimen_id"] not in predictions:
                    continue
                data = ordered_data(m)
                # Use an index as filename; untrusted specimen labels never become paths.
                filename = f"{role}_{rows.index(m):02d}_predictions.csv"
                write_csv(args.output/filename, [{"sequence": float(i), "displacement_m": float(u),
                    "observed_force_N": float(o), "predicted_force_N": float(f)} for i, u, o, f in zip(
                    data["sequence"], data["displacement_m"], data["force_N"], predictions[m["specimen_id"]])])
        write_json(args.output/"summary.json", fit)
        print(json.dumps({"output": str(args.output), "status": fit["status"]}))
    except Exception as exc:
        write_json(args.output/"failure.json", {"type": type(exc).__name__, "message": str(exc)})
        raise


if __name__ == "__main__":
    main()
