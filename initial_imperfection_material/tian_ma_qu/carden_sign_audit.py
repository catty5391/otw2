"""Read-only sign, coordinate and recovery-branch audit of the existing Carden fit.

No refitting, source-point editing or material replacement. Optional PyMuPDF is
only used for an independent renderer-coordinate comparison with the raw PDF.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from .material import TMQParameters, TianMaQuPrototype
from .parameter_identification import ordered_data, response, KIP_N

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS = Path(__file__).parent / "followup_results/carden_conditional_20261026"
RAW = ROOT / "literature/tmq_ordered_history_20261026/raw"
PDF = ROOT / "literature/tmq_ordered_history_20261026/papers/02_Carden_Itani_Buckle_2008_MCEER_08_0002.pdf"
OUTPUT = Path(__file__).parent / "followup_results/carden_sign_audit_20261028"
X_SCALE = 6*25.4/313.2
F_SCALE = 50*KIP_N/193.92


def first_upcrossing(x, y, level):
    """Interpolate the first crossing in preserved order, never sort a branch."""
    for i in range(len(y)-1):
        if y[i] <= level < y[i+1]:
            return float(x[i]+(x[i+1]-x[i])*(level-y[i])/(y[i+1]-y[i]))
    return None


def pdf_point_to_screen(point, translation, page_height):
    """Raw PDF y is upward; a screen renderer alone reverses page y."""
    x,y=point;tx,ty=translation
    return np.array([x+tx,page_height-(y+ty)])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_pdf(vectors, output):
    import pymupdf
    with pymupdf.open(PDF) as doc:
        page=doc[100]
        drawings=page.get_drawings()
        curves=[d for d in drawings if len(d["items"])>1000]
        if len(curves)!=2 or page.rotation!=0:
            raise ValueError("Unexpected original page geometry")
        checks={}
        for key, drawing in zip(("P","Q"), curves):
            raw=vectors[key]
            if raw["transform"][:4]!=[1.,0.,0.,1.]:
                raise ValueError("Unexpected reflected/scaled source CTM")
            translation=raw["transform"][4:]
            expected=[];previous=None
            for x,y,operation in raw["vertices"]:
                current=pdf_point_to_screen((x,y),translation,page.rect.height)
                if operation=="l" and np.linalg.norm(current-previous)>1e-8:
                    expected.append([*previous,*current])
                previous=current
            actual=np.array([[*item[1],*item[2]] for item in drawing["items"] if item[0]=="l"])
            maximum_error=float(np.max(np.abs(np.asarray(expected)-actual)))
            if maximum_error>1e-4:
                raise ValueError("Cached vectors disagree with independent PDF renderer")
            origin=pdf_point_to_screen((0.,0.),translation,page.rect.height)
            vertical=[];horizontal=[]
            for d in drawings:
                for item in d["items"]:
                    if item[0]!="l":continue
                    a,b=item[1:]
                    if abs(a.x-b.x)<1e-4 and 190<abs(a.y-b.y)<195 and abs(a.x-origin[0])<2 and min(a.y,b.y)<origin[1]<max(a.y,b.y):
                        vertical.append((a,b))
                    if abs(a.y-b.y)<1e-4 and 300<abs(a.x-b.x)<315 and abs(a.y-origin[1])<2:
                        horizontal.append((a,b))
            if len(vertical)!=1 or len(horizontal)!=1:
                raise ValueError("Ambiguous drawn zero axes")
            zero_x=vertical[0][0].x;zero_y=horizontal[0][0].y
            # Positive source force = above horizontal zero axis = smaller screen y.
            offset_x=(origin[0]-zero_x)*X_SCALE
            offset_f=(zero_y-origin[1])*F_SCALE
            checks[key]=dict(renderer_nonzero_segments=len(actual),
                renderer_max_coordinate_error_pdf_points=maximum_error,
                path_origin_screen_xy=origin.tolist(),drawn_zero_axis_screen_xy=[zero_x,zero_y],
                path_origin_relative_to_drawn_axis_displacement_mm=float(offset_x),
                path_origin_relative_to_drawn_axis_force_N=float(offset_f),
                source_x_right_is_positive=True,source_y_up_is_positive=True,
                raw_local_matrix=raw["transform"],plot_stroke_width_pdf_points=float(drawing["width"]))
        page.get_pixmap(matrix=pymupdf.Matrix(1.7,1.7)).save(str(output/"source_page101.png"))
        return checks


def run(output=OUTPUT):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    original_summary=json.loads((PREVIOUS/"summary.json").read_text())
    params=TMQParameters(**original_summary["diagnostic_parameters"])
    vectors={k:json.loads((RAW/f"carden_{k}_vector.json").read_text()) for k in ("P","Q")}
    paths=[PDF,PREVIOUS/"summary.json",Path(__file__).parent/"material.py"]
    paths += [RAW/f"carden_{k}_vector.json" for k in ("P","Q")]
    paths += [PREVIOUS/f"{k}{suffix}" for k in ("P","Q") for suffix in (".json","_predictions.csv","_refined_predictions.csv")]
    before={str(p.relative_to(ROOT)):digest(p) for p in paths}
    pdf_checks=check_pdf(vectors,output)
    data={};all_crossings=[];results={};branch_traces=[]
    for key in ("P","Q"):
        manifest=json.loads((PREVIOUS/f"{key}.json").read_text())
        d=ordered_data(manifest)
        xy=np.array([p[:2] for p in vectors[key]["vertices"]])
        independent_u=xy[:,0]*X_SCALE*.001
        independent_f=xy[:,1]*F_SCALE
        saved=list(csv.DictReader((PREVIOUS/f"{key}_refined_predictions.csv").open()))
        saved_u=np.array([float(r["displacement_m"]) for r in saved])
        saved_o=np.array([float(r["observed_force_N"]) for r in saved])
        saved_p=np.array([float(r["candidate_force_N"]) for r in saved])
        replay=response(params,d["strain"])*d["area_m2"]
        opposite_input=response(params,-d["strain"])*d["area_m2"]
        scale=max(abs(d["force_N"]))
        errors={name:float(np.sqrt(np.dot(d["weights"],((f-d["force_N"])/scale)**2)))
                for name,f in (("unchanged",replay),("force_sign_reversed",-replay),
                               ("strain_sign_reversed",opposite_input),("both_signs_reversed",-opposite_input))}
        first_motion=next(float(x) for x in independent_u if x!=0.)
        results[key]=dict(point_count=len(xy),first_displacement_sign=int(np.sign(first_motion)),
            max_vector_to_csv_displacement_difference_m=float(max(abs(independent_u-saved_u))),
            max_vector_to_csv_force_difference_N=float(max(abs(independent_f-saved_o))),
            max_manifest_to_csv_displacement_difference_m=float(max(abs(d["displacement_m"]-saved_u))),
            max_replay_to_saved_prediction_difference_N=float(max(abs(replay-saved_p))),
            common_initial_values=[float(saved_u[0]),float(saved_o[0]),float(saved_p[0])],
            counterfactual_weighted_nrmse=errors,all_original_indices_preserved=all(int(r["sequence"])==i for i,r in enumerate(saved)))
        threshold=.9*manifest["yield_stress_Pa"]*d["area_m2"]
        boundaries=[0]+manifest["source_turning_indices"]+[len(xy)-1]
        count=0
        for start,end in zip(boundaries,boundaries[1:]):
            u=saved_u[start:end+1]*1000
            if u[-1]<=u[0]:continue
            count+=1
            of=independent_f[start:end+1];pf=replay[start:end+1]
            observed=first_upcrossing(u,of,threshold);predicted=first_upcrossing(u,pf,threshold)
            axis_observed=first_upcrossing(u,of+pdf_checks[key]["path_origin_relative_to_drawn_axis_force_N"],threshold)
            all_crossings.append(dict(specimen=key,positive_leg_number=count,start_sequence=start,end_sequence=end,
                start_displacement_mm=float(u[0]),end_displacement_mm=float(u[-1]),threshold_N=threshold,
                observed_crossing_mm=observed,predicted_crossing_mm=predicted,
                predicted_minus_observed_mm=None if observed is None or predicted is None else predicted-observed,
                axis_based_observed_crossing_mm=axis_observed,
                observed_zero_force_mm=first_upcrossing(u,of,0.),predicted_zero_force_mm=first_upcrossing(u,pf,0.)))
        material=TianMaQuPrototype(params)
        next_turn={i+1:i for i in manifest["source_turning_indices"] if d["strain"][i]<0}
        for i,e in enumerate(d["strain"]):
            material.set_trial_strain(float(e))
            state=material.get_state()
            if i in next_turn and state["active_secant_modulus"] is not None:
                branch_traces.append(dict(specimen=key,first_step_after_reversal=i,
                    reversal_sequence=next_turn[i],secant_modulus_Pa=state["active_secant_modulus"],
                    F_G_H_I=[dict(displacement_mm=x*d["length_m"]*1000,force_N=y*d["area_m2"])
                             for x,y in material._trial.curve.knots]))
            material.commit_state()
        data[key]=dict(u=saved_u*1000,observed=independent_f,predicted=replay,manifest=manifest)
    first_end=data["P"]["manifest"]["source_turning_indices"][0]
    first_peak=int(np.argmin(data["P"]["observed"][:first_end+1]))
    exact_peak=-params.phi*params.yield_stress/params.elastic_modulus*data["P"]["manifest"]["length_m"]*1000
    sampled_peak=int(np.argmin(data["P"]["predicted"][:first_end+1]))
    first=dict(observed_index=first_peak,observed_displacement_mm=float(data["P"]["u"][first_peak]),
        observed_peak_force_N=float(data["P"]["observed"][first_peak]),
        analytical_model_peak_displacement_mm=exact_peak,
        sampled_model_peak_displacement_mm=float(data["P"]["u"][sampled_peak]),
        missing_peak_shortening_mm=abs(data["P"]["u"][first_peak])-abs(exact_peak),
        orientation="model first compression peak lies to the RIGHT of the observed negative peak")
    summary=dict(schema="otw2.carden_sign_audit.v1",date="2026-10-28",sign_inversion_found=False,
        claim_scope="raw PDF -> vectors -> declared units -> existing TMQ -> saved plotting arrays",
        common_horizontal_input_array=True,original_data_modified=False,original_fit_replaced=False,
        metadata_correction_needed=True,pdf_checks=pdf_checks,source_file_sha256=before,
        replay_checks=results,first_compression=first,recovery_crossings=all_crossings,
        recovery_branch_traces=branch_traces,
        interpretation="Leftward displacement of later tensile recovery is real model mismatch, not a graph-axis flip or constant translation; zero compression tail and recovery branches reach high tensile force too early.")
    after={str(p.relative_to(ROOT)):digest(p) for p in paths}
    summary["original_source_and_result_hashes_unchanged"]=before==after
    if not summary["original_source_and_result_hashes_unchanged"]:raise RuntimeError("Source/result mutation during audit")
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    with (output/"recovery_crossings.csv").open("w",encoding="utf-8",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=list(all_crossings[0]));writer.writeheader();writer.writerows(all_crossings)
    plot(output,data,summary)
    return summary


def plot(output,data,summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font));plt.rcParams["font.family"]="Noto Sans CJK JP"
    plt.rcParams["axes.unicode_minus"]=False
    fig,axes=plt.subplots(2,2,figsize=(13,10))
    p=data['P'];black='#253a48';orange='#ce602e'
    axes[0,0].plot(p['u'],p['observed']/1000,color=black,lw=.8,label='原试验绘图路径')
    axes[0,0].plot(p['u'],p['predicted']/1000,color=orange,lw=.8,label='现有 TMQ 候选')
    axes[0,0].set(title='P：共同位移数组，恢复支仍明显偏左',xlabel='作动器位移 / mm',ylabel='轴力 / kN')
    axes[0,0].legend(fontsize=9)
    end=p['manifest']['source_turning_indices'][0]+1
    axes[0,1].plot(p['u'][:end],p['observed'][:end]/1000,color=black,label='原试验首压')
    axes[0,1].plot(p['u'][:end],p['predicted'][:end]/1000,color=orange,label='TMQ 首压')
    peak=summary['first_compression']
    axes[0,1].axvline(peak['observed_displacement_mm'],color=black,ls=':',label='观察峰 −1.869 mm')
    axes[0,1].axvline(peak['analytical_model_peak_displacement_mm'],color=orange,ls=':',label='理论峰 −0.721 mm')
    axes[0,1].set(title='首压峰反而偏右，不能用统一翻号纠正',xlabel='作动器位移 / mm',ylabel='轴力 / kN')
    axes[0,1].legend(fontsize=9)
    for leg,style in ((2,'-'),(9,'--')):
        row=next(r for r in summary['recovery_crossings'] if r['specimen']=='P' and r['positive_leg_number']==leg)
        sl=slice(row['start_sequence'],row['end_sequence']+1)
        axes[1,0].plot(p['u'][sl],p['observed'][sl]/1000,color=black,ls=style,label=f'原试验第{leg}正向支')
        axes[1,0].plot(p['u'][sl],p['predicted'][sl]/1000,color=orange,ls=style,label=f'TMQ 第{leg}正向支')
        axes[1,0].plot([row['observed_crossing_mm'],row['predicted_crossing_mm']],[row['threshold_N']/1000]*2,'o',color='#007f83')
    axes[1,0].axhline(summary['recovery_crossings'][0]['threshold_N']/1000,color='#007f83',ls=':',label='0.9 Afy = 66.70 kN')
    axes[1,0].set(title='P：模型过早恢复高拉力',xlabel='作动器位移 / mm',ylabel='轴力 / kN')
    axes[1,0].legend(fontsize=8)
    for key,color in (('P','#007f83'),('Q','#7253a1')):
        rows=[r for r in summary['recovery_crossings'] if r['specimen']==key and r['predicted_minus_observed_mm'] is not None]
        axes[1,1].plot([r['positive_leg_number'] for r in rows],[r['predicted_minus_observed_mm'] for r in rows],'o-',color=color,label=key)
    axes[1,1].axhline(0,color='gray',lw=.8)
    axes[1,1].set(title='0.9 Afy 处的水平差随历史增长',xlabel='正向加载支编号（Q 含初次受拉）',ylabel='模型位移 − 观察位移 / mm')
    axes[1,1].legend()
    for ax in axes.flat:ax.grid(alpha=.2)
    fig.suptitle('Carden 符号与左偏审计：拉为正、压为负；全程保留作者顺序\n现有模型未通过完整回线验证，图线数字化不等于仪器时程',fontsize=13)
    fig.tight_layout()
    for ext in ('png','svg','pdf'):fig.savefig(output/f'coordinate_and_shift_audit.{ext}',dpi=170,bbox_inches='tight')
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--pdf-python-path',type=Path)
    args=parser.parse_args()
    if args.pdf_python_path:sys.path.append(str(args.pdf_python_path))
    result=run(args.output)
    print(json.dumps(dict(sign_inversion_found=result['sign_inversion_found'],metadata_correction_needed=True,
                         original_hashes_unchanged=result['original_source_and_result_hashes_unchanged']),ensure_ascii=False))
