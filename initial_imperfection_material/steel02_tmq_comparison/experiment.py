"""Same geometry, steel, end displacement and explicit numerical coverage.

The reference is a planar pin-ended weak-axis fiber member, not a complete
three-dimensional angle or a verified physical test. TMQ coefficients are the
existing tower transfer, not refitted to make this comparison look favorable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import openseespy.opensees as ops

from ..experiment import _equal_angle_weak_axis_fibers, section_discretization_check
from ..material import MemberProperties, EquivalentImperfectionMaterial
from ..tian_ma_qu.cases import literature_cases
from ..tian_ma_qu.material import TianMaQuPrototype
from ..tian_ma_qu.opensees_adapter import register_material

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "results"
STEEL02 = dict(R0=20.0, cR1=.925, cR2=.15, a1=0., a2=1., a3=0., a4=1.)
SOLVER = dict(test="NormUnbalance", tolerance=1e-5, iterations=60,
              algorithm="Newton", fallback="NewtonLineSearch", fallback_iterations=120,
              max_bisections=8, maximum_runtime_seconds=180.)


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def members():
    """Read the original S2K geometry using the project's read-only parser."""
    from model.tower_model import OpenSeesModel
    source = ROOT / "Source/Z30103A6.s2k"
    # The saved member export is independently checked against S2K nodes below.
    export = ROOT / "initial_imperfection_material/tian_ma_qu/tower_results/tmq_bounded_03/model_data/tmq_member_parameters.csv"
    with export.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    angles = sorted((r for r in rows if r['section_name'] == 'L125x8Q345'),
                    key=lambda r: (float(r['length_m']), int(r['element_tag'])))
    selected = angles[len(angles)//2]
    length = float(selected['length_m'])
    member = MemberProperties.z30103a6_l125x8(length=length)
    for key, expected in [('area_m2',member.area), ('weak_inertia_m4',member.inertia_weak),
                          ('elastic_modulus',member.elastic_modulus), ('yield_stress',member.yield_strength)]:
        if not math.isclose(float(selected[key]), expected, rel_tol=1e-12):
            raise ValueError(f"Tower export differs from member geometry: {key}")
    # Do not mutate or rebuild the tower. Parse its table records directly.
    text = source.read_text(encoding='utf-8-sig')
    tables = {}; current = None
    for line in text.splitlines():
        if line.startswith('TABLE:'):
            current = line.split('"')[1]; tables[current] = []
        elif current and '=' in line:
            tables[current].append(OpenSeesModel._parse_key_values(line))
    coordinates = {r['Joint']: tuple(float(r[k]) for k in ('XorR','Y','Z'))
                   for r in tables['JOINT COORDINATES']}
    frame = next(r for r in tables['CONNECTIVITY - FRAME'] if r['Frame'] == selected['element_tag'])
    measured_length = math.dist(coordinates[frame['JointI']], coordinates[frame['JointJ']])
    if not math.isclose(length, measured_length, rel_tol=1e-10):
        raise ValueError("Saved selected length is not the S2K node distance")
    records=[r for group in tables.values() for r in group]
    section=next(r for r in records if r.get('SectionName')=='L125x8Q345' and 'I23' in r)
    basic=next(r for r in records if r.get('Material')=='Q345' and 'E1' in r)
    steel=next(r for r in records if r.get('Material')=='Q345' and 'Fy' in r)
    for a,b in ((float(section['Area']),member.area),
                (float(section['I22'])-abs(float(section['I23'])),member.inertia_weak),
                (float(basic['E1']),member.elastic_modulus),(float(steel['Fy'])*1e6,member.yield_strength)):
        if not math.isclose(a,b,rel_tol=1e-12):raise ValueError('S2K material/section properties changed')
    provenance = dict(selected_original_frame=int(selected['element_tag']), frame=frame,
        count=len(angles), minimum_length_m=float(angles[0]['length_m']),
        maximum_length_m=float(angles[-1]['length_m']), selected_length_m=length,
        source=str(source.relative_to(ROOT)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        selection='upper median by length, then frame id; verified against original endpoint coordinates',
        note='Pin-ended K=1 is a controlled experiment boundary, not an identified tower joint restraint.')
    return {'tower_median': member, 'long_demo': replace(member, length=3.)}, provenance


def parameters(member, imperfection_ratio=.001):
    template = literature_cases()[0].parameters
    peak = EquivalentImperfectionMaterial._perry_peak_load(member, imperfection_ratio)
    return replace(template, elastic_modulus=member.elastic_modulus,
        yield_stress=member.yield_strength, rho=member.steel_hardening_ratio,
        phi=peak/(member.area*member.yield_strength),
        provenance='Existing tower mapping: actual E/fy/A/L; K=1 Perry first-fiber-yield phi; '
                   'P102-row-A tube cyclic coefficients transferred without angle calibration')


def initial_coordinates(length, divisions, ratio, shape='half_sine'):
    if divisions < 2 or divisions % 2: raise ValueError('Use even divisions >=2')
    if length <= 0 or ratio < 0: raise ValueError('Invalid geometry')
    station = np.linspace(0., 1., divisions+1)
    if shape == 'half_sine': factor = np.sin(np.pi*station)
    elif shape == 'triangle': factor = 1-np.abs(2*station-1)
    elif shape == 'legacy_midpoint_only':
        if divisions != 4: raise ValueError('Legacy middle-only shape is defined only at four divisions')
        factor = np.array([0.,0.,1.,0.,0.])
    else: raise ValueError(shape)
    factor[0] = factor[-1] = 0.
    return np.column_stack((length*ratio*factor, length*station))


def protocol(member, name, *, refinement=1):
    ey = member.yield_strength/member.elastic_modulus
    if name == 'monotonic': targets = [0., -.015]; step = .015/600/refinement
    elif name == 'elastic': targets = [0., -.0003, 0.]; step = .0003/40/refinement
    elif name == 'cyclic':
        targets = [0., -.0003, 0.]
        for multiple in (.5, 1., 2., 4., 6.):
            a = ey*multiple
            targets += [-a, a, -a, a]
        targets += [0.]
        step = ey/16/refinement
    else: raise ValueError(name)
    points = [dict(target_index=0, leg=0, strain=0., target=True)]
    for leg,(a,b) in enumerate(zip(targets,targets[1:]),1):
        n = math.ceil(abs(b-a)/step)
        for j in range(1,n+1):
            points.append(dict(target_index=len(points), leg=leg,
                               strain=a+(b-a)*j/n, target=j==n))
    return points, targets


def build(member, scheme, divisions=4, ratio=.001, shape='half_sine', formulation='disp', elastic=False):
    ops.wipe()
    if scheme == 'segmented':
        ops.model('basic','-ndm',2,'-ndf',3)
        coordinates = initial_coordinates(member.length, divisions, ratio, shape)
        for tag, (x,y) in enumerate(coordinates,1): ops.node(tag,float(x),float(y))
        ops.fix(1,1,1,0); ops.fix(divisions+1,1,0,0)
        if elastic: ops.uniaxialMaterial('Elastic',1,member.elastic_modulus)
        else:
            ops.uniaxialMaterial('Steel02',1,member.yield_strength,member.elastic_modulus,
                member.steel_hardening_ratio, *STEEL02.values())
        fibers = _equal_angle_weak_axis_fibers(member)
        ops.section('Fiber',1)
        for y,a in fibers: ops.fiber(y,0.,a,1)
        ops.geomTransf('Corotational',1)
        integration, count, element = ('Legendre',6,'dispBeamColumn') if formulation=='disp' else ('Lobatto',5,'forceBeamColumn')
        ops.beamIntegration(integration,1,1,count)
        for tag in range(1,divisions+1): ops.element(element,tag,tag,tag+1,1,1)
        node,dof = divisions+1,2
        metadata = dict(elements=divisions, free_dofs=3*divisions,
            coordinates=coordinates.tolist(), integration=integration, integration_points=count,
            element=element, section=section_discretization_check(member,fibers),
            probes=[min(y for y,a in fibers),max(y for y,a in fibers)], elastic_control=elastic)
    else:
        ops.model('basic','-ndm',1,'-ndf',1)
        ops.node(1,0.); ops.node(2,member.length); ops.fix(1,1)
        if scheme=='tmq':
            p=parameters(member,ratio); register_material(1,p)
            metadata=dict(tmq_parameters=p.to_dict())
        elif scheme=='straight_steel02':
            ops.uniaxialMaterial('Steel02',1,member.yield_strength,member.elastic_modulus,
                member.steel_hardening_ratio,*STEEL02.values());metadata={}
        else: raise ValueError(scheme)
        ops.element('truss',1,1,2,member.area,1)
        node,dof=2,1
        metadata.update(elements=1,free_dofs=1,element='truss',integration_points=0)
    ops.timeSeries('Linear',1); ops.pattern('Plain',1,1)
    if dof==2: ops.load(node,0.,1.,0.)
    else: ops.load(node,1.)
    ops.constraints('Plain');ops.numberer('RCM');ops.system('BandGeneral')
    ops.test(SOLVER['test'],SOLVER['tolerance'],SOLVER['iterations'],0)
    ops.algorithm('Newton');ops.integrator('DisplacementControl',node,dof,1e-6);ops.analysis('Static')
    return node,dof,metadata


def run_case(member, points, *, scheme, divisions=4, ratio=.001, shape='half_sine', formulation='disp', elastic=False):
    start=time.perf_counter();node,dof,metadata=build(member,scheme,divisions,ratio,shape,formulation,elastic)
    rows=[];attempts=[];failure=None
    observer=TianMaQuPrototype(parameters(member,ratio)) if scheme=='tmq' else None
    final_completed=0
    def capture(item, requested, depth):
        u=float(ops.nodeDisp(node,dof));force=float(ops.getLoadFactor(1));ops.reactions()
        r=float(ops.nodeReaction(1,dof));fiber_stress=0.;fiber_strain=0.
        if scheme=='segmented':
            for tag in range(1,divisions+1):
                for section in range(1,metadata['integration_points']+1):
                    for y in metadata['probes']:
                        s,e=ops.eleResponse(tag,'section',section,'fiber',y,0.,'stressStrain')
                        fiber_stress=max(fiber_stress,abs(s));fiber_strain=max(fiber_strain,abs(e))
            mid=divisions//2+1
            lateral=float(ops.nodeDisp(mid,1));absolute=float(ops.nodeCoord(mid,1))+lateral
        else: lateral=absolute=0.
        stage='fiber_member' if scheme=='segmented' else 'straight_steel02'
        check=0.
        if observer:
            observer.set_trial_strain(u/member.length);state=observer.get_state()
            stage=state['stage'];check=abs(force-member.area*state['stress']);observer.commit_state()
        row=dict(sequence=len(rows), target_index=item['target_index'],leg=item['leg'],
            requested_point=requested,protocol_target=requested and item['target'],
            strain=u/member.length,displacement_m=u,force_N=force,reaction_N=r,
            reaction_balance_N=abs(force+r),midspan_lateral_increment_m=lateral,
            midspan_lateral_total_m=absolute,max_abs_fiber_stress_Pa=fiber_stress,
            max_abs_fiber_strain=fiber_strain,stage=stage,subdivision_depth=depth,
            iterations=0 if not rows else int(ops.testIter()),observer_force_error_N=check)
        row['external_work_J']=0. if not rows else rows[-1]['external_work_J']+.5*(rows[-1]['force_N']+force)*(u-rows[-1]['displacement_m'])
        rows.append(row)
    def advance(item,target,depth):
        nonlocal failure
        if time.perf_counter()-start>SOLVER['maximum_runtime_seconds']:
            failure=dict(kind='runtime_budget',target_index=item['target_index'],depth=depth);return False
        for algorithm in ('Newton','NewtonLineSearch'):
            increment=target-float(ops.nodeDisp(node,dof))
            ops.test(SOLVER['test'],SOLVER['tolerance'],SOLVER['iterations'] if algorithm=='Newton' else SOLVER['fallback_iterations'],0)
            ops.algorithm(algorithm)
            ops.integrator('DisplacementControl',node,dof,increment)
            code=ops.analyze(1)
            norms=ops.testNorm(); it=int(ops.testIter())
            norm=float(norms[min(max(it-1,0),len(norms)-1)]) if len(norms) else None
            attempts.append(dict(target_index=item['target_index'],depth=depth,algorithm=algorithm,
                increment_m=increment,code=int(code),iterations=it,
                residual_norm=norm if norm is not None and math.isfinite(norm) else None))
            if code==0:
                capture(item,abs(target-item['strain']*member.length)<1e-12,depth);return True
        if depth>=SOLVER['max_bisections']:
            failure=dict(kind='nonconvergence',target_index=item['target_index'],target_displacement_m=target,
                         last_displacement_m=float(ops.nodeDisp(node,dof)),depth=depth,return_code=int(code));return False
        halfway=.5*(float(ops.nodeDisp(node,dof))+target)
        return advance(item,halfway,depth+1) and advance(item,target,depth+1)
    try:
        capture(points[0],True,0)
        for item in points[1:]:
            if not advance(item,item['strain']*member.length,0):break
            final_completed=item['target_index']
        iterations=[r['iterations'] for r in rows[1:]]
        info=dict(scheme=scheme,divisions=divisions if scheme=='segmented' else 1,
            imperfection_ratio=ratio,shape=shape if scheme=='segmented' else 'equivalent_in_phi_no_geometric_bow',
            formulation=formulation if scheme=='segmented' else 'axial_truss',
            metadata=metadata,requested_steps=len(points)-1,completed_steps=final_completed,
            accepted_substeps=len(rows)-1,complete=final_completed==len(points)-1,failure=failure,
            runtime_seconds=time.perf_counter()-start,attempts=len(attempts),
            failed_attempts=sum(a['code']!=0 for a in attempts),
            accepted_iterations_mean=float(np.mean(iterations)) if iterations else None,
            accepted_iterations_max=max(iterations,default=0),
            total_attempted_iterations=sum(a['iterations'] for a in attempts),
            max_reaction_balance_N=max(r['reaction_balance_N'] for r in rows),
            max_observer_force_error_N=max(r['observer_force_error_N'] for r in rows),
            peak_compression_kN=-min(r['force_N'] for r in rows)/1000,
            peak_tension_kN=max(r['force_N'] for r in rows)/1000,
            peak_compression_displacement_mm=min(rows,key=lambda r:r['force_N'])['displacement_m']*1000,
            final_force_kN=rows[-1]['force_N']/1000,
            max_fiber_stress_over_fy=max(r['max_abs_fiber_stress_Pa'] for r in rows)/member.yield_strength,
            external_work_J=rows[-1]['external_work_J'],
            work_note='Signed integral N du; not automatically dissipated energy, final state may differ.')
        return rows,attempts,info
    finally: ops.wipe()


def compare(reference, candidate, normalization, *, requested_steps):
    """Same requested protocol indices only; never sort by cyclic displacement."""
    left={r['target_index']:r for r in reference if r['requested_point']}
    right={r['target_index']:r for r in candidate if r['requested_point']}
    keys=sorted(left.keys() & right.keys())
    if len(keys)<2: return dict(common_points=len(keys),nrmse=None)
    if any(abs(left[k]['displacement_m']-right[k]['displacement_m'])>1e-10 for k in keys):
        raise ValueError('Mismatched ordered loading histories')
    error=np.array([right[k]['force_N']-left[k]['force_N'] for k in keys])
    return dict(common_points=len(keys),reference_points=len(left),candidate_points=len(right),
        full_common_history=keys==list(range(requested_steps+1)),
        requested_steps=requested_steps,coverage=(len(keys)-1)/requested_steps,
        nrmse=float(np.sqrt(np.mean(error**2))/normalization),normalization='A fy',
        maximum_abs_force_difference_kN=float(np.max(np.abs(error)))/1000,
        reference_common_work_J=left[keys[-1]]['external_work_J'],
        candidate_common_work_J=right[keys[-1]]['external_work_J'])


def run(output=OUTPUT):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    specimens,selection=members(); cases={};histories={}
    plan=[]
    for key,m in specimens.items():
        for loading in ('monotonic','cyclic','elastic'):
            for n in (4,8,16,32) if loading=='monotonic' else (4,16):
                plan.append(dict(key=f'{key}_{loading}_steel02_{n}',member=key,loading=loading,scheme='segmented',divisions=n))
            for scheme in ('tmq','straight_steel02'):
                plan.append(dict(key=f'{key}_{loading}_{scheme}',member=key,loading=loading,scheme=scheme))
        for ratio,name in ((.0005,'l2000'),(.002,'l500')):
            plan.append(dict(key=f'{key}_imperfection_{name}',member=key,loading='monotonic',scheme='segmented',divisions=16,ratio=ratio))
        for shape in ('triangle','legacy_midpoint_only'):
            plan.append(dict(key=f'{key}_shape_{shape}',member=key,loading='monotonic',scheme='segmented',divisions=4,shape=shape))
        for n in (4,16):
            plan.append(dict(key=f'{key}_forcebeam_{n}',member=key,loading='monotonic',scheme='segmented',divisions=n,formulation='force'))
            plan.append(dict(key=f'{key}_cyclic_forcebeam_{n}',member=key,loading='cyclic',scheme='segmented',divisions=n,formulation='force'))
        plan.append(dict(key=f'{key}_monotonic_step_half',member=key,loading='monotonic',scheme='segmented',divisions=16,refinement=2))
    save_json(output/'plan.json',dict(specimens={k:asdict(v) for k,v in specimens.items()},selection=selection,
        solver=SOLVER,steel02=STEEL02,cases=plan,tmq_coefficients_refitted=False,
        physical_validation=False,scope='2D weak-axis pinned member; no local/torsional buckling, bolt slip, residual stresses or fracture'))
    for case in plan:
        key=case['key'];m=specimens[case['member']]
        points,targets=protocol(m,case['loading'],refinement=case.get('refinement',1))
        kwargs={k:v for k,v in case.items() if k not in ('key','member','loading','refinement')}
        rows,attempts,info=run_case(m,points,**kwargs)
        info.update(key=key,member=case['member'],loading=case['loading'],targets_strain=targets)
        folder=output/'runs'/key;folder.mkdir(parents=True,exist_ok=True)
        write_csv(folder/'history.csv',rows);write_csv(folder/'attempts.csv',attempts);save_json(folder/'summary.json',info)
        histories[key]=rows;cases[key]=info
        print(json.dumps(dict(case=key,complete=info['complete'],steps=info['completed_steps'],
            peak_kN=info['peak_compression_kN'],failed_attempts=info['failed_attempts'],seconds=info['runtime_seconds'])),flush=True)
    comparisons={}
    for key,m in specimens.items():
        for loading in ('monotonic','cyclic','elastic'):
            base=f'{key}_{loading}_steel02_16'
            for suffix in ('steel02_4','tmq','straight_steel02'):
                other=f'{key}_{loading}_{suffix}'
                comparisons[other]=compare(histories[base],histories[other],m.area*m.yield_strength,
                                           requested_steps=cases[base]['requested_steps'])
            if loading=='cyclic':
                for n in (4,16):
                    other=f'{key}_cyclic_forcebeam_{n}'
                    comparisons[other]=compare(histories[base],histories[other],m.area*m.yield_strength,
                                               requested_steps=cases[base]['requested_steps'])
        # Do not apply equal-index metrics to the refined time grid.
        fine=histories[f'{key}_monotonic_step_half']
        coarse=histories[f'{key}_monotonic_steel02_16']
        fine_at_coarse=[r for r in fine if r['requested_point'] and r['target_index']%2==0]
        fine_at_coarse=[dict(r,target_index=r['target_index']//2) for r in fine_at_coarse]
        comparisons[f'{key}_step_refinement']=compare(coarse,fine_at_coarse,m.area*m.yield_strength,
                                                    requested_steps=cases[f'{key}_monotonic_steel02_16']['requested_steps'])
    summary=dict(schema='otw2.steel02_tmq_comparison.v1',engine_version=ops.version(),
        source_selection=selection,specimens={k:asdict(v) for k,v in specimens.items()},
        solver=SOLVER,steel02=STEEL02,cases=cases,comparisons=comparisons,
        total_cases=len(cases),complete_cases=sum(c['complete'] for c in cases.values()),
        physical_validation=False,tmq_coefficients_refitted=False,production_tower_modified=False)
    save_json(output/'summary.json',summary)
    from .publication import publish
    publish(output,summary,histories)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();run(args.output)


if __name__=='__main__': main()
