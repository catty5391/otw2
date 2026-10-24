"""Run: python -m initial_imperfection_material.tian_ma_qu.run_experiment --with-opensees"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .cases import ASSUMPTIONS, literature_cases
from .experiment import (demonstration_targets, numerical_checks, run_opensees,
                         sensitivity_curves, simulate, summarize_case, write_csv)
from .material import TianMaQuPrototype
from .visualization import create_figures, create_viewer


def run_experiment(output, steps_per_leg=100, with_opensees=False, overwrite=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(f"Refusing to overwrite nonempty results: {output}; use a new directory or --overwrite")
    if steps_per_leg < 2:
        raise ValueError("Use at least two steps per leg")
    output.mkdir(parents=True, exist_ok=True)
    targets = demonstration_targets()
    summary = {"schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
               "model_status":TianMaQuPrototype.model_status,
               "python":sys.version,"platform":platform.platform(),
               "assumptions":ASSUMPTIONS,"closure_assumptions":list(TianMaQuPrototype.closure_assumptions),
               "protocol":{"name":"new_demo_two_cycles_per_amplitude_10_to_35_mm",
                           "targets_m":targets,"steps_per_leg":steps_per_leg,
                           "physical_time":False,"matches_original_test_history":False},
               "source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in Path(__file__).parent.iterdir() if p.suffix in (".py",".cpp")},
               "cases":[], "experimental_validation_performed":False,
               "tower_model_modified":False, "damage_enabled":False}
    bundles=[]
    for case in literature_cases():
        print(f"Running {case.key}: {len(targets)-1} legs x {steps_per_leg} steps",flush=True)
        directory=output/case.key;directory.mkdir(parents=True,exist_ok=True)
        rows,events=simulate(case,targets,steps_per_leg)
        result=summarize_case(case,rows,events)
        write_csv(directory/"history.csv",rows)
        (directory/"events.json").write_text(json.dumps(events,indent=2)+"\n")
        result["checks"]=numerical_checks(case,targets,steps_per_leg,rows)
        bundle={"case":case,"rows":rows,"events":events}
        if with_opensees:
            native,check=run_opensees(case,rows)
            write_csv(directory/"opensees_history.csv",native)
            result["opensees"]=check;bundle["opensees_rows"]=native
        summary["cases"].append(result);bundles.append(bundle)
        # Persist completed cases even if a later case fails; no false full completion flag.
        (output/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    variants=sensitivity_curves(literature_cases()[0],targets)
    summary["sensitivity"]=[]
    for variant in variants:
        result=summarize_case(variant["case"],variant["rows"],variant["events"])
        summary["sensitivity"].append({"parameter":variant["parameter"],"value":variant["value"],
                                       "external_work_J":result["external_work_J"],
                                       "final_force_kN":result["final_force_kN"]})
        write_csv(output/f"sensitivity_{variant['parameter']}_{variant['value']}.csv",variant["rows"])
    create_figures(output,bundles,variants);create_viewer(output,bundles)
    summary["complete"]=all(c["complete"] and c["checks"]["passed"] and
                             c.get("opensees",{}).get("passed",True) for c in summary["cases"])
    summary["artifacts_sha256"]={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in output.rglob("*") if p.is_file() and p.name!="summary.json"}
    (output/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).parent/"results")
    parser.add_argument("--steps-per-leg",type=int,default=100)
    parser.add_argument("--with-opensees",action="store_true",help="Build ABI-specific research adapter and solve actual single truss")
    parser.add_argument("--overwrite",action="store_true")
    args=parser.parse_args()
    result=run_experiment(args.output,args.steps_per_leg,args.with_opensees,args.overwrite)
    print(json.dumps({"complete":result["complete"],"output":str(args.output.resolve())},ensure_ascii=False))
    if not result["complete"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
