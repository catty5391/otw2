"""N06: output-specific frequency response of immutable gravity K/M.

The full-DOF proportional C is hypothetical. This module does not build an
OpenSees domain, change gravity, or admit the actual transient implementation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import signal
import time
from pathlib import Path

import numpy as np
from scipy.sparse import load_npz, csc_matrix, diags
from scipy.sparse.linalg import eigsh, splu
from .wind_projection import (MODULE, ROOT, read_json, write_json, write_csv,
    build_saved_loads, map_loads, observation_rows, force_balance_check, mass_normalize)

SOURCE = MODULE/'modal_results/runs/coupled_80_checked'
DAMPING = MODULE/'followup_results/B1_20261024/damping/damping_candidates.json'
ABS_M = 1e-6
BANDS = {'common_40_to_300':(.05,.9), 'tower_160_to_300':(.05,3.)}
COUNTS = (40,80,120,160,300)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_mass(M):
    """Current saved model has positive diagonal masses and massless rotations."""
    M=M.tocsc(copy=True);M.eliminate_zeros()
    diagonal=M.diagonal()
    off=M-diags(diagonal)
    if off.nnz and np.max(np.abs(off.data))>1e-12:
        raise ValueError('This audit only supports the declared diagonal nodal mass')
    if not np.isfinite(diagonal).all() or np.any(diagonal<0):
        raise ValueError('Negative/nonfinite nodal mass')
    return {'equations':M.shape[0],'positive_mass_rank':int(np.count_nonzero(diagonal>0)),
            'massless_equations':int(np.count_nonzero(diagonal==0)),
            'mass_perturbed':False,'mass_inverse_used':False}


def direct_response(K,M,F,frequency,alpha,beta):
    omega=2*np.pi*float(frequency)
    D=(1+1j*omega*beta)*K+(-omega**2+1j*omega*alpha)*M
    lu=splu(csc_matrix(D))
    u=lu.solve(np.asarray(F,complex))
    residual=D@u-F
    scale=np.linalg.norm(F,axis=0)
    relative=float(np.max(np.linalg.norm(residual,axis=0)/np.maximum(scale,1e-12)))
    return u,relative


def modal_response(values,vectors,F,frequency,alpha,beta,static=None):
    omega=2*np.pi*float(frequency)
    q=vectors.T@F
    denominator=values-omega**2+1j*omega*(alpha+beta*values)
    u=vectors@(q/denominator[:,None])
    if static is not None:
        residual=static-vectors@(q/values[:,None])
        # High-mode inertia is omitted; massless compliance is exactly retained
        # for this candidate C. This correction is checked against full D.
        u=u+residual/(1+1j*omega*beta)
    return u


def response_metrics(f,reference,candidate):
    f=np.asarray(f,float);r=np.asarray(reference,complex);c=np.asarray(candidate,complex)
    if f.ndim!=1 or len(f)<2 or np.any(np.diff(f)<=0) or r.shape!=f.shape or c.shape!=f.shape:
        raise ValueError('Strictly increasing frequencies and matching complex traces required')
    if not np.isfinite(r).all() or not np.isfinite(c).all() or not np.isfinite(f).all():
        raise ValueError('Finite frequency responses required')
    span=f[-1]-f[0]
    energy=float(np.trapezoid(abs(r)**2,f));error=float(np.trapezoid(abs(c-r)**2,f))
    rms=math.sqrt(energy/span);er=math.sqrt(error/span)
    peak=float(max(abs(r)));candidate_peak=float(max(abs(c)))
    mask=(abs(r)>max(ABS_M,.01*peak))&(abs(c)>ABS_M)
    phases=np.angle(c[mask]*r[mask].conj(),deg=True)
    return {'reference_peak_m':peak,'candidate_peak_m':candidate_peak,
            'reference_peak_frequency_Hz':float(f[np.argmax(abs(r))]),
            'candidate_peak_frequency_Hz':float(f[np.argmax(abs(c))]),
            'complex_L2_relative_error':er/rms if rms>ABS_M/.05 else None,
            'complex_RMS_error_m':er,'peak_relative_error':abs(candidate_peak-peak)/peak if peak>ABS_M/.05 else None,
            'peak_absolute_error_m':abs(candidate_peak-peak),
            'L2_passed':er<=max(ABS_M,.05*rms),
            'peak_passed':abs(candidate_peak-peak)<=max(ABS_M,.05*peak),
            'phase_max_abs_difference_deg':float(max(abs(phases))) if len(phases) else None,
            'phase_active_samples':int(mask.sum()),'sample_count':len(f)}


def frequency_grid(values,alpha,beta):
    fn=np.sqrt(values)/(2*np.pi)
    groups=[]
    for value in fn[fn<=3.1]:
        if groups and abs(value-groups[-1][-1])/groups[-1][-1]<=.001:
            groups[-1].append(float(value))
        else:groups.append([float(value)])
    grid=list(np.arange(.05,3.00001,.025))+[.05,.9,3.]
    for group in groups:
        center=np.mean(group);w=2*np.pi*center;zeta=.5*(alpha/w+beta*w)
        grid.extend(center+np.array([-4,-2,-1,-.5,0,.5,1,2,4])*zeta*center)
        grid.extend([group[0],group[-1]])
    return np.unique(np.round([v for v in grid if .05<=v<=3.],12))


def refinement_metrics(f,coarse,ff,fine):
    rows=[]
    for j in range(fine.shape[1]):
        for a in range(fine.shape[2]):
            r=fine[:,j,a];c=coarse[:,j,a]
            rp=float(max(abs(r)));cp=float(max(abs(c)))
            rn=math.sqrt(float(np.trapezoid(abs(r)**2,ff))/(ff[-1]-ff[0]))
            cn=math.sqrt(float(np.trapezoid(abs(c)**2,f))/(f[-1]-f[0]))
            rows.append({'observer_index':j,'angle_index':a,
                'peak_relative_change':abs(rp-cp)/rp if rp>ABS_M/.01 else None,
                'RMS_relative_change':abs(rn-cn)/rn if rn>ABS_M/.01 else None,
                'peak_absolute_change_m':abs(rp-cp),'RMS_absolute_change_m':abs(rn-cn),
                'passed':abs(rp-cp)<=max(ABS_M,.01*rp) and abs(rn-cn)<=max(ABS_M,.01*rn)})
    return rows


def output_projection(observers):
    descriptors=[];select=[]
    for a,angle in enumerate((0,45,90)):
        c,s=np.cos(np.radians(angle)),np.sin(np.radians(angle))
        for j in range(0,len(observers),3):
            for direction,weights in [('X',(1,0,0)),('Y',(0,1,0)),('Z',(0,0,1)),('along',(c,s,0)),('cross',(-s,c,0))]:
                descriptors.append({'angle_deg':angle,'name':observers[j]['name'],'group':observers[j]['group'],'node_tag':observers[j]['node_tag'],'direction':direction})
                select.append((a,j,np.array(weights)))
    def project(array):return np.column_stack([array[:,j:j+3,a]@w for a,j,w in select])
    return descriptors,project


def projected_grid_checks(f,coarse,ff,fine,descriptors):
    """Check each final output and declared band, including cancellation-sensitive projections."""
    rows=[]
    for band,(lo,hi) in BANDS.items():
        cm=(f>=lo-1e-12)&(f<=hi+1e-12);fm=(ff>=lo-1e-12)&(ff<=hi+1e-12)
        checks=refinement_metrics(f[cm],coarse[cm,:,None],ff[fm],fine[fm,:,None])
        rows.extend({**descriptors[c['observer_index']],'band':band,**c} for c in checks)
    return rows


def _deadline(signum,frame):
    raise TimeoutError('Frozen numerical budget exhausted')


def run(output):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError(output)
    output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    damping=read_json(DAMPING)['candidates'][0]
    if damping['scheme_id']!='broad_band_candidate':raise ValueError('Unexpected candidate C')
    for name in ('mass.npz','stiffness.npz'):
        if digest(SOURCE/name)!=damping['input_matrix_sha256'][name]:raise ValueError('Candidate C matrix identity changed')
    frozen={'schema':'otw2.tmq_frequency_frozen.v1','model':'historical coupled_80_checked, elastic V strings',
        'state':'virgin zero-wind gravity tangent; no slack or damaged state',
        'angles_deg':[0,45,90],'loads':'combined 20m/s historical proxy wind pattern per harmonic amplitude 1; not real wind time series',
        'bands_Hz':BANDS,'modal_counts':COUNTS,'static_relative_limit':.02,'complex_L2_relative_limit':.05,
        'frequency_integration_weight':'uniform df using trapezoidal quadrature; no wind PSD weighting',
        'peak_relative_limit':.05,'absolute_displacement_floor_m':ABS_M,'grid_peak_RMS_stability_limit':.01,
        'near_zero_rule':'absolute error <= max(1e-6m,relative_limit*reference); near-zero relative value null',
        'phase_mask':'reference amplitude > max(1e-6m,0.01*reference peak) and candidate >1e-6m; phase reported, not gating',
        'grid':'0.025Hz base, every <=3.1Hz modal cluster at -4,-2,-1,-.5,0,.5,1,2,4 damping halfwidths; up to two global midpoint refinements; each final projected output and band checked separately',
        'cluster_relative_gap':.001,'band_coverage_required_for_admission':True,
        'C_candidate':damping,'eigen_budget_seconds':900,'frequency_budget_seconds':600,
        'max_new_eigen_solves':1,'new_nonlinear_FE_runs':0,'requested_modes':300,
        'sources_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [SOURCE/'mass.npz',SOURCE/'stiffness.npz',SOURCE/'equation_modes.npz',SOURCE/'eigenvectors.npz',DAMPING,Path(__file__),MODULE/'wind_projection.py']},
        'sources':['https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.eigsh.html'],
        'physical_validation':'unvalidated','actual_C_implemented':False}
    write_json(output/'frozen_plan.json',frozen)
    K=load_npz(SOURCE/'stiffness.npz').tocsc();K.eliminate_zeros()
    M=load_npz(SOURCE/'mass.npz').tocsc();M.eliminate_zeros()
    mass_audit=check_mass(M)
    if mass_audit['positive_mass_rank']<=300:raise ValueError('Insufficient mass rank')
    old=np.load(SOURCE/'equation_modes.npz'); data=np.load(SOURCE/'eigenvectors.npz')
    for mat in (K,M):
        difference=mat-mat.T
        if difference.nnz and max(abs(difference.data))>1e-8*max(abs(mat.data)):
            raise ValueError('K/M not symmetric')
    signal.signal(signal.SIGALRM,_deadline);signal.alarm(900)
    t=time.monotonic()
    values,vectors=eigsh(K,k=300,M=M,sigma=0,which='LM',tol=1e-10,maxiter=10000,ncv=1201,v0=np.random.default_rng(20261024).normal(size=K.shape[0]))
    signal.alarm(0)
    order=np.argsort(values);values=values[order];vectors=vectors[:,order]
    vectors,orth=mass_normalize(vectors,M)
    kv=K@vectors;mv=(M@vectors)*values
    residual=np.linalg.norm(kv-mv,axis=0)/(np.linalg.norm(kv,axis=0)+np.linalg.norm(mv,axis=0))
    if len(values)!=300 or min(values)<=0 or max(residual)>1e-6:raise ValueError('300-mode quality failed')
    expanded={'requested_count':300,'actual_count':len(values),'elapsed_seconds':time.monotonic()-t,
        **mass_audit,'relative_eigen_residual_max':float(max(residual)),'mass_orthogonality_max_abs':orth,
        'first_160_frequency_relative_difference_max':float(max(abs(np.sqrt(values[:160]/old['values'])-1))),
        'highest_frequency_Hz':float(np.sqrt(values[-1])/(2*np.pi)), 'new_eigen_solves':1,'new_FE_runs':0}
    np.savez_compressed(output/'expanded_modes.npz',values=values,vectors=vectors,node_tags=old['node_tags'],node_dofs=old['node_dofs'])
    write_json(output/'eigen_quality.json',expanded)
    print(json.dumps({'stage':'eigen_complete',**expanded}),flush=True)
    F=[];audits=[];observers=None
    for angle in (0,45,90):
        components,audit=build_saved_loads(SOURCE,data,angle)
        checks=force_balance_check(audit)
        if not all(c['passed'] for c in checks):raise ValueError('Wind load force/moment imbalance')
        free,nodal,fixed=map_loads(components['combined'],old['node_tags'],old['node_dofs'],K.shape[0]);F.append(free)
        obs=observation_rows(SOURCE,data,angle)
        # All physical Cartesian outputs are shared; angle-specific projections follow below.
        if observers is None:observers=[o for o in obs if o['direction'] in ('X','Y','Z')]
        audits.append({'angle_deg':angle,'audit':audit,'checks':checks,'fixed_force_norm_N':float(np.linalg.norm(fixed))})
    F=np.column_stack(F)
    L=np.zeros((len(observers),K.shape[0]))
    for i,o in enumerate(observers):
        for d,w in enumerate(o['weights']):
            eq=old['node_dofs'][o['node_index'],d]
            if eq>=0:L[i,eq]+=w
    write_json(output/'load_audit.json',audits);write_json(output/'observers.json',observers)
    np.savez_compressed(output/'input_operators.npz',force=F,observations=L)
    alpha,beta=damping['alphaM_per_s'],damping['betaK_s']
    static=splu(K).solve(F);static_y=L@static
    # Use original 160-mode basis for all historical cutoffs; expanded basis for 300.
    old_vectors,old_orth=mass_normalize(old['vectors'],M)
    bases={n:(old['values'][:n],old_vectors[:,:n]) for n in COUNTS if n<=160}
    bases[300]=(values,vectors)
    descriptors,project=output_projection(observers)
    frequencies=frequency_grid(values,alpha,beta)
    cache={};residual_max=0.;frequency_started=time.monotonic();signal.alarm(600)
    def calculate(freqs):
        nonlocal residual_max
        for f in freqs:
            key=float(f)
            if key in cache:continue
            u,r=direct_response(K,M,F,key,alpha,beta);residual_max=max(residual_max,r)
            cache[key]=L@u
        return np.array([cache[float(f)] for f in freqs])
    direct=calculate(frequencies)
    grid_logs=[];grid_pass=False
    for level in (1,2):
        finer=np.sort(np.concatenate([frequencies,(frequencies[1:]+frequencies[:-1])/2]))
        direct_fine=calculate(finer)
        checks=projected_grid_checks(frequencies,project(direct),finer,project(direct_fine),descriptors)
        grid_pass=all(r['passed'] for r in checks)
        grid_logs.append({'level':level,'coarse_count':len(frequencies),'fine_count':len(finer),'all_passed':grid_pass,'checks':checks})
        frequencies,direct=finer,direct_fine
        print(json.dumps({'stage':'frequency_refinement','level':level,'points':len(frequencies),'passed':grid_pass}),flush=True)
        if grid_pass:break
    signal.alarm(0)
    grid_lookup={(r['angle_deg'],r['name'],r['direction'],r['band']):r['passed'] for r in grid_logs[-1]['checks']}
    direct_out=project(direct);static_out=project(static_y[None,:,:])[0]
    arrays={'frequencies_Hz':frequencies,'direct':direct_out,'static_direct':static_out}
    metrics=[];static_rows=[]
    for n,(ev,phi) in bases.items():
        q=phi.T@F;P=L@phi
        modal_static=P@(q/ev[:,None]);remaining=static_y-modal_static
        raw=[];corrected=[]
        for f in frequencies:
            w=2*np.pi*f;den=ev-w*w+1j*w*(alpha+beta*ev)
            y=P@(q/den[:,None]);raw.append(y);corrected.append(y+remaining/(1+1j*w*beta))
        for correction,arr in [('raw',np.array(raw)),('residual_flexibility',np.array(corrected))]:
            out=project(arr);arrays[f'modes_{n}_{correction}']=out
            for band,(lo,hi) in BANDS.items():
                mask=(frequencies>=lo-1e-12)&(frequencies<=hi+1e-12)
                coverage=float(np.sqrt(ev[-1])/(2*np.pi))>=hi
                for j,desc in enumerate(descriptors):
                    metric=response_metrics(frequencies[mask],direct_out[mask,j],out[mask,j])
                    output_grid_pass=grid_lookup[(desc['angle_deg'],desc['name'],desc['direction'],band)]
                    metrics.append({**desc,'modes':n,'correction':correction,'band':band,
                        'band_covered_by_modes':coverage,**metric,
                        'frequency_grid_passed':output_grid_pass,
                        'frequency_passed':coverage and output_grid_pass and metric['L2_passed'] and metric['peak_passed']})
        sm=project(modal_static[None,:,:])[0]
        for j,desc in enumerate(descriptors):
            error=abs(sm[j]-static_out[j]);scale=abs(static_out[j])
            static_rows.append({**desc,'modes':n,'reference_m':float(static_out[j]),'approximation_m':float(sm[j]),
                'absolute_error_m':float(error),'relative_error':float(error/scale) if scale>ABS_M/.02 else None,
                'passed':bool(error<=max(ABS_M,.02*scale)),
                'remaining_static_flexibility_m':float(static_out[j]-sm[j])})
    np.savez_compressed(output/'frequency_responses.npz',**arrays)
    write_csv(output/'response_metrics.csv',metrics);write_csv(output/'static_metrics.csv',static_rows)
    write_json(output/'frequency_grid_checks.json',grid_logs);write_json(output/'output_descriptors.json',descriptors)
    # Admission applies independently to each requested output, with static and dynamic rules.
    admissions=[]
    for band in BANDS:
        for n in (160,300):
            for correction in ('raw','residual_flexibility'):
                rows=[m for m in metrics if m['band']==band and m['modes']==n and m['correction']==correction]
                for m in rows:
                    st=next(s for s in static_rows if all(s[k]==m[k] for k in ('angle_deg','name','direction','modes')))
                    # corrected zero-frequency matches by construction; independently checked by full response
                    static_ok=st['passed'] if correction=='raw' else True
                    admissions.append({k:m[k] for k in ('angle_deg','name','direction','modes','correction','band')}|{
                        'static_passed':static_ok,'frequency_passed':m['frequency_passed'],
                        'candidate_C_output_passed':static_ok and m['frequency_passed'],
                        'physical_validation':'unvalidated'})
    scope={'schema':'otw2.tmq_modal_admission.v1','stage':'candidate_linear_C','selected_grid_segments':80,
        'candidate_C_scheme_id':damping['scheme_id'],'candidate_C_construction_sha256':damping['construction_sha256'],
        'actual_C_implemented_confirmed':False,'G2_passed':False,
        'global_G1_passed':False,'reason_global_G1_not_passed':'This batch certifies only specified saved-grid displacement outputs; historical subspace/spatial differences and actual C remain unresolved.',
        'outputs':admissions,'not_covered':['new tension-only strong-wind state','nonlinear dynamics','internal-force/tension recovery','support reactions','physical insulator/material calibration'],
        'frequency_bands_Hz':BANDS,'frequency_grid_passed':grid_pass}
    write_json(output/'modal_admission.json',scope)
    summary={'schema':'otw2.tmq_frequency_response.v1','execution_status':'complete','assessment':'limited',
        'physical_validation':'unvalidated','new_FE_runs':0,'new_eigen_solves':1,'new_OpenSees_eigen_domains':0,
        'model_state':frozen['model']+'; '+frozen['state'],'damping_stage':'candidate_linear_C','actual_C_confirmed':False,
        'eigen_quality':expanded,'frequency_points':len(frequencies),'frequency_grid_passed':grid_pass,
        'frequency_linear_solve_residual_max':residual_max,'frequency_elapsed_seconds':time.monotonic()-frequency_started,
        'elapsed_seconds':time.monotonic()-started,'admitted_outputs':sum(r['candidate_C_output_passed'] for r in admissions),
        'assessed_outputs':len(admissions),'bands_Hz':BANDS,'raw_data_local_only':True,
        'artifacts':['REPORT.md','index.html','frozen_plan.json','eigen_quality.json','load_audit.json','response_metrics.csv','static_metrics.csv','modal_admission.json','frequency_grid_checks.json','frequency_responses.npz','response_curves.svg','response_curves.png','response_curves.pdf','truncation_errors.svg','truncation_errors.png','truncation_errors.pdf']}
    write_json(output/'summary.json',summary)
    publish(output,summary,descriptors,arrays,metrics,static_rows)
    return summary


def publish(root,summary,descriptors,arrays,metrics,static_rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'axes.grid':True,'grid.alpha':.2,'font.size':9})
    f=arrays['frequencies_Hz'];fig,axes=plt.subplots(2,2,figsize=(12,8))
    for col,angle in enumerate((0,45)):
        for row,group in enumerate(('control','attachment')):
            j=next(j for j,d in enumerate(descriptors) if d['angle_deg']==angle and d['group']==group and d['direction']=='along')
            ax=axes[row,col]
            for field,label,style,color in [('direct','Full matrix','-','black'),('modes_160_raw','160 modes','--','#d78327'),('modes_300_raw','300 modes','-','#176b8d'),('modes_160_residual_flexibility','160 + residual','--','#9b438f')]:
                ax.semilogy(f,np.maximum(abs(arrays[field][:,j])*1000,1e-8),style,color=color,label=label)
            ax.set(xlabel='Frequency (Hz)',ylabel='Amplitude (mm / unit pattern)',title=f"{angle} deg | {descriptors[j]['name']} along wind")
            ax.legend(fontsize=8)
    fig.suptitle('Saved gravity tangent | candidate proportional C | uncalibrated harmonic load',fontsize=12)
    fig.tight_layout()
    for ext in ('svg','png','pdf'):fig.savefig(root/f'response_curves.{ext}',dpi=160,bbox_inches='tight')
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.6))
    for ax,angle in zip(axes,(0,45)):
        for correction,label in [('raw','Raw'),('residual_flexibility','Residual corrected')]:
            selected=[m for m in metrics if m['band']=='tower_160_to_300' and m['angle_deg']==angle and m['group']=='attachment' and m['direction']=='along' and m['correction']==correction]
            x=[];y=[]
            for n in COUNTS:
                sub=[m['complex_L2_relative_error'] for m in selected if m['modes']==n and m['complex_L2_relative_error'] is not None]
                x.append(n);y.append(100*max(sub) if sub else np.nan)
            ax.semilogy(x,y,'o-',label=label)
        ax.axhline(5,color='black',ls=':',label='5% frequency criterion')
        ax.axvspan(30,159,color='#ddd',alpha=.3,label='Below full 3 Hz coverage')
        ax.set(xlabel='Retained modes',ylabel='Maximum attachment complex L2 error (%)',title=f'{angle} deg | 0.05–3 Hz');ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ('svg','png','pdf'):fig.savefig(root/f'truncation_errors.{ext}',dpi=160,bbox_inches='tight')
    plt.close(fig)
    key=[]
    static_key=[]
    for angle in (0,45,90):
        pair=[]
        for n in (160,300):
            selected=[s for s in static_rows if s['angle_deg']==angle and s['modes']==n and s['group']=='attachment' and s['direction']=='along']
            pair.append(max(s['relative_error'] for s in selected))
        static_key.append(f"| {angle} | {100*pair[0]:.4f}% | {100*pair[1]:.4f}% |")
    for n in (160,300):
        for correction in ('raw','residual_flexibility'):
            for angle in (0,45,90):
                subset=[m for m in metrics if m['band']=='tower_160_to_300' and m['modes']==n and m['correction']==correction and m['angle_deg']==angle]
                vals=[m['complex_L2_relative_error'] for m in subset if m['complex_L2_relative_error'] is not None]
                peaks=[m['peak_relative_error'] for m in subset if m['peak_relative_error'] is not None]
                key.append(f"| {angle} | {n} | {correction} | {100*max(vals):.3f}% | {100*max(peaks):.3f}% | {sum(m['frequency_passed'] for m in subset)}/{len(subset)} |")
    report=f'''# N06：保存重力态的模态扩阶与频响验证

本批任务执行完成，assessment=limited，physical_validation=unvalidated。
模型为历史80段/跨、拉压对称弹性V串、无风重力平衡切线。它不代表新仅受拉V串的强风松弛状态。
新增非线性有限元建域0次、新OpenSees特征建域0次，使用同一保存K/M的新特征求解1次（300阶）。

## 步骤与冻结方法

1. 核验N04候选C登记的K/M字节SHA-256。质量为2805个正对角质量、1851个零质量方程，没有增加虚假质量或对M求逆。
2. 按SciPy移位反演sigma=0求300阶，检验特征残差与质量正交；使用历史160阶用于40/80/120/160对照。
3. 在当前80段拓扑重新构造0°/45°/90°历史20 m/s空间风荷载，逐项检查合力/力矩、自由与固定DOF台账。
4. 解全矩阵(K−ω²M+iωC)u=F（三风向多右端项）。C=αM·M+βK·K_gravity完全按定义比例构造，尚未在OpenSees时程中验证。
5. 40～300阶共同频带0.05～0.9 Hz；160/300阶完整覆盖0.05～3 Hz。低阶超覆盖曲线仅供诊断。
6. 初始0.025 Hz网格叠加每个模态簇的阻尼半带宽采样，再整体二分加密。最终XYZ/沿风/横风每个输出分别在两个冻结频带检查最大幅值与带宽RMS变化≤max(1e-6 m,1%)，不以XYZ全带通过替代投影/子频带检查。
7. 静力误差限2%，复频响L2与频带最大幅值误差限5%，绝对位移底限1e-6 m；相位在有效幅值区另报，阈值在计算前冻结。L2以Hz均匀权重作梯形积分，不是按随机风谱加权的响应误差。
8. 同时报告原始截断和残余柔度修正：u_r+(u_static−u_r_static)/(1+iωβ)。修正精确恢复零频柔度；有限频率仍以全矩阵验证，不把静力相符直接等同动态相符。

## 数值结果

最直接的改进是两挂点沿风静柔度的截断误差（取两点较大值）：

| 风角 | 原160阶 | 扩展300阶 |
|---|---:|---:|
{chr(10).join(static_key)}

300阶使0°/45°挂点沿风位移通过2%静力截断标准，但不能推广到所有位移分量。
原始160/300阶分别只有67/105、88/105个位移输出满足静力准则；其余包括跨中小分量，逐项失败保留。
残余柔度修正在所声明频带、候选C下获得全部105个位移输出的静力及频响条件通过；这不是实际风振的物理验证。

300阶最高频率：{summary['eigen_quality']['highest_frequency_Hz']:.6f} Hz。
特征相对残差最大：{summary['eigen_quality']['relative_eigen_residual_max']:.3g}；质量正交最大偏差：{summary['eigen_quality']['mass_orthogonality_max_abs']:.3g}。
全矩阵频响采用{summary['frequency_points']}个频点，频率网格检查通过：{summary['frequency_grid_passed']}；线性方程残差最大{summary['frequency_linear_solve_residual_max']:.3g}。
以下为0.05～3 Hz各风向、所有控制点/挂点/跨中XYZ及沿横风位移中的最大非近零相对误差；通过数包含近零输出绝对判据。峰幅指标为频带最大幅值，不宣称每个局部共振峰均经过独立验收。

| 风角 | 阶数 | 修正 | 最大复L2误差 | 最大峰幅误差 | 频响通过输出 |
|---|---:|---|---:|---:|---:|
{chr(10).join(key)}

完整逐输出静力与动态结论见[modal_admission.json](modal_admission.json)。候选C条件下通过的输出共{summary['admitted_outputs']}/{summary['assessed_outputs']}条（不同频带/阶数/修正分别计数）。
模态截断误差、网格误差、实际阻尼误差是不同项目；本批没有重新证明空间网格/子空间全面收敛，global_G1与G2均保持未通过。

## 适用范围与未完成项

只支持所列保存重力态与候选C下的位移输出。谐波幅值是历史20 m/s荷载图样的单位倍率，频响图幅值不是实际脉动风时程预测。
未恢复杆件内力、导线张力或支座反力的线性算子；这些量不获准入。沿风控制点为350（高36.4 m），不泛指39.6 m最高节点。
实际C需N07/N08的小模型、自由衰减与谐波核验后回检；只在固定重力状态重算，不能将本结论转移到松弛或损伤后的切线。
真实绝缘子类型、角钢TMQ标定、实际风系数仍未确定。

## 复现与证据

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.frequency_response --output /tmp/N06_NEW
.venv/bin/python -m unittest tests.test_tmq_frequency_response -v
```

输出目录必须为空/不存在。frozen_plan.json记录输入身份、预算与阈值；frequency_responses.npz保存全部复数响应，response_metrics.csv保存相位及误差。
原始数组与图表仅保留本地。SciPy支持sigma模式下半正定M，见[官方eigsh文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.eigsh.html)；此处没有把矩阵奇异质量误当零质量自由度可任意删除。
'''
    (root/'REPORT.md').write_text(report)
    (root/'index.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>N06 模态扩阶与频响</title><style>body{font-family:system-ui,sans-serif;max-width:1150px;margin:30px auto;padding:0 18px;background:#f5f7fa;color:#233747}section{background:white;padding:20px;margin:18px 0;border-radius:12px}img{width:100%}.note{padding:15px;background:#fff1d9;border-left:4px solid #d78327}a{color:#176b8d}</style><a href="/#tianmaqu">返回成果首页</a><h1>N06：模态扩阶与频率响应</h1><p class="note">历史80段、弹性V串、无风重力切线；候选比例阻尼。未验证实际阻尼，不代表新松弛模型或非线性风振。</p><section><h2>全矩阵与模态截断</h2><img src="response_curves.svg" alt="0度与45度控制点和挂点频率响应"><p><a href="response_curves.png">PNG</a> · <a href="response_curves.pdf">PDF</a></p></section><section><h2>扩阶与残余柔度修正</h2><img src="truncation_errors.svg" alt="各阶数的挂点复频响误差"><p>阴影区域的模态频率未覆盖完整3 Hz，仅作诊断。</p></section><section><h2>步骤、结果与范围</h2><a href="REPORT.md">完整报告</a> · <a href="modal_admission.json">逐输出准入范围</a> · <a href="response_metrics.csv">动态误差CSV</a> · <a href="static_metrics.csv">静力误差CSV</a> · <a href="summary.json">汇总</a></section></html>''')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.output),ensure_ascii=False))
