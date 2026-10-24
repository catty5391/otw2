"""Reconstruct current Elastic/corotTruss V-string forces from saved node states.

This is saved-data postprocessing, not a new FE run or an insulator capacity check.
The reconstruction assumes no initial material strain/stress in the strings.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

MODULE = Path(__file__).resolve().parent
CASES = ("tower_line_0", "tower_line_45_disp", "tower_line_90")


def elastic_axial_force(initial_i, initial_j, displacement_i, displacement_j, ea):
    values = (*initial_i, *initial_j, *displacement_i, *displacement_j, ea)
    length = math.dist(initial_i, initial_j)
    if not all(math.isfinite(v) for v in values) or length <= 0 or ea <= 0:
        raise ValueError("Finite coordinates, positive initial length and EA required")
    current = math.dist(tuple(a + u for a, u in zip(initial_i, displacement_i)),
                        tuple(b + u for b, u in zip(initial_j, displacement_j)))
    return ea * (current / length - 1)


def audit_run(run: Path) -> tuple[dict, list[dict]]:
    inputs = [run / "model_data/nodes.csv", run / "line_model/insulators.csv",
              run / "node_states.csv.gz", run / "history.csv", run / "summary.json"]
    with inputs[0].open() as stream:
        coords = {int(r["node_tag"]): tuple(float(r[k]) for k in ("x", "y", "z"))
                  for r in csv.DictReader(stream)}
    with inputs[1].open() as stream:
        strings = list(csv.DictReader(stream))
    legs = []
    for string in strings:
        lower = int(string["lower_node_tag"])
        coords[lower] = tuple(json.loads(string["lower_coord"]))
        upper, elements = json.loads(string["upper_node_tags"]), json.loads(string["element_tags"])
        if len(upper) != 2 or len(elements) != 2:
            raise ValueError("Expected two legs per V-string")
        for node, element in zip(upper, elements):
            legs.append({"element": element, "upper": node, "lower": lower,
                         "EA_N": float(string["EA"]), "initial_length_m": math.dist(coords[node], coords[lower])})
    tags = {leg[key] for leg in legs for key in ("upper", "lower")}
    displacements = {}
    with gzip.open(inputs[2], "rt") as stream:
        for row in csv.DictReader(stream):
            node = int(row["node_tag"])
            if node in tags:
                displacements.setdefault(int(row["step"]), {})[node] = tuple(float(row[k]) for k in ("ux", "uy", "uz"))
    with inputs[3].open() as stream:
        history = {int(row["step"]): row for row in csv.DictReader(stream)}
    config = json.loads(inputs[4].read_text())["directional_wind"]
    reference_speed = float(config["wind_speed_m_s"])
    rows = []
    for step, state in sorted(displacements.items()):
        if not tags.issubset(state) or step not in history:
            raise ValueError(f"Incomplete state/history at step {step}")
        factor = float(history[step]["wind_load_factor"])
        if not math.isfinite(factor) or factor < 0:
            raise ValueError("Positive wind load factor required for speed conversion")
        for leg in legs:
            upper, lower = leg["upper"], leg["lower"]
            force = elastic_axial_force(coords[upper], coords[lower], state[upper], state[lower], leg["EA_N"])
            rows.append({"case": run.name, "step": step, "element_tag": leg["element"],
                         "wind_load_factor": factor, "equivalent_wind_speed_m_s": reference_speed * math.sqrt(factor),
                         "force_N_tension_positive": force})
    if not rows or set(displacements) != set(history):
        raise ValueError("Missing saved node states")
    compressive = [row for row in rows if row["force_N_tension_positive"] < -1.0]
    peak_step = max(history, key=lambda step: float(history[step]["wind_load_factor"]))
    sources = []
    for path in inputs:
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        sources.append({"path": path.relative_to(MODULE).as_posix(), "sha256": sha})
    summary = {"case": run.name, "wind_angle_deg": config["wind_angle_deg"],
               "saved_steps": len(displacements), "legs": legs, "sources": sources,
               "compression_detection_tolerance_N": 1.0,
               "gravity_forces_N": [r["force_N_tension_positive"] for r in rows if r["step"] == 0],
               "first_saved_compression": compressive[0] if compressive else None,
               "minimum_force": min(rows, key=lambda r: r["force_N_tension_positive"]),
               "minimum_force_at_peak_load": min((r for r in rows if r["step"] == peak_step), key=lambda r: r["force_N_tension_positive"])}
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    summaries, rows = [], []
    for case in CASES:
        summary, history = audit_run(MODULE / "wind_speed_results/runs" / case)
        summaries.append(summary)
        rows.extend(history)
    args.output.mkdir(parents=True)
    with (args.output / "leg_forces.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {"schema": "otw2.insulator_saved_state_audit.v1", "new_FE_runs": 0,
              "method": "N=EA*(current_length/initial_length-1); current Elastic corotTruss strings only",
              "limitations": ["no insulator strength/buckling validation", "first saved compression is not exact onset",
                              "equivalent wind speed is static load scaling, not an engineering design wind speed"],
              "cases": summaries}
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
