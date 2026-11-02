"""Fit explicit nonlinear branches; run complete conditional member cycles.

Only observed Carden P branch data enter fitting. Nominal dimensions and K=.5
remain assumptions. Peak-aligned branch fits are NOT full-history validation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import replace
from math import log, pi, sqrt
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from .material import AnglePHMParameters, LiuAnglePHM, PHMDomainError, compression_response
from ..tian_ma_qu.material import TMQParameters, TianMaQuPrototype
from ..tian_ma_qu.experiment import displacement_history

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/"initial_imperfection_material/tian_ma_qu/followup_results/carden_conditional_20261026"
DEFAULT_OUTPUT=Path(__file__).parent/"results"


def write_json(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def write_csv(path,rows):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def nominal_angle_lambda_n(E,fy):
    b=.0254;t=.0047625;length=.64516
    rect=[(t,b,t/2,b/2),(b-t,t,(b+t)/2,t/2)]
    area=sum(w*h for w,h,y,z in rect)
    yc=sum(w*h*y for w,h,y,z in rect)/area
    zc=sum(w*h*z for w,h,y,z in rect)/area
    iy=sum(w*h**3/12+w*h*(z-zc)**2 for w,h,y,z in rect)
    iz=sum(h*w**3/12+w*h*(y-yc)**2 for w,h,y,z in rect)
    iyz=sum(w*h*(y-yc)*(z-zc) for w,h,y,z in rect)
    iw=float(min(np.linalg.eigvalsh([[iy,iyz],[iyz,iz]])))
    slenderness=.5*length/sqrt(iw/area)
    return dict(area_m2=area,length_m=length,weak_inertia_m4=iw,
                assumed_effective_length_factor=.5,slenderness=slenderness,
                lambda_n=slenderness/pi*sqrt(fy/E))


def _multistart(fun,starts,bounds):
    fits=[least_squares(fun,x,bounds=bounds,max_nfev=800,xtol=1e-11,ftol=1e-11,gtol=1e-11) for x in starts]
    return min(fits,key=lambda r:float(r.fun@r.fun))


def _fit_info(fit,names):
    sv=np.linalg.svd(fit.jac,compute_uv=False)
    return dict(names=names,optimizer_success=bool(fit.success),nrmse=float(np.sqrt(np.mean(fit.fun**2))),
                jacobian_singular_values=sv.tolist(),local_rank=int(np.linalg.matrix_rank(fit.jac)),
                active_bounds=fit.active_mask.tolist(),message=fit.message,
                accepted_as_identified=bool(np.linalg.matrix_rank(fit.jac)==len(names) and not np.any(fit.active_mask)),
                interpretation="Conditional branch fit; local rank is not confidence or physical validation")


def fit_branches():
    metadata=json.loads((EVIDENCE/"summary.json").read_text())
    rows=list(csv.DictReader((EVIDENCE/"P_predictions.csv").open()))
    e=np.array([float(r["displacement_m"])/metadata["nominal_length_m"] for r in rows])
    stress=np.array([float(r["observed_force_N"])/metadata["nominal_area_m2"] for r in rows])
    first=np.array([i for i,r in enumerate(rows) if r["phase"]=="first_compression"])
    peak=int(first[np.argmin(stress[first])]);end=int(first[-1]);peak_s=float(stress[peak]);q=-peak_s
    indices=np.arange(peak,end+1)
    d=e[peak]-e[indices]
    if np.any(d<0):raise ValueError("First descending branch precedes observed peak strain")
    E=metadata["fixed_E_Pa"];fy=metadata["fixed_fy_Pa"]
    geom=nominal_angle_lambda_n(E,fy)
    # Existing independently documented conditional tensile fit, not a new coupon.
    rho=.00281947913403508
    base=AnglePHMParameters.from_regression(elastic_modulus=E,yield_stress=fy,
        slenderness=geom["slenderness"],hardening_ratio=rho,unloading_exponent=3.,
        reload_stress_fraction=.85,reload_span_yield_strains=2.,reload_linear_ratio=.5,max_abs_strain=.03,
        provenance="Liu2023 formula form; Carden P measured coupon E/fy; nominal angle; K=.5 assumed")
    base=replace(base,phi=q/fy)
    # eta2 parametrization keeps the curve monotone throughout the declared range.
    def coefficients(x):
        eta1=np.exp(x[0]);eta2=x[1]*eta1/(1.5*np.sqrt(2*base.max_abs_strain))
        return eta1,eta2,-q*x[2]
    def nonlinear(x):
        a,b,sa=coefficients(x)
        return sa+(peak_s-sa)*np.exp(-(a+b*np.sqrt(d))*d)
    fit=_multistart(lambda x:(nonlinear(x)-stress[indices])/q,
        [[log(a),c,r] for a,c,r in [(150.,-.5,.1),(300.,.5,.1),(700.,0.,.3)]],
        ([log(5),-.95,0.],[log(5000),2.,.4]))
    a,b,sa=coefficients(fit.x)
    p=replace(base,eta1=float(a),eta2=float(b),sigma_a=float(sa))

    def polygon(x):
        alpha,beta=np.exp(x[:2]);gamma=x[2]
        transition=(1-gamma)*q/(alpha*E)
        magnitude=np.where(d<=transition,q-alpha*E*d,gamma*q-beta*E*(d-transition))
        return -np.maximum(0,magnitude)
    fold=_multistart(lambda x:(polygon(x)-stress[indices])/q,
        [[log(a),log(b),g] for a,b,g in [(.08,.02,.5),(.2,.01,.65),(.03,.006,.75)]],
        ([log(.0001),log(.0001),.05],[log(1.),log(1.),.95]))
    old=TMQParameters(**metadata["diagnostic_parameters"])
    old=replace(old,phi=p.phi,rho=rho,alpha=float(np.exp(fold.x[0])),beta=float(np.exp(fold.x[1])),gamma=float(fold.x[2]))

    zero=next(i for i in range(end+1,len(e)) if stress[i]>=0)
    x=e[end:zero]-e[end];y=stress[end:zero]-stress[end]
    ku=float(x@y/(x@x))
    sft=-fy+rho*E*(e[end]-fy/E)
    power=log(ku/E)/log(stress[end]/sft)
    p=replace(p,unloading_exponent=power)
    positive=np.array([i for i,r in enumerate(rows) if r["phase"]=="unload_reload" and stress[i]>=0])
    def branch_for(params):
        m=LiuAnglePHM(params);s=m._committed.clone();s.strain=float(e[end]);s.stress=float(stress[end])
        return m._reload_curve(s)
    def rebuild(x):
        return replace(p,reload_stress_fraction=float(x[0]),reload_span_yield_strains=float(x[1]),reload_linear_ratio=float(x[2]))
    def recovery(x):
        curve=branch_for(rebuild(x))
        return (np.array([curve.response(v,1)[0] for v in e[positive]])-stress[positive])/fy
    recover=_multistart(recovery,[[.8,2.,.5],[.7,4.,.7],[.9,1.,.25]],([.4,.8,.05],[.99,10.,3.]))
    p=rebuild(recover.x)
    curve=branch_for(p)
    ku_paper=E*(stress[end]/sft)**3
    result=dict(schema="otw2.liu_angle_phm.branch_fit.v1",physical_validation=False,
        source_file=str((EVIDENCE/"P_predictions.csv").relative_to(ROOT)),
        source_sha256=hashlib.sha256((EVIDENCE/"P_predictions.csv").read_bytes()).hexdigest(),
        source_kind="original ordered experimental PDF path; no raw instrument timestamps",
        source_original_report=metadata["source"],geometry=geom,
        first_branch_indices=[int(first[0]),end],peak_index=peak,descending_indices=[peak,end],
        peak_stress_Pa=peak_s,observed_peak_strain=float(e[peak]),linear_model_peak_strain=peak_s/E,
        nonlinear={**_fit_info(fit,["log_eta1","normalized_eta2","residual_fraction"]),
                   "eta1":p.eta1,"eta2":p.eta2,"sigma_a_Pa":p.sigma_a},
        polygon={**_fit_info(fold,["log_alpha","log_beta","gamma"]),
                 "alpha":old.alpha,"beta":old.beta,"gamma":old.gamma},
        unloading=dict(observed_reversal_index=end,observed_zero_index=zero,
            stiffness_Pa=ku,ratio_to_E=ku/E,fitted_exponent=power,paper_exponent=3.,
            reversal_strain=float(e[end]),reversal_stress_Pa=float(stress[end]),
            fitted_zero_strain=float(e[end]-stress[end]/ku),
            paper_zero_strain=float(e[end]-stress[end]/ku_paper),observed_zero_strain=float(e[zero])),
        reloading=_fit_info(recover,["H_stress_fraction","GH_span_in_yield_strains","chi"]),
        parameters=p.to_dict(),polygon_parameters=old.to_dict(),
        fixed_and_unidentified={"hardening_ratio":"0.002819479 from previous P conditional tensile fit",
            "K":"0.5 is assumed, not identified", "degradation":"69.896/1.566 retained from 2023 paper; not fitted here",
            "H_I_rule":"fitted fractions/spans + historical extension floor, project closure",
            "minor_reversals":"parent-branch retracing, unvalidated", "fracture":"not implemented; explicit strain guard"},
        scope="Anchored branch fits, not calibrated full-history predictions; Q was already seen previously and is not a fresh holdout")
    fitted_rows=[dict(sequence=int(i),displacement_m=float(e[i]*geom["length_m"]),
        observed_force_N=float(stress[i]*geom["area_m2"]),curved_force_N=float(nonlinear(fit.x)[j]*geom["area_m2"]),
        polygon_force_N=float(polygon(fold.x)[j]*geom["area_m2"])) for j,i in enumerate(indices)]
    reload_rows=[dict(sequence=int(i),displacement_m=float(e[i]*geom["length_m"]),
        observed_force_N=float(stress[i]*geom["area_m2"]),curved_force_N=float(curve.response(e[i],1)[0]*geom["area_m2"]))
        for i in range(end,int(positive[-1])+1)]
    return p,old,result,fitted_rows,reload_rows


def protocol(p):
    ey=p.yield_strain
    targets=[0.,-.25*ey,0.]
    for a in (1,2,3,4,6,8):targets.extend([a*ey,-a*ey,a*ey,-a*ey,a*ey])
    targets.append(0.)
    return targets


def simulate(material,targets,steps=60):
    rows=[];events=[]
    for step,leg,e,is_target in displacement_history(targets,steps):
        material.set_trial_strain(e);s=material.get_state()
        rows.append(dict(step=step,leg=leg,is_target=is_target,strain=e,stress_Pa=s["stress"],
            tangent_Pa=s["tangent"],stage=s["stage"],buckling_count=s["buckling_count"],
            work_density=s["external_work_density"],plastic_max=s.get("plastic_max",0.)))
        events.extend(dict(step=step,**v) for v in s["events"])
        material.commit_state()
    return rows,events


def opensees_check(p,rows,area,length):
    import openseespy.opensees as ops
    from ..tian_ma_qu.opensees_adapter import register_model
    out=[dict(step=0,strain=0.,stress_Pa=0.,force_N=0.,reaction_N=0.,load_factor_N=0.)]
    failure=None;ops.wipe()
    try:
        ops.model("basic","-ndm",1,"-ndf",1);ops.node(1,0.);ops.node(2,length);ops.fix(1,1)
        bridge=register_model(1,LiuAnglePHM(p));ops.element("truss",1,1,2,area,1)
        ops.timeSeries("Linear",1);ops.pattern("Plain",1,1);ops.load(2,1.)
        ops.constraints("Plain");ops.numberer("Plain");ops.system("FullGeneral")
        ops.test("NormUnbalance",1e-6,30);ops.algorithm("Newton")
        ops.integrator("DisplacementControl",2,1,1e-6);ops.analysis("Static")
        for row in rows[1:]:
            ops.integrator("DisplacementControl",2,1,row["strain"]*length-ops.nodeDisp(2,1))
            code=ops.analyze(1)
            if code:
                failure=dict(step=row["step"],code=code);break
            stress,strain=ops.eleResponse(1,"material","stressStrain");ops.reactions()
            out.append(dict(step=row["step"],strain=strain,stress_Pa=stress,force_N=stress*area,
                reaction_N=ops.nodeReaction(1,1),load_factor_N=ops.getLoadFactor(1)))
        error=max(abs(r["stress_Pa"]-rows[i]["stress_Pa"]) for i,r in enumerate(out))
        balance=max(abs(r["force_N"]+r["reaction_N"]) for r in out)
        load=max(abs(r["force_N"]-r["load_factor_N"]) for r in out)
        return out,dict(completed_steps=len(out)-1,requested_steps=len(rows)-1,failure=failure,
            max_stress_difference_Pa=error,max_reaction_error_N=balance,max_load_error_N=load,
            passed=failure is None and error<.1 and balance<1e-4 and load<1e-4,
            engine_version=ops.version(),bridge=bridge,
            scope="Actual one-truss equilibrium and adapter check; not independent physical validation")
    finally:ops.wipe()


def observed_replay(p):
    result=[];predictions={}
    for name in ("P","Q"):
        raw=list(csv.DictReader((EVIDENCE/f"{name}_predictions.csv").open()))
        material=LiuAnglePHM(p);output=[];stop=None
        for i,r in enumerate(raw):
            try:material.set_trial_strain(float(r["displacement_m"])/.64516)
            except PHMDomainError as exc:
                stop=dict(sequence=i,reason=str(exc));break
            output.append(dict(sequence=i,displacement_m=float(r["displacement_m"]),
                observed_force_N=float(r["observed_force_N"]),candidate_force_N=material.get_stress()*.00021925359375))
            material.commit_state()
        predictions[name]=output
        obs=np.array([r["observed_force_N"] for r in output]);pred=np.array([r["candidate_force_N"] for r in output])
        result.append(dict(specimen=name,observed_points=len(raw),predicted_points=len(output),stop=stop,
            covered_prefix_nrmse=float(np.sqrt(np.mean((pred-obs)**2))/max(abs(obs))),
            complete=len(output)==len(raw),physical_validation=False,
            label="Already-seen diagnostic history; not a fresh held-out validation"))
    return result,predictions


def run(output,*,native=True):
    output=Path(output)
    if output.exists():raise FileExistsError("Use a new output folder; preserve prior evidence")
    output.mkdir(parents=True)
    p,old,fit,post,reloading=fit_branches()
    write_json(output/"fit.json",fit);write_csv(output/"postbuckling_fit.csv",post);write_csv(output/"reloading_fit.csv",reloading)
    targets=protocol(p)
    rows,events=simulate(LiuAnglePHM(p),targets)
    old_rows,_=simulate(TianMaQuPrototype(old),targets)
    literal_rows,_=simulate(LiuAnglePHM(replace(p,unloading_exponent=3.)),targets)
    fine,_=simulate(LiuAnglePHM(p),targets,120)
    a=[r for r in rows if r["is_target"]];b=[r for r in fine if r["is_target"]]
    step_error=max(abs(x["stress_Pa"]-y["stress_Pa"]) for x,y in zip(a,b))
    work_error=abs(rows[-1]["work_density"]-fine[-1]["work_density"])/max(abs(fine[-1]["work_density"]),1.)
    for name,data in [("curved_history",rows),("polygon_history",old_rows),("paper_unloading_history",literal_rows)]:write_csv(output/f"{name}.csv",data)
    write_json(output/"events.json",events)
    adapter=None
    if native:
        native_rows,adapter=opensees_check(p,rows,fit["geometry"]["area_m2"],fit["geometry"]["length_m"])
        write_csv(output/"opensees_history.csv",native_rows)
    replay,predictions=observed_replay(p)
    for name,data in predictions.items():write_csv(output/f"{name}_diagnostic_prefix.csv",data)
    summary=dict(schema="otw2.liu_angle_phm.experiment.v1",model="LiuAnglePHM conditional analytical curve prototype",
        physical_validation=False,exact_author_reproduction=False,production_tower_parameters_changed=False,
        fit=fit,protocol_kind="new artificial cyclic demonstration; not original experiment protocol",
        targets_strain=targets,requested_steps=len(rows)-1,completed_steps=len(rows)-1,
        final_work_density_J_m3=rows[-1]["work_density"],max_buckling_count=max(r["buckling_count"] for r in rows),
        doubled_resolution_max_target_stress_difference_Pa=step_error,
        doubled_resolution_relative_work_difference=work_error,opensees=adapter,observed_replay=replay,
        paper_literal_sign_audit=dict(signed_peak_Pa=p.first_buckling_stress,
            printed_integral_sign_would_harden=True,
            adopted_expression="sigma_a+(sigma_cr-sigma_a)*exp(-(eta1+eta2*sqrt(d))*d)",
            interpretation="Explicit compression-negative softening interpretation, not silent exact transcription"))
    write_json(output/"summary.json",summary)
    from .publication import publish
    publish(output,summary,rows,old_rows,literal_rows,post,reloading)
    print(json.dumps({"output":str(output),"post_fit_nrmse":fit["nonlinear"]["nrmse"],
        "polygon_fit_nrmse":fit["polygon"]["nrmse"],"steps":len(rows)-1,
        "opensees_passed":adapter and adapter["passed"]},ensure_ascii=False))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument("--no-native",action="store_true");args=parser.parse_args()
    run(args.output,native=not args.no_native)
