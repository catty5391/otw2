"""Conditional TMQ calibration against author-ordered Carden P/Q plot paths.

E and fy come from measured coupons. Geometry is explicitly nominal, displacement
is actuator displacement, and samples are PDF polyline vertices, not instrument
timestamps. All plotting moves must be continuous; no displacement sorting occurs.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from .cases import literature_cases
from .grouped_identification import CHECKS, admission_reasons, fit_group
from .material import TMQParameters
from .parameter_identification import ROOT, KIP_N, Bound, fit_ordered_history, ordered_data, response, write_json, write_csv

SOURCE = "https://www.eng.buffalo.edu/mceer-reports/08/08-0002.pdf"
JOURNAL = "https://ej.aisc.org/index.php/engj/article/download/875/874"
PDF_SHA256 = "420f3d5bc93e1b0638f6d5c81e82395b341c063578f8d10d355c42991625815d"
LITERATURE = ROOT/"literature/tmq_ordered_history_20261026"
PDF = LITERATURE/"papers/02_Carden_Itani_Buckle_2008_MCEER_08_0002.pdf"
OUTPUT = Path(__file__).parent/"followup_results/carden_conditional_20261026"
X_MM_PER_PT = 6*25.4/313.2
Y_N_PER_PT = 50*KIP_N/193.92
NOMINAL_AREA = (2*1*.1875-.1875**2)*.0254**2
NOMINAL_LENGTH = 25.4*.0254


def path_points(path):
    """Read a PDF line path; reject every disconnected pen move or other operator."""
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    token = re.compile(rf"({number})\s+({number})\s+([ml])")
    triples = []
    last = 0
    for match in token.finditer(path):
        if path[last:match.start()].strip():
            raise ValueError("Unsupported path operator; no inferred point order")
        triples.append((float(match[1]), float(match[2]), match[3]))
        last = match.end()
    if path[last:].strip() or len(triples) < 3 or triples[0][2] != "m":
        raise ValueError("Invalid continuous line path")
    for previous, current in zip(triples, triples[1:]):
        if current[2] == "m" and previous[:2] != current[:2]:
            raise ValueError("Disconnected author path cannot be joined into a history")
    return triples


def export_vectors(pdf=PDF, target=LITERATURE/"raw"):
    """Optional PDF reader is needed only for this source extraction step."""
    import pymupdf
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest() != PDF_SHA256:
        raise ValueError("Unreviewed PDF: page/axes mapping is valid only for the verified original")
    target = Path(target); target.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    page = doc[100]
    if page.get_xobjects():
        raise ValueError("Unexpected embedded-form transform")
    content = page.read_contents().decode("latin1")
    pattern = re.compile(r"(?P<ctm>[-+\d.eE\s]+)cm\s+(?P<path>[-+\d.eE\sml]+)S\s+Q")
    paths = [m for m in pattern.finditer(content) if m["path"].count("l") > 100]
    if len(paths) != 2:
        raise ValueError("Expected exactly P and Q author traces on PDF page 101")
    for specimen, match, expected, first_direction in zip(("P", "Q"), paths, (5397, 4192), (-1, 1)):
        matrix = [float(x) for x in match["ctm"].split()]
        if len(matrix) != 6 or matrix[:4] != [1., 0., 0., 1.]:
            raise ValueError("Unexpected source path transform")
        triples = path_points(match["path"])
        if len(triples) != expected or triples[0][:2] != (0., 0.):
            raise ValueError("Unexpected original trace or nonzero source path origin")
        values = np.array([p[:2] for p in triples])
        first_motion = next(float(x) for x in values[:, 0] if x != 0.)
        if first_motion*first_direction <= 0:
            raise ValueError("Trace order disagrees with original Table 3-2 first direction")
        destination = target/f"carden_{specimen}_vector.json"
        if destination.exists():
            raise FileExistsError(destination)
        write_json(destination, {"source": SOURCE, "source_sha256": PDF_SHA256,
            "pdf_page": 101, "printed_page": 71, "figure": "3-24" if specimen == "P" else "3-25",
            "specimen": specimen, "transform": matrix, "vertices": triples,
            "path_sha256": hashlib.sha256(match["path"].encode()).hexdigest(),
            "move_count": sum(p[2] == "m" for p in triples), "disconnected_moves": 0,
            "origin_basis": "author path start is re-zeroed; relative to drawn force-zero axis P starts +0.24 PDF pt and Q -0.96 PDF pt; Q offset exceeds one stroke width; this is not an instrument-zero verification",
            "axis_scales": {"x_mm_per_pdf_point": X_MM_PER_PT, "y_N_per_pdf_point": Y_N_PER_PT},
            "line_width_pdf_points": .543, "instrument_timestamps_available": False})
    doc.close()


def turning_points(u, direction, tolerance=.75):
    """Locate source-path reversals; do not sort, smooth, or resample the path."""
    if tolerance <= 0 or direction not in (-1, 1):
        raise ValueError("Positive reversal tolerance and initial direction required")
    extreme, indices = 0, []
    for index in range(1, len(u)):
        if direction*(u[index]-u[extreme]) >= 0:
            extreme = index
        elif -direction*(u[index]-u[extreme]) >= tolerance:
            indices.append(extreme)
            direction = -direction
            extreme = index
    return indices


def manifest_from_vector(vector):
    if vector["source_sha256"] != PDF_SHA256 or vector["disconnected_moves"] != 0:
        raise ValueError("Unreviewed vector evidence")
    xy = np.array([p[:2] for p in vector["vertices"]])
    u = xy[:, 0]*X_MM_PER_PT
    f = xy[:, 1]*Y_N_PER_PT
    specimen = vector["specimen"]
    turns = turning_points(u, -1 if specimen == "P" else 1)
    if specimen == "P" and turns[:3] != [112, 313, 522]:
        raise ValueError("First three reviewed P legs changed")
    verification = {k: {"status": "verified", "source_reference": SOURCE} for k in CHECKS}
    for key in ("E", "fy"):
        verification[key].update(basis="measured_coupon", source_reference=SOURCE+"; Table 3-1, printed p55 / PDF85, batch3")
    verification["geometry"].update(basis="reported_nominal", source_reference=JOURNAL+"; Table1, p112/PDF2, 1x1x3/16 in, 25.4 in")
    verification["order"].update(basis="author_sequence", source_reference=
        SOURCE+"; Fig3-24/25, p71/PDF101: continuous original vector path; zero start; Table3-2 first direction; no joins")
    verification["displacement"]["source_reference"] = JOURNAL+"; p114/PDF4: actuator displacement and force; welded connection"
    verification["boundary"]["source_reference"] = SOURCE+"; Table3-2, Fig3-4: balanced welded angle-to-gusset, 1 in gusset nominal"
    verification["initial_state"]["source_reference"] = SOURCE+"; full author trace starts at its own local origin, Table3-2 first direction; path-start zeroing is conditional, P/Q force offsets from the drawn zero axis differ"
    verification["phases"]["source_reference"] = SOURCE+"; original PDF101 path indices and reversals crosschecked against Fig3-24/25"
    verification["group"]["source_reference"] = JOURNAL+"; Table1: P/Q same nominal geometry, connection and batch; different first directions"
    phases = ["validation_only"]*len(u)
    if specimen == "P":
        for i in range(len(u)):
            if i <= turns[0]: phases[i] = "first_compression"
            elif i <= turns[1]: phases[i] = "unload_reload"
            elif i <= turns[2]: phases[i] = "subsequent_compression"
    m = {"schema": "otw2.tmq_ordered_history.v1", "data_kind": "experiment", "specimen_id": "Carden_"+specimen,
        "source": SOURCE+"; Figure "+vector["figure"], "ordered": True,
        "ordering_evidence": "Unbroken author-drawn polyline order, not x sorting; all moveto joins coincide; first direction agrees with table",
        "group_key": "Carden_nominal_1x1x3_16_L25_4in_welded_batch3", "verification": verification,
        "elastic_modulus_Pa": 218e9, "yield_stress_Pa": 338e6, "length_m": NOMINAL_LENGTH, "area_m2": NOMINAL_AREA,
        "geometry_basis": "Reported nominal inch dimensions, sharp-corner area 2bt-t^2; measured member area unavailable",
        "material_property_basis": "Original measured same-heat ASTM A370 coupon, report Table3-1 batch3",
        "initial_state": "virgin_zero_load", "units": {"displacement": "mm", "force": "N", "sign": "tension_positive"},
        "force_resolution_N": .543*Y_N_PER_PT, "displacement_resolution_m": .543*X_MM_PER_PT/1000,
        "conditions": ["nominal sharp-corner A, not measured member area", "reported 25.4 in L, not independently measured gauge length",
            "actuator displacement includes assembly compliance", "author vector plotting sequence, not raw instrument times",
            "plot origin selected within grid/line-width precision; no reconstruction of unknown loading",
            "force friction was reported below 1 kip and ignored by original authors", "no fracture model in current TMQ prototype"],
        "source_vector": {k: v for k, v in vector.items() if k != "vertices"},
        "origin_uncertainty": {"x_origin_vs_grid_mm": 0.,
            "force_origin_vs_grid_N": (.24 if specimen == "P" else -.96)*Y_N_PER_PT,
            "force_origin_offset_pdf_points": .24 if specimen == "P" else -.96,
            "force_origin_exceeds_one_stroke_width": specimen == "Q",
            "axis_reference": "independently read drawn zero axes on original PDF page101, audited 2026-10-28; x path origin coincides with vertical zero axis within PDF float rounding",
            "normalization": "source path start used as zero; Q vertical offset exceeds one stroke width; no source vertices or force/displacement arrays corrected"},
        "source_turning_indices": turns,
        "samples": [{"sequence": i, "displacement": float(x), "force": float(y), "phase": phase,
            "segment": sum(i > t for t in turns)} for i, (x, y, phase) in enumerate(zip(u, f, phases))]}
    return m


def run(output=OUTPUT, raw=LITERATURE/"raw"):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    vectors = {key: json.loads((Path(raw)/f"carden_{key}_vector.json").read_text()) for key in ("P", "Q")}
    manifests = {key: manifest_from_vector(v) for key, v in vectors.items()}
    data = {key: ordered_data(m) for key, m in manifests.items()}
    peak = -min(row["force"] for row in manifests["P"]["samples"] if row["phase"] == "first_compression")
    phi = peak/(NOMINAL_AREA*338e6)
    template = replace(literature_cases()[0].parameters, elastic_modulus=218e9, yield_stress=338e6, phi=phi,
        provenance="Carden batch3 measured E/fy; nominal A/L; phi from P first-leg peak; gamma=.5 zeta=.1 rho=.01 and starting cyclic coefficients are priors, not Carden calibration")
    plan = {"evidence_policy": "conditional_nominal_geometry", "training": ["P.json"], "holdout": ["Q.json"],
        "template": template.to_dict(), "phi_fixed_from_first_compression_peak_N": peak,
        "stages": [
            {"name": "first_compression", "bounds": [{"name": "alpha", "lower": .0005, "upper": .5, "scale": "log"}, {"name": "beta", "lower": .0005, "upper": .2, "scale": "log"}]},
            {"name": "unload_reload", "bounds": [{"name": "tau", "lower": .1, "upper": 6., "scale": "log"}, {"name": "mu", "lower": .02, "upper": .7, "scale": "log"}, {"name": "nu", "lower": .8, "upper": 6., "scale": "log"}]},
            {"name": "subsequent_compression", "bounds": [{"name": "eta", "lower": .2, "upper": .95}, {"name": "theta", "lower": .001, "upper": .2, "scale": "log"}, {"name": "kappa", "lower": .0001, "upper": .1, "scale": "log"}]}],
        "optimizer": {"seeds": [17, 29, 43], "population": 24, "generations": 24, "timeout_seconds": 90.},
        "frozen_before_fit": True, "holdout_used_for_optimization": False,
        "interpretation": "conditional experimental graph fit; not strict measured-geometry identification or physical validation"}
    output.mkdir(parents=True)
    for key, m in manifests.items(): write_json(output/f"{key}.json", m)
    write_json(output/"frozen_plan.json", plan)
    write_json(output/"input_hashes.json", {key: hashlib.sha256((output/f"{key}.json").read_bytes()).hexdigest() for key in manifests})
    try:
        result = fit_group([manifests["P"]], [manifests["Q"]], template, plan["stages"],
                          evidence_policy=plan["evidence_policy"], **plan["optimizer"])
        write_json(output/"fit.json", {k: v for k, v in result.items() if k != "predictions_N"})
        # A rank-deficient stage is not an identified parameter set. For diagnostic
        # full-curve plots revert its coefficients to the preceding accepted stage.
        accepted = [s for s in result["stages"] if s["sensitivity"]["local_rank"] == s["sensitivity"]["parameter_count"]]
        p = TMQParameters(**accepted[-1]["parameters"]) if accepted else template
        selected_basis = "stages_with_full_local_rank; remaining coefficients retain declared priors"
        metrics = []
        for key, d in data.items():
            predicted = response(p, d["strain"])*d["area_m2"]
            d["predicted_N"] = predicted
            error = (predicted-d["force_N"])/max(abs(d["force_N"]))
            metrics.append({"specimen": key, "role": "training" if key == "P" else "holdout",
                "full_history_nrmse": float(np.sqrt(np.dot(d["weights"], error**2))),
                "observed_min_N": float(min(d["force_N"])), "predicted_min_N": float(min(predicted)),
                "observed_max_N": float(max(d["force_N"])), "predicted_max_N": float(max(predicted)),
                "complete_observed_points": len(predicted)})
            write_csv(output/f"{key}_predictions.csv", [{"sequence": i, "displacement_m": float(x),
                "observed_force_N": float(y), "candidate_force_N": float(z), "phase": d["manifest"]["samples"][i]["phase"]}
                for i, (x, y, z) in enumerate(zip(d["displacement_m"], d["force_N"], predicted))])
        summary = {"schema": "otw2.tmq_carden_conditional.v1", "source": SOURCE, "source_sha256": PDF_SHA256,
            "status": result["status"], "strict_geometry_admitted": False, "conditional_nominal_geometry": True,
            "physical_validation": False, "production_parameters_changed": False, "raw_instrument_history_obtained": False,
            "training": "P", "holdout": "Q", "phi": phi, "peak_force_N": peak,
            "fixed_E_Pa": 218e9, "fixed_fy_Pa": 338e6, "nominal_area_m2": NOMINAL_AREA, "nominal_length_m": NOMINAL_LENGTH,
            "curve_metrics": metrics, "stages": [{k: s[k] for k in ("stage", "fitted_names", "training_nrmse", "sensitivity")} for s in result["stages"]],
            "diagnostic_parameters": p.to_dict(), "diagnostic_parameter_selection": selected_basis,
            "conditions": manifests["P"]["conditions"], "strict_admission_reasons": admission_reasons(manifests["P"])}
        write_json(output/"summary.json", summary)
        plot(output, data)
        print(json.dumps(summary, ensure_ascii=False))
        return summary
    except Exception as exc:
        write_json(output/"failure.json", {"type": type(exc).__name__, "message": str(exc)})
        raise


def plot(output, data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for col, (key, d) in enumerate(data.items()):
        u = d["displacement_m"]*1000
        axes[0, col].plot(u, d["force_N"]/1000, color="black", linewidth=.8, label="Original experimental plot path")
        axes[0, col].plot(u, d["predicted_N"]/1000, color="#ce602e", linewidth=.8, alpha=.85, label="Conditional TMQ candidate")
        axes[0, col].set(xlabel="Actuator displacement (mm)", ylabel="Axial force (kN)", title=f"Carden {key} | {'training' if key == 'P' else 'held-out specimen'}")
        axes[1, col].plot(d["sequence"], d["force_N"]/1000, color="black", linewidth=.9)
        axes[1, col].plot(d["sequence"], d["predicted_N"]/1000, color="#ce602e", linewidth=.9)
        axes[1, col].set(xlabel="Original PDF vertex index (not time)", ylabel="Axial force (kN)", title="Complete preserved sequence, including terminal force loss")
        axes[0, col].legend(fontsize=8)
    for axis in axes.flat: axis.grid(alpha=.2)
    fig.suptitle("Measured coupon E/fy; nominal A/L; actuator displacement\nIncomplete identification / unvalidated prototype; all observations retained")
    fig.tight_layout()
    for ext in ("png", "svg", "pdf"): fig.savefig(output/f"full_hysteresis.{ext}", dpi=170, bbox_inches="tight")
    plt.close(fig)


def refine_tension(output=OUTPUT):
    """Use resolved later tensile plastic observations of P to constrain rho.

    This is an explicitly additional, frozen training-only diagnostic. It does
    not upgrade the failed repeated-compression stage or remove full-curve errors.
    """
    output = Path(output)
    destination = output/"rho_refinement"
    if destination.exists(): raise FileExistsError(destination)
    summary = json.loads((output/"summary.json").read_text())
    source_data = {k: ordered_data(json.loads((output/f"{k}.json").read_text())) for k in ("P", "Q")}
    d = source_data["P"]
    segment = np.array([s["segment"] for s in d["manifest"]["samples"]])
    # P begins with compression; its odd-numbered legs advance into tension.
    threshold = 1.1*d["area_m2"]*d["manifest"]["yield_stress_Pa"]
    mask = (segment % 2 == 1) & (d["force_N"] >= threshold)
    if np.count_nonzero(mask) < 20 or len(np.unique(segment[mask])) < 2:
        raise ValueError("Insufficient independent later tensile branches above the declared threshold")
    weights = np.zeros(len(mask))
    for leg in np.unique(segment[mask]):
        selected = mask & (segment == leg)
        weights[selected] = 1/np.count_nonzero(selected)
    weights /= weights.sum()
    training = {**d, "weights": weights}
    template = TMQParameters(**summary["diagnostic_parameters"])
    destination.mkdir()
    write_json(destination/"frozen_plan.json", {"training": "P", "holdout": "Q", "parameter": "rho",
        "bounds": [0., .02], "force_threshold_N": threshold, "source_indices": np.flatnonzero(mask).tolist(),
        "source_segments": np.unique(segment[mask]).tolist(), "geometry_policy": "conditional_nominal_geometry",
        "all_other_parameters_fixed": template.to_dict(), "selection_basis": "positive-going P branches above 1.10 nominal Afy; no Q observations used",
        "seeds": [17, 29, 43], "population": 16, "generations": 16})
    fit = fit_ordered_history(training, template, [Bound("rho", 0., .02)],
        seeds=(17, 29, 43), population=16, generations=16, timeout_seconds=90.)
    write_json(destination/"fit.json", fit)
    if fit["local_identifiability"]["rank"] != 1:
        raise ValueError("rho is not locally identifiable in selected later tensile branches")
    p = TMQParameters(**fit["best_parameters"])
    summary["initial_diagnostic_metrics"] = summary["curve_metrics"]
    summary["initial_diagnostic_parameters"] = summary["diagnostic_parameters"]
    summary["curve_metrics"] = []
    for key, history in source_data.items():
        predicted = response(p, history["strain"])*history["area_m2"]
        history["predicted_N"] = predicted
        error = (predicted-history["force_N"])/max(abs(history["force_N"]))
        summary["curve_metrics"].append({"specimen": key, "role": "training" if key == "P" else "holdout",
            "full_history_nrmse": float(np.sqrt(np.dot(history["weights"], error**2))),
            "observed_min_N": float(min(history["force_N"])), "predicted_min_N": float(min(predicted)),
            "observed_max_N": float(max(history["force_N"])), "predicted_max_N": float(max(predicted)),
            "complete_observed_points": len(predicted)})
        # Keep the original candidate files; refined predictions have new names.
        write_csv(output/f"{key}_refined_predictions.csv", [{"sequence": i, "displacement_m": float(u),
            "observed_force_N": float(f), "candidate_force_N": float(g)} for i, (u, f, g) in enumerate(zip(
            history["displacement_m"], history["force_N"], predicted))])
    summary["diagnostic_parameters"] = p.to_dict()
    summary["diagnostic_parameter_selection"] = "initial staged candidate plus training-only later tensile rho refinement; repeated compression coefficients remain priors"
    summary["tension_refinement"] = {"rho": p.rho, "observed_point_count": int(np.count_nonzero(mask)),
        "source_segments": np.unique(segment[mask]).tolist(), "threshold_N": threshold,
        "selected_tensile_nrmse": float(np.sqrt(fit["best_objective"])), "local_rank": 1,
        "all_runs_complete": all(not r["ga"]["timed_out"] for r in fit["runs"]),
        "interpretation": "conditional on all other fixed coefficients; not independent steel coupon hardening or full cyclic validation"}
    write_json(output/"summary.json", summary)
    plot(output, source_data)
    return summary["tension_refinement"]


def publish(output=OUTPUT):
    """Publish the completed experiment, including failures and unsupported coefficients."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = Path(output)
    summary = json.loads((output/"summary.json").read_text())
    fit = json.loads((output/"fit.json").read_text())
    plan = json.loads((output/"frozen_plan.json").read_text())
    histories = {k: ordered_data(json.loads((output/f"{k}.json").read_text())) for k in ("P", "Q")}
    peak_rows = []
    for key, d in histories.items():
        start, direction, cycle = 0, -1 if key == "P" else 1, 0
        for end in d["manifest"]["source_turning_indices"]+[len(d["strain"])-1]:
            if direction < 0:
                cycle += 1
                index = start+int(np.argmin(d["force_N"][start:end+1]))
                peak_rows.append({"specimen": key, "compression_number": cycle, "index": index,
                    "displacement_mm": float(d["displacement_m"][index]*1000),
                    "peak_N": float(-d["force_N"][index]),
                    "ratio_to_P_virgin_peak": float(-d["force_N"][index]/summary["peak_force_N"]),
                    "prior_tension": key == "Q" or cycle > 1})
            start = end+1; direction = -direction
    write_csv(output/"observed_compression_peaks.csv", peak_rows)
    later = [r["peak_N"] for r in peak_rows if r["specimen"] == "P" and r["compression_number"] > 1]
    hi, lo = max(later), min(later)
    bound_hits = []
    for stage, settings in zip(fit["stages"], plan["stages"]):
        for bound in settings["bounds"]:
            value = stage["parameters"][bound["name"]]
            for side in ("lower", "upper"):
                if abs(value-bound[side]) <= 1e-6*(bound["upper"]-bound["lower"]):
                    bound_hits.append({"stage": stage["stage"], "parameter": bound["name"], "side": side, "value": value})
    theoretical_peak_u = summary["phi"]*summary["fixed_fy_Pa"]*summary["nominal_length_m"]/summary["fixed_E_Pa"]*1000
    diagnostics = {"observed_compression_peaks": peak_rows, "bound_hits": bound_hits,
        "P_first_peak_displacement_magnitude_mm": abs(peak_rows[0]["displacement_mm"]),
        "linear_initial_branch_peak_displacement_mm": theoretical_peak_u,
        "constant_later_peak_minimax_relative_error": (hi-lo)/(hi+lo),
        "constant_later_peak_minimax_N": 2*hi*lo/(hi+lo),
        "interpretation": "Bound based on plotted P peak values, without measurement uncertainty; applies to current constant-eta implementation, not every published TMQ formulation",
        "rho_status": "first tension leg insufficient; additional later tensile P branches used conditionally" if summary.get("tension_refinement") else "first tension leg insufficient; retained prior .01",
        "kappa_status": "zero local sensitivity in selected second compression; no identified value published",
        "source_table_correction": "F/G/I start in compression but original Table3-4 identifies tensile yielding before buckling; exclude from virgin-peak selection"}
    summary["diagnostics"] = diagnostics
    summary["all_GA_runs_completed"] = all(not r["ga"]["timed_out"] for s in fit["stages"] for r in s["runs"])
    summary["actual_GA_seconds"] = sum(r["ga"]["elapsed_seconds"] for s in fit["stages"] for r in s["runs"])
    if summary.get("tension_refinement"):
        rho_fit = json.loads((output/"rho_refinement/fit.json").read_text())
        summary["all_GA_runs_completed"] &= summary["tension_refinement"]["all_runs_complete"]
        summary["actual_GA_seconds"] += sum(r["ga"]["elapsed_seconds"] for r in rho_fit["runs"])
    write_json(output/"summary.json", summary)
    write_json(output/"diagnostics.json", diagnostics)
    # First-leg mismatch and measured progressive buckling are diagnostic evidence.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    d = histories["P"]; end = d["manifest"]["source_turning_indices"][0]+1
    p = TMQParameters(**summary["diagnostic_parameters"])
    f = response(p, d["strain"][:end])*d["area_m2"]
    axes[0].plot(-d["displacement_m"][:end]*1000, -d["force_N"][:end]/1000, "k-", label="P observed first compression")
    axes[0].plot(-d["displacement_m"][:end]*1000, -f/1000, color="#ce602e", label="Conditional TMQ")
    axes[0].scatter([theoretical_peak_u], [summary["peak_force_N"]/1000], color="#ce602e", marker="x")
    axes[0].set(xlabel="Actuator shortening (mm)", ylabel="Compression (kN)", title="Fixed E/fy and nominal geometry: peak position mismatch")
    for key, color in (("P", "#1675ac"), ("Q", "#7b5599")):
        rows = [r for r in peak_rows if r["specimen"] == key]
        axes[1].plot([r["compression_number"] for r in rows], [r["ratio_to_P_virgin_peak"] for r in rows], "o-", color=color, label=f"{key}: ratio to P virgin peak")
    axes[1].axhline(p.eta, color="#ce602e", linestyle="--", label="Current constant eta prior")
    axes[1].set(xlabel="Compression excursion number", ylabel="Peak / P first peak", title="Q includes initial tension; all source points retained")
    for ax in axes: ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ("png", "svg", "pdf"): fig.savefig(output/f"mechanism_diagnostics.{ext}", dpi=170, bbox_inches="tight")
    plt.close(fig)
    parameters = summary["diagnostic_parameters"]
    metrics = {r["specimen"]: r for r in summary["curve_metrics"]}
    refinement = summary.get("tension_refinement")
    rho_note = (f"随后新增一项单独冻结的P训练诊断：选取正向拉伸支中力超过1.10Afy={refinement['threshold_N']/1000:.3f} kN的{refinement['observed_point_count']}个原始顶点，支路等权，仅拟合ρ。得到ρ={refinement['rho']:.6f}、该选区NRMSE={refinement['selected_tensile_nrmse']:.2%}，局部1/1秩。它仍依赖固定的其它循环系数，不是独立测得的钢材强化比。未用Q选择阈值、边界或参数。" if refinement else "ρ未作追加识别，保持0.01先验。")
    report = f'''# Carden P/Q：真实作者有序曲线的条件识别与失败诊断

日期：2026-10-26。P 用于训练，Q 仅在阶段识别后评价。**已执行真实试验绘图数据上的条件拟合；完整参数识别与完整滞回检验均未通过。** 所有观察点和失配保留，不更新生产材料。

## 1. 这次取得了此前缺少的什么

由第二个子 agent 从 [University at Buffalo 官方报告]({SOURCE})取得 MCEER-08-0002 原文；表 3-1（印刷页55/PDF85）给出批3实测券样 E=218 GPa、fy=338 MPa。P/Q 属同一批焊接单角钢。

[2006 原期刊]({JOURNAL})表1（印刷页112/PDF2）给 P/Q 名义截面 1×1×3/16 in、长度25.4 in。因此本次固定名义锐角 A={NOMINAL_AREA*1e6:.8f} mm²、L={NOMINAL_LENGTH*1000:.2f} mm。未取得独立实测面积；2008表中640 mm是另一圆整值，与645.16 mm存在5.16 mm差异，未冒充同一实测值。位移来自作动器，含系统柔度；焊接件未观察到螺栓滑移，但不等于夹具柔度已扣除。

## 2. 历史顺序及坐标如何取得

提取原报告 PDF101/印刷71 的图3-24、3-25原始 PDF 线段命令：P有5397个顶点，Q有4192个，共9589点。P内部40次、Q内部27次换笔均与上个端点完全重合，未出现断开后猜测拼接；起始方向分别先压/先拉，与原试件表一致。保留作者线段顺序及重复点，未按位移排序，也没有将绘图索引包装成时间或仪器采样号。

两图使用英制原轴标尺换算：横轴6 in/313.2 PDF点，纵轴50 kip/193.92 PDF点。源路径局部首点均为(0,0)，现有数值以该首点归零；这是一项条件假定，未经仪器零点验证。相对原图实际水平零轴，P首点为+0.24 PDF点（约+0.275 kN），Q首点为−0.96 PDF点（约−1.101 kN）；Q超过图线宽0.543 PDF点对应的约0.623 kN。两图路径首点横坐标均与实际垂直零轴重合到PDF浮点精度，不能把整幅网格拟合/舍入误差作为原点偏移。原始相对坐标和图上平移保留在raw文件，分试件归零假设写入manifest。这是可追溯图线数字化，不是取得原始DAQ文件。详见[2026-10-28符号与原点审计](../carden_sign_audit_20261028/REPORT.md)。

首个转折约±6.54 mm，随后约±12.85 mm、±19.39 mm。原2006文字0.25 in与2008文字13 mm的增幅冲突未用于造加载协议；全部位移均直接取自作者路径。反转提取容差0.75 mm只用于划分原始行号，不修改任何位移/力。

P首压图峰53.401 kN，与2006表4的12.0 kip=53.379 kN相差0.04%；Q图峰47.345 kN与表4的10.7 kip=47.596 kN相差约0.53%。Q第一次受压已有先拉历史，不能称未加载试件的初始峰。

## 3. 实际识别步骤、冻结方案与结果

1. 冻结 E、fy、A、L、P训练/Q留出、3种种子17/29/43及各阶段范围；保存输入hash和frozen_plan.json。
2. 从 P 首压支确定 φ=Pcr/(Afy)={summary['phi']:.6f}，随后只拟合α、β。γ=0.5明确保留为先验。
3. 用首次压屈后卸载与再加载支拟合τ、μ、ν，ζ=0.1保留先验。首次拉伸段最高73.770 kN，低于名义Afy=74.108 kN，不足以确定ρ，因此ρ=0.01仍是原先验，不能称实测标定结果。
4. 尝试用第二受压支识别η、θ、κ，局部Jacobian仅2/3秩：κ的局部灵敏度为0，停止发布该组三参数的“最终值”。完整诊断图使用前两个阶段的参数以及原先声明的后续压屈先验，不偷偷采用任意的κ优化值。
5. 重放P和Q所有9589点，保留末端失强。Q未参与任何优化目标；本轮没有根据Q误差调整范围或选择参数。

6. {rho_note}

| 阶段 | 目标支路 NRMSE | 可辨识性/限制 |
|---|---:|---|
| 首压α、β | {summary['stages'][0]['training_nrmse']:.2%} | 局部2/2秩；α={parameters['alpha']:.6f}，β={parameters['beta']:.6f} |
| 卸载τ、μ、ν | {summary['stages'][1]['training_nrmse']:.2%} | 局部3/3秩，但τ=6、μ=0.7均碰上界，ν={parameters['nu']:.6f}；不是稳健确定的唯一参数 |
| 后续η、θ、κ | {summary['stages'][2]['training_nrmse']:.2%} | 局部2/3秩，κ未被激励，θ碰下界；该组未识别完成 |

阶段误差统一按P完整观察记录绝对峰91.937 kN归一，不是按各支路压峰归一；不能将此百分数误读为压峰相对误差。GA三种种子均完整结束，另进行了独立标记的最小二乘细化；算法收敛不等于物理模型通过。

## 4. 完整滞回结果

| 试件 | 用途 | 完整回线 NRMSE | 观察最大拉力/kN | 诊断模型最大拉力/kN |
|---|---|---:|---:|---:|
| P | 部分支路训练，余下历史诊断 | {metrics['P']['full_history_nrmse']:.2%} | {metrics['P']['observed_max_N']/1000:.2f} | {metrics['P']['predicted_max_N']/1000:.2f} |
| Q | 未参与优化的同规格试件 | {metrics['Q']['full_history_nrmse']:.2%} | {metrics['Q']['observed_max_N']/1000:.2f} | {metrics['Q']['predicted_max_N']/1000:.2f} |

完整误差按各试件观察峰归一，各加载支路等权。它们对应“首两阶段候选+后续拉伸ρ条件细化+其余未识别系数先验”，不是完整九参数优化后的最好可能精度。初始ρ=0.01时P/Q全曲线误差分别为51.17%/39.53%，其完整预测另存P_predictions.csv/Q_predictions.csv；本表和主图使用追加ρ拟合后的结果，另存refined_predictions.csv。**不能据此断言所有TMQ形式都无法拟合；可以确定当前这组参数未通过回线检验。**

图 `full_hysteresis.svg/png/pdf` 展示完整P/Q回线及原始索引上的力历史；橙线偏离黑线的部分全部保留。报告未将最后失强切掉以改善误差；当前材料没有断裂机制。

## 5. 已查明的力学/识别问题

- **首峰位置无法只靠下降支系数修正。** 实测绘图峰在约1.869 mm缩短；固定E、fy、φ、L时，当前线性初始段的理论峰在{theoretical_peak_u:.3f} mm。α、β只改变峰后段，不能把首峰移到1.869 mm。需要区分几何柔化、端部/夹具柔度及位移标距口径，不能降低实测钢材E来吸收所有差异。
- **单一后续峰系数有明确限制。** P第2到第10受压峰由37.436 kN降至26.976 kN，分别约为首峰的0.701和0.505。当前原型把每次后续峰固定为η乘首峰；在这些图峰上，无论η取何值，最坏峰值相对误差至少约{(hi-lo)/(hi+lo):.1%}（未计量测误差）。这是当前常η实现的局限，不能自动归咎原作者未核对的完整模型。
- **不能把优化边界或零灵敏度当参数确定。** τ/μ碰上界、θ碰下界，κ在当前阶段无响应；应改变有依据的训练覆盖或复核材料分支规则，而不是将输出数字直接装入全塔。
- **ρ需要后续拉伸支，不能从第一小循环确定。** 本轮已追加利用P后续高于1.10Afy的拉伸支约束ρ；这只减少相关假设，未解决卸载边界和后续峰规则。仍需在冻结ρ后重新评估其它循环系数及不确定性；Q继续作为不参与优化的预测记录。

## 6. 新证据纠正旧筛选

原报告表3-4脚注标明F/G/I虽然首次加载方向为压缩，但真正发生压屈前已经历拉伸屈服。因此历史“10件先压容量代理”不能称10件virgin压屈标定。新代码已拒绝F/G/I进入此类容量拟合；原历史结果保留为旧批次快照并加提示。

Jain仍无严格准入：另一个子agent发现后人综述存在预拉至屈服及端板固定连接线索，与数据库标签冲突。未据此虚构预加载或更改原始CSV。两份详细文献复核报告位于 literature/tmq_ordered_history_20261026。

## 7. 复算与后续执行

`carden_ordered_experiment.py --export-vectors` 仅提取已核对哈希的原PDF，需要可选pymupdf（本轮装在/tmp工具目录，项目依赖未修改）；常规拟合只读取本地已导出的vector JSON。

```sh
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.carden_ordered_experiment --output /tmp/carden-conditional-new
```

不得覆盖已有目录。随后可调用模块publish(output)生成报告及诊断图。原始PDF/JSON/CSV和图形保留本地，方法、测试、文献结论与报告可版本管理。本轮没有全塔计算或参数替换。

下一批按顺序：确认首峰位移口径/构件柔化 → 冻结本轮ρ候选并复核其不确定性 → 回查原TMQ后续峰递推及小反转规则 → 在独立实验模块试验有来源支持的恢复/退化修正 → 重放P/Q全部路径并报告全部失败。保持对名义几何与绘图误差的条件说明。
'''
    (output/"REPORT.md").write_text(report)
    # HTML contains summaries only; full-resolution scientific plots remain separate artifacts.
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Carden真实滞回条件识别</title><style>body{{margin:0;background:#eef2f6;color:#193247;font:16px/1.75 system-ui}}main{{max-width:1180px;margin:auto;padding:24px}}section{{background:white;border-radius:16px;padding:22px;margin:20px 0}}h1{{line-height:1.3}}img{{width:100%}}a{{color:#116494}}.note{{border-left:4px solid #c16c21;background:#fff6e8;padding:14px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}b{{font-variant-numeric:tabular-nums}}@media(max-width:650px){{main{{padding:12px}}section{{padding:14px}}.grid{{grid-template-columns:1fr}}}}</style><main><a href="/">← 成果主页</a><h1>真实滞回：Carden P训练 / Q留出</h1><p class="note">本轮确实用作者保存的试验曲线路径进行条件拟合。完整回线未通过；后续压屈参数未全部识别。实测券样E/fy已核实，几何仍为报告名义值，全塔参数未替换。</p><section class="grid"><div>实测 E / fy<br><b>218 GPa / 338 MPa</b></div><div>条件首压系数<br><b>φ = {summary['phi']:.4f}</b><br>首峰53.4 kN</div><div>完整回线 NRMSE<br><b>P {metrics['P']['full_history_nrmse']:.1%} / Q {metrics['Q']['full_history_nrmse']:.1%}</b></div></section><section><h2>完整滞回曲线与原始序列</h2><p>黑线为作者原始绘图路径，橙线为首两阶段候选加未识别系数先验。P 5397点、Q 4192点全部保留，包括末端失强；下图横轴是绘图顶点编号，没有时间含义。</p><a href="full_hysteresis.pdf"><img src="full_hysteresis.svg" alt="P训练和Q留出完整力位移回线及原始序列，候选模型明显失配"></a></section><section><h2>已查明的关键问题</h2><p>首峰缩短：观察约1.869 mm，当前初始直线模型约0.721 mm。P后续压峰从首峰的0.701降到0.505，当前常数η无法同时保持所有峰值。卸载τ/μ碰搜索上界，第二受压支不足以确定κ；ρ仍为先验。</p><a href="mechanism_diagnostics.pdf"><img src="mechanism_diagnostics.svg" alt="首压峰位移失配与后续循环压峰逐步下降"></a></section><section><h2>证据与复算</h2><p>采用原报告名义A=219.254 mm²、L=645.16 mm及作动器位移；没有冒称实测面积或原始仪器时程。作者矢量路径内部换笔全部连续，P先压/Q先拉与试件表相符。</p><p><a href="REPORT.md">详细步骤、参数与失败诊断</a> · <a href="summary.json">结果摘要</a> · <a href="frozen_plan.json">冻结识别方案</a> · <a href="observed_compression_peaks.csv">逐循环压峰</a> · <a href="verification.json">测试记录</a></p><p><a href="P_predictions.csv">P全部观察/预测</a> · <a href="Q_predictions.csv">Q全部观察/预测</a> · <a href="{SOURCE}">原始MCEER报告</a></p></section><section><h2>下一项工作</h2><p>先核对峰值位移和连接柔度，再用P后续已屈服的拉伸支约束ρ，复核原TMQ后续峰递推与小反转规则。当前失配不能全部归因于优化器，也不能据此声称所有TMQ模型无效。</p><p>旧容量筛选补充：F/G/I虽先压，原报告注明压屈前已拉屈服，现已从virgin首峰识别接口排除。</p></section></main></html>'''
    page = page.replace("橙线为首两阶段候选加未识别系数先验", "橙线为首两阶段候选加后续拉伸ρ细化，其余未识别系数保留先验")
    page = page.replace("ρ仍为先验。", f"ρ已由后续拉伸支条件识别为{parameters['rho']:.6f}。")
    page = page.replace("再用P后续已屈服的拉伸支约束ρ", "冻结并复核后续拉伸支得到的ρ候选")
    page = page.replace('href="P_predictions.csv"', 'href="P_refined_predictions.csv"').replace('href="Q_predictions.csv"', 'href="Q_refined_predictions.csv"')
    (output/"index.html").write_text(page)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--export-vectors", action="store_true")
    args = parser.parse_args()
    if args.export_vectors: export_vectors()
    else:
        run(args.output)
        refine_tension(args.output)
        publish(args.output)
