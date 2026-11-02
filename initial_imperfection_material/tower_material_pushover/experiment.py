"""Whole-tower displacement control; stop at the first failed Newton increment.

Each case owns a separate process and a new directory. The saved prefix is a
numerical observation, never an extrapolated collapse or damage-state limit.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=Path(__file__).parent/'results'
SCHEMES=('steel01_four_segments','steel02_four_segments','tmq')
ANGLES=(0,30,45,90)
CONTROL_NODE=350
CRITICAL_MEMBERS=(292,349,825,828,877,878,917,920)
DOF_NAMES=('ux','uy','uz','rx','ry','rz')


def write_json(path, data):
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def control_dof(angle):
    if angle not in ANGLES:raise ValueError('Use an explicitly supported wind angle')
    return 1 if angle in (0,30,45) else 2


def displacement_increment(relative, remaining):
    """Fine sampling before first yield; every case uses the same schedule."""
    if relative < .05-1e-9:limit=min(.002,.05-relative)
    elif relative < .2-1e-9:limit=min(.005,.2-relative)
    else:limit=.01
    return min(limit,remaining)


def build_model(scheme, output):
    from model.tower_model import OpenSeesModel
    from model.tower_model_with_buckling import OpenSeesModelWithBuckling
    from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
    class Steel01SegmentedTower(OpenSeesModelWithBuckling):
        def material(self):
            # Only change the steel law. Keep segmented fibers/Corotational.
            return OpenSeesModel.material(self)
    source=ROOT/'Source/Z30103A6.s2k'
    if scheme=='tmq':
        return OpenSeesModelWithTianMaQu(source,output_dir=output,imperfection_ratio=.001)
    if scheme not in SCHEMES:raise ValueError('Unknown material scheme')
    cls=Steel01SegmentedTower if scheme=='steel01_four_segments' else OpenSeesModelWithBuckling
    return cls(source,output_dir=output,random_disp_ratio=.001,member_divisions=4,imperfection_seed=30103,
               long_edge_segments=8,short_edge_segments=1,steel01_b=.03)


def freeze_sources(output):
    names=['initial_imperfection_material/tower_material_pushover/experiment.py',
           'initial_imperfection_material/tower_material_pushover/evidence.py',
           'model/tower_model.py','model/tower_model_with_buckling.py','model/steel02_parameters.py',
           'model/tower_model_with_tian_ma_qu.py','initial_imperfection_material/tian_ma_qu/material.py',
           'initial_imperfection_material/tian_ma_qu/section_adapter.py',
           'initial_imperfection_material/tian_ma_qu/directional_loading.py',
           'initial_imperfection_material/full_tower_cyclic.py','util/analysis/stepping.py',
           'util/analysis/equilibrium_checks.py','util/processing/member_state_recorder.py']
    hashes={}
    for name in names:
        target=output/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        data=(ROOT/name).read_bytes();target.write_bytes(data)
        hashes[name]=hashlib.sha256(data).hexdigest()
    return hashes


def physical_members(model, scheme):
    nodes=model._parse_node_coordinates();sections=model._frame_section_properties()
    assignments=model._element_section_assignments()
    steels={model._parse_key_values(line)['Material']:model._parse_key_values(line)
            for line in model._table_lines('MATERIAL PROPERTIES 03A - STEEL DATA')}
    basics={model._parse_key_values(line)['Material']:model._parse_key_values(line)
            for line in model._table_lines('MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES')}
    result={}
    for tag,item in sorted(model._parse_element_connectivity().items()):
        ni,nj=item['node_i'],item['node_j'];section=sections[assignments[tag]['section_name']]
        grade=section['material_name'];fy=float(steels[grade]['Fy'])*1e6;E=float(basics[grade]['E1'])
        result[tag]=dict(node_i=ni,node_j=nj,chord=[nodes[nj][a]-nodes[ni][a] for a in 'xyz'],
            section_name=section['section_name'],grade=grade,area_m2=section['area'],fy_Pa=fy,E_Pa=E,Afy_N=section['area']*fy,
            segments=[tag] if scheme=='tmq' else model.element_segment_map[tag])
    return nodes,result


def inspect_fibers(ops, member):
    """Every fiber at every integration point of all four segments; no N/A yield proxy."""
    stress=0.;strain=0.;tension=0.;compression=0.;critical=(None,None);crossed=0
    for element in member['segments']:
        for ip in range(1,7):
            data=ops.eleResponse(element,'section',ip,'fiberData')
            if not data or len(data)%5:raise RuntimeError(f'Missing fiberData {element}/{ip}')
            values=data[3::5];eps=data[4::5]
            local=max(abs(v) for v in values)
            if local>stress:stress=local;critical=(element,ip)
            strain=max(strain,max(abs(v) for v in eps))
            tension=max(tension,max(values));compression=min(compression,min(values))
            crossed+=sum(abs(v)>=member['fy_Pa'] for v in values)
    return dict(max_abs_stress_Pa=stress,max_abs_strain=strain,max_tension_stress_Pa=tension,
                min_compression_stress_Pa=compression,fiber_stress_over_fy=stress/member['fy_Pa'],
                fiber_strain_over_ey=strain/(member['fy_Pa']/member['E_Pa']),fibers_at_or_above_fy=crossed,
                critical_segment=critical[0],critical_integration_point=critical[1])


def run_case(output,scheme,angle,*,target_drift=.03,case_budget=1200.):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError(f'Refusing to overwrite {output}')
    if not math.isfinite(target_drift) or target_drift<=0 or not math.isfinite(case_budget) or case_budget<=0:
        raise ValueError('Positive finite target and budget required')
    dof=control_dof(angle)
    if scheme not in SCHEMES:raise ValueError(scheme)
    output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();hashes=freeze_sources(output)
    import openseespy.opensees as ops
    from initial_imperfection_material.full_tower_cyclic import _apply_gravity
    from initial_imperfection_material.tian_ma_qu.directional_loading import verification_config,build_load_plan
    from initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison import project_end_forces
    from util.processing.directional_wind import apply_nodal_wind_loads,wind_unit_vector,nodal_resultant
    from util.processing.member_state_recorder import MemberStateRecorder
    from util.analysis.equilibrium_checks import static_equilibrium
    from util.analysis.stepping import AdaptiveStepper,Algorithm
    from .evidence import section_groups,drift_metrics,curve_evidence
    summary=dict(schema='otw2.tower_material_pushover_case.v1',scheme=scheme,angle_deg=angle,status='building',
        target_control_drift=target_drift,control_node=CONTROL_NODE,control_dof=dof,accepted_steps=0,
        case_budget_seconds=case_budget,code_sha256=hashes,engine_version=ops.version(),
        source_sha256=hashlib.sha256((ROOT/'Source/Z30103A6.s2k').read_bytes()).hexdigest(),
        physical_validation=False,damage_state_thresholds_established=False,
        stop_policy='first failed Newton increment stops; no fallback, tolerance relaxation, arc-length or model repair',
        material_note='Steel01/Steel02 share four-segment fibers; TMQ uses one straight member-equivalent axial law plus uncoupled elastic bending/torsion; not a pure steel-law substitution',
        scope='single tower, constant gravity, initial-geometry fixed directional nodal wind pattern; displacement-controlled quasi-static, not time history')
    write_json(output/'summary.json',summary)
    streams={};writers={};history=[];state_recorder=None;stepper=None
    def stream(name):
        if name not in streams:streams[name]=(output/name).open('w',encoding='utf-8',newline='')
        return streams[name]
    def csv_record(name,row):
        if name not in writers:
            writers[name]=csv.DictWriter(stream(name),fieldnames=list(row));writers[name].writeheader()
        writers[name].writerow(row)
    def json_record(name,row):
        f=stream(name);f.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n');f.flush()
    def checkpoint():
        summary['wall_seconds']=time.monotonic()-started
        write_json(output/'summary.json',summary)
    try:
        ops.wipe();model=build_model(scheme,output/'model_data')
        build_start=time.monotonic();model.model_tower()
        print(f'BUILT {scheme}: {time.monotonic()-build_start:.1f}s',flush=True)
        summary['build_seconds']=time.monotonic()-build_start
        nodes,members=physical_members(model,scheme);base=sorted(model.fix_map)
        height=nodes[CONTROL_NODE]['z']-min(nodes[n]['z'] for n in base)
        direction=wind_unit_vector(angle);top_z=max(n['z'] for n in nodes.values())
        top_nodes=[n for n in nodes if abs(nodes[n]['z']-top_z)<1e-8]
        summary.update(control_height_m=height,top_height_m=top_z,top_nodes=top_nodes,
            material_parameters=model.material_tag_map if scheme!='tmq' else {'coefficient_case':model.coefficient_case,'mapping':'S2K E/fy/A/L, Perry K=1 phi, tube cyclic coefficients unvalidated'},
            finite_element_nodes=len(ops.getNodeTags()),finite_elements=len(ops.getEleTags()),physical_members=len(members))
        loads,plan=build_load_plan(model,verification_config(angle,wind_speed_m_s=20.))
        write_json(output/'wind_load_plan.json',plan)
        for n,v in sorted(loads.items()):csv_record('wind_nodal_loads.csv',dict(node_tag=n,**dict(zip(('Fx_N','Fy_N','Fz_N','Mx_Nm','My_Nm','Mz_Nm'),v))))
        audit=dict(original_geometry_sha256=digest(nodes),
            physical_member_inputs_sha256=digest({n:{k:v for k,v in r.items() if k!='segments'} for n,r in members.items()}),
            nodal_mass_sha256=digest({n:[r[k] for k in ('mx','my','mz','mrx','mry','mrz')] for n,r in model.mass_map.items()}),
            supports_sha256=digest({n:[r[k] for k in DOF_NAMES] for n,r in model.fix_map.items()}),
            wind_nodal_load_sha256=digest(loads),reference_wind_resultant=plan['combined_initial_coordinate_resultant'])
        summary['input_audit']=audit;write_json(output/'input_audit.json',audit)
        groups=section_groups(nodes);write_json(output/'section_groups.json',groups)
        state_recorder=MemberStateRecorder(model,output/'critical_member_history.jsonl',members=CRITICAL_MEMBERS,record_fibers=scheme!='tmq')
        state_recorder.capture(stage_id='initial',step=0,progress=0.)
        def save_nodes(stage,step):
            disps={n:list(ops.nodeDisp(n)) for n in nodes}
            for n,v in disps.items():csv_record('node_states.csv',dict(stage=stage,step=step,node_tag=n,**dict(zip(DOF_NAMES,v))))
            return disps
        save_nodes('initial',0);summary['status']='gravity'
        summary['gravity_solver']={'algorithm':'Newton','test':['NormDispIncr',1e-7,120],'steps':10}
        checkpoint()
        def gravity_callback(step,total,gravity):
            save_nodes('gravity',step)
            state_recorder.capture(stage_id='gravity',step=step,progress=step/total)
            csv_record('gravity_history.csv',dict(step=step,factor=step/total,control_displacement_m=float(ops.nodeDisp(CONTROL_NODE,dof))))
            for f in streams.values():f.flush()
            summary['gravity_completed_steps']=step;checkpoint()
            if time.monotonic()-started>case_budget:raise TimeoutError('case budget reached during gravity')
        gravity_start=time.monotonic();gravity=_apply_gravity(model,steps=10,on_step=gravity_callback)
        gravity_disps={n:list(ops.nodeDisp(n)) for n in nodes};gravity_u=gravity_disps[CONTROL_NODE][dof-1]
        ops.reactions();gravity_shear=[-sum(float(ops.nodeReaction(n,d)) for n in base) for d in (1,2,3)]
        summary.update(gravity_seconds=time.monotonic()-gravity_start,gravity_control_displacement_m=gravity_u,
                       gravity_completed=True,gravity_base_shear_N=gravity_shear,status='pushing')
        wind=apply_nodal_wind_loads(loads,model.tag_manager,ops)
        constrained={(int(n),d) for n,fix in model.fix_map.items() for d,key in enumerate(DOF_NAMES,1) if fix[key]}
        rotations={(int(n),d) for n in ops.getNodeTags() for d in (4,5,6)}
        ever_yielded=set()
        def capture():
            step=len(history);factor=float(ops.getLoadFactor(wind.pattern_tag));current=save_nodes('pushover',step)
            combined={int(n):list(v) for n,v in gravity.node_loads.items()}
            for n,v in loads.items():
                dest=combined.setdefault(int(n),[0.]*6)
                for d,value in enumerate(v):dest[d]+=factor*value
            ledger={(n,d):v for n,vec in combined.items() for d,v in enumerate(vec,1)}
            scale=max(1.,sum(abs(v) for (n,d),v in ledger.items() if d<=3))
            eq=static_equilibrium(ops,ledger,constrained_dofs=constrained,rotational_dofs=rotations,
                force_scale=scale,moment_scale=scale*height,relative_tolerance=1e-6,
                force_absolute_tolerance=.001,moment_absolute_tolerance=.001)
            eq.pop('free_dof_residuals');json_record('equilibrium.jsonl',dict(step=step,**eq))
            ops.reactions();reactions={n:list(ops.nodeReaction(n)) for n in base}
            for n,v in reactions.items():csv_record('support_reactions.csv',dict(step=step,node_tag=n,**dict(zip(('Rx_N','Ry_N','Rz_N','Mx_Nm','My_Nm','Mz_Nm'),v))))
            shear=[-sum(v[d] for v in reactions.values()) for d in range(3)]
            incremental=[shear[d]-gravity_shear[d] for d in range(3)]
            delta=[current[CONTROL_NODE][d]-gravity_disps[CONTROL_NODE][d] for d in range(3)]
            along=sum(delta[d]*direction[d] for d in range(3))
            drift=drift_metrics(groups,current,gravity_disps,angle)
            for row in drift['rows']:csv_record('panel_history.csv',dict(step=step,**row))
            tmq_states={s['element_tag']:s for s in model.committed_member_states()} if scheme=='tmq' else {}
            yielded=[];maxstress=0.;maxstrain=0.;worst=None;maxdemand=0.
            for tag,m in members.items():
                first,last=ops.eleForce(m['segments'][0]),ops.eleForce(m['segments'][-1])
                ni,nj,mean=project_end_forces(first,last,m['chord'])
                envelope=dict(step=step,member_id=tag,node_i=m['node_i'],node_j=m['node_j'],N_i_N=ni,N_j_N=nj,N_mean_N=mean,
                    abs_N_over_Afy=abs(mean)/m['Afy_N'],
                    **{f'{end}_{axis}':force[offset+k] for end,force,offset in [('i',first,0),('j',last,6)]
                       for k,axis in enumerate(('Fx_N','Fy_N','Fz_N','Mx_Nm','My_Nm','Mz_Nm'))})
                maxdemand=max(maxdemand,abs(mean)/m['Afy_N'])
                if scheme=='tmq':envelope.update({k:v for k,v in tmq_states[tag].items() if k!='element_tag'})
                else:
                    fiber=inspect_fibers(ops,m);envelope.update(fiber)
                    if fiber['fiber_stress_over_fy']>=1:yielded.append(tag);ever_yielded.add(tag)
                    if fiber['fiber_stress_over_fy']>maxstress:maxstress=fiber['fiber_stress_over_fy'];worst=tag
                    maxstrain=max(maxstrain,fiber['fiber_strain_over_ey'])
                csv_record('member_envelopes.csv',envelope)
            top_delta=[[current[n][d]-gravity_disps[n][d] for d in range(3)] for n in top_nodes]
            row=dict(step=step,committed=True,control_displacement_m=current[CONTROL_NODE][dof-1],
                relative_control_displacement_m=delta[dof-1],control_drift_ratio=delta[dof-1]/height,
                control_ux_m=delta[0],control_uy_m=delta[1],along_wind_displacement_m=along,along_wind_drift_ratio=along/height,
                horizontal_drift_ratio=math.hypot(*delta[:2])/height,
                top_mean_along_displacement_m=sum(sum(v[d]*direction[d] for d in range(3)) for v in top_delta)/len(top_delta),
                top_max_horizontal_displacement_m=max(math.hypot(*v[:2]) for v in top_delta),
                base_shear_x_N=incremental[0],base_shear_y_N=incremental[1],
                base_shear_along_N=sum(incremental[d]*direction[d] for d in range(3)),wind_load_factor=factor,
                max_abs_raw_along_drift=drift['max_abs_raw_along_drift'],max_abs_corrected_along_drift=drift['max_abs_corrected_along_drift'],
                fiber_yielded_members=len(yielded) if scheme!='tmq' else None,
                fiber_ever_yielded_members=len(ever_yielded) if scheme!='tmq' else None,
                max_fiber_stress_over_fy=maxstress if scheme!='tmq' else None,
                max_fiber_strain_over_ey=maxstrain if scheme!='tmq' else None,max_fiber_demand_member=worst,
                max_abs_N_over_Afy=maxdemand,
                tmq_buckled_members=sum(s['buckling_count']>0 for s in tmq_states.values()) if scheme=='tmq' else None,
                tmq_tension_yield_members=sum(s['tension_yield_ever'] for s in tmq_states.values()) if scheme=='tmq' else None,
                equilibrium_passed=eq['passed'],force_residual_N=eq['translation']['maximum_absolute'],
                moment_residual_Nm=eq['rotation']['maximum_absolute'],wall_seconds=time.monotonic()-started)
            history.append(row);csv_record('history.csv',row)
            state_recorder.capture(stage_id='pushover',step=step,progress=delta[dof-1],direction=1)
            for f in streams.values():f.flush()
            summary.update(accepted_steps=step,last_point=row,curve_evidence=curve_evidence(history,height))
            checkpoint()
            print(f"STEP {step} u={delta[dof-1]:.5f}m V={row['base_shear_along_N']/1000:.3f}kN fiber={row['fiber_yielded_members']} tmq={row['tmq_buckled_members']}",flush=True)
            if not eq['passed']:raise RuntimeError('committed state rejected by independent equilibrium; retained but excluded from valid capacity prefix')
        capture()
        ops.wipeAnalysis();ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
        ops.test('NormUnbalance',.005,40,0);ops.algorithm('Newton')
        ops.integrator('DisplacementControl',CONTROL_NODE,dof,.002);ops.analysis('Static')
        def log_attempt(event):
            if event.get('norms') is None and hasattr(ops,'testNorm'):
                norms=list(ops.testNorm())[:max(0,event.get('iterations') or 0)]
                event['norms']=[float(v) if math.isfinite(float(v)) else str(v) for v in norms]
            event.update(next_step=len(history),wind_load_factor=float(ops.getLoadFactor(wind.pattern_tag)),
                         control_drift_after=(float(ops.nodeDisp(CONTROL_NODE,dof))-gravity_u)/height)
            json_record('attempts.jsonl',event)
        stepper=AdaptiveStepper(ops,progress=lambda:float(ops.nodeDisp(CONTROL_NODE,dof)),
            configure_increment=lambda inc:ops.integrator('DisplacementControl',CONTROL_NODE,dof,inc),
            algorithms=(Algorithm('Newton'),),convergence_test=('NormUnbalance',.005,40,0),minimum_increment=1e-6,
            maximum_attempts_per_step=1,maximum_total_attempts=1000,maximum_accepted_steps=1000,
            timeout_seconds=max(1.,case_budget-(time.monotonic()-started)),on_attempt=log_attempt)
        summary['solver_settings']=stepper.settings();checkpoint()
        target=target_drift*height
        while history[-1]['relative_control_displacement_m']<target-1e-9:
            if time.monotonic()-started>case_budget:
                summary.update(status='partial',stop_reason='case_time_budget');break
            current=history[-1]['relative_control_displacement_m'];increment=displacement_increment(current,target-current)
            summary['pending_target_displacement_m']=current+increment;checkpoint()
            result=stepper.step(increment)
            if not result.converged:
                summary.update(status='partial',stop_reason='first_newton_nonconvergence' if result.attempts>0 and result.return_code!=0 else result.stop_reason,
                    stepper_stop_reason=result.stop_reason,failed_target_displacement_m=current+increment,
                    failed_target_control_drift=(current+increment)/height,failed_return_code=result.return_code)
                break
            summary.pop('pending_target_displacement_m',None)
            capture()
            if history[-1]['wind_load_factor']<0:
                summary.update(status='partial',stop_reason='negative_load_factor_outside_positive_wind_pattern');break
        else:summary.update(status='complete',stop_reason=None)
    except Exception as error:
        summary.update(status='stopped',stop_reason=f'{type(error).__name__}: {error}')
        print(summary['stop_reason'],flush=True)
    finally:
        if state_recorder is not None:state_recorder.close()
        for f in streams.values():f.close()
        if stepper is not None:summary['solver_diagnostics']=stepper.diagnostics()
        if history:summary['curve_evidence']=curve_evidence(history,summary['control_height_m'])
        summary['all_saved_equilibria_passed']=bool(history) and all(r['equilibrium_passed'] for r in history)
        checkpoint();ops.wipe()
    return summary


def execute_case(root,scheme,angle,target_drift,case_budget):
    key=f'{scheme}_deg_{angle}';output=root/'runs'/key
    if (output/'summary.json').exists():
        previous=json.loads((output/'summary.json').read_text())
        if previous.get('scheme')!=scheme or previous.get('angle_deg')!=angle or previous.get('target_control_drift')!=target_drift:
            raise ValueError(f'Existing case has different inputs: {output}')
        return dict(key=key,reused=True,summary=previous)
    root.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONUNBUFFERED='1')
    cmd=[sys.executable,'-m','initial_imperfection_material.tower_material_pushover.experiment','--worker',
         '--output',str(output),'--scheme',scheme,'--angle',str(angle),'--target-drift',str(target_drift),'--case-budget',str(case_budget)]
    with (root/f'{key}.log').open('w') as log:
        process=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:code=process.wait(timeout=case_budget+120)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            p=output/'summary.json';s=json.loads(p.read_text()) if p.exists() else {}
            s.update(status='partial',stop_reason='worker_hard_timeout',hard_timeout_seconds=case_budget+120)
            write_json(p,s);code=-1
    return dict(key=key,returncode=code,summary=json.loads((output/'summary.json').read_text()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=OUTPUT);p.add_argument('--worker',action='store_true')
    p.add_argument('--scheme',choices=SCHEMES,default=SCHEMES[0]);p.add_argument('--angle',type=int,default=0)
    p.add_argument('--angles',type=int,nargs='+',default=list(ANGLES));p.add_argument('--schemes',nargs='+',choices=SCHEMES,default=list(SCHEMES))
    p.add_argument('--target-drift',type=float,default=.03);p.add_argument('--case-budget',type=float,default=1200.)
    p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args()
    if a.worker:
        run_case(a.output,a.scheme,a.angle,target_drift=a.target_drift,case_budget=a.case_budget);return
    if any(angle not in ANGLES for angle in a.angles):p.error('unsupported angle')
    a.output.mkdir(parents=True,exist_ok=True)
    matrix=[(scheme,angle) for angle in a.angles for scheme in a.schemes]
    plan=dict(schema='otw2.tower_material_pushover_plan.v1',matrix=matrix,target_control_drift=a.target_drift,
              case_budget_seconds=a.case_budget,stop_policy='stop at first Newton failure',parallel_processes=a.jobs)
    plan_path=a.output/'plan.json'
    if plan_path.exists():
        previous=json.loads(plan_path.read_text())
        if previous!=plan:write_json(a.output/('plan_'+str(time.time_ns())+'.json'),plan)
    else:write_json(plan_path,plan)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures=[pool.submit(execute_case,a.output,scheme,angle,a.target_drift,a.case_budget) for scheme,angle in matrix]
        for future in futures:
            result=future.result();print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
