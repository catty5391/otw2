"""Compact driver for the existing spatial member builder.

This reuses MechanicalCatalog and build_member_reference.  The prescribed
pin-ended axial protocol is an explicit experiment, not tower boundary replay.
OpenSees owns process-global state: run cases sequentially or in processes.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import openseespy.opensees as ops

from model.mechanical_profile import MechanicalCatalog, MechanicalProfile, fiber_moments, local_axes
from model.tower_model import OpenSeesModel
from ..member_reference_3d import build_member_reference

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'Source/Z30103A6.s2k'
DEFAULT_MEMBERS = (349, 920, 292)
SOLVER = dict(test='NormUnbalance', tolerance=1e-5, iterations=60,
              fallback_iterations=120, max_bisections=8, algorithm='Newton',
              fallback='NewtonLineSearch')


def save_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def write_csv(path: str | Path, rows: list[dict]) -> None:
    if not rows:
        return
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_members(member_ids=None, *, long_edge_segments=8, short_edge_segments=1,
                 parser_output=None) -> dict[int, dict]:
    profile = MechanicalProfile(name='aligned_v1', long_edge_segments=long_edge_segments,
                                short_edge_segments=short_edge_segments)
    def read(path):
        catalog = MechanicalCatalog(SOURCE, output_dir=path, profile=profile)
        return {i: catalog.member(i) for i in (DEFAULT_MEMBERS if member_ids is None else member_ids)}
    if parser_output is not None:
        return read(parser_output)
    with tempfile.TemporaryDirectory(prefix='otw2_spatial_member_') as folder:
        return read(folder)


def selection_provenance() -> dict:
    """Select high compression demand representatives from completed wind runs.

    |N|/Afy is a demand indicator, not a buckling interaction equation. The
    Q345 median rod is intentionally retained for comparison with the old study.
    """
    with tempfile.TemporaryDirectory(prefix='otw2_member_selection_') as folder:
        catalog = MechanicalCatalog(SOURCE, output_dir=folder)
        members = {i: catalog.member(i) for i in catalog.connectivity}
    base = ROOT/'initial_imperfection_material/tian_ma_qu/followup_results/single_tower_wind_comparison_20261028/runs'
    scores = {}
    evidence = []
    for folder in sorted(base.glob('steel02*')):
        summary_path, forces = folder/'summary.json', folder/'member_forces.csv.gz'
        if not summary_path.is_file() or not forces.is_file():
            continue
        summary = json.loads(summary_path.read_text())
        if summary.get('status') != 'complete':
            continue
        evidence.append(dict(file=str(forces.relative_to(ROOT)), sha256=hashlib.sha256(forces.read_bytes()).hexdigest(),
                             angle_deg=summary['angle_deg']))
        with gzip.open(forces, 'rt', encoding='utf-8') as stream:
            for row in csv.DictReader(stream):
                tag, force, score = int(row['physical_member_tag']), float(row['N_mean_N']), float(row['abs_N_over_Afy'])
                if force < 0 and score > scores.get(tag, {}).get('compression_abs_N_over_Afy', -1.):
                    scores[tag] = dict(compression_abs_N_over_Afy=score, force_N=force,
                        angle_deg=summary['angle_deg'], wind_speed_m_s=float(row['wind_speed_m_s']),
                        file=str(forces.relative_to(ROOT)))
    selected = [dict(member_id=349, reason='Retain actual median-length L125x8Q345 rod from prior controlled study')]
    for grade in ('Q235', 'Q420'):
        options = [tag for tag in scores if members[tag]['section']['material_name'] == grade]
        if not options:
            raise ValueError(f'No completed wind result for grade {grade}')
        tag = max(options, key=lambda i: (scores[i]['compression_abs_N_over_Afy'], -i))
        selected.append(dict(member_id=tag, reason=f'Largest compression |N|/Afy for {grade} among completed selected wind runs', **scores[tag]))
    if [row['member_id'] for row in selected] != list(DEFAULT_MEMBERS):
        raise ValueError('Evidence changed; review member selection instead of silently reusing the frozen study')
    return dict(selected=selected, evidence=evidence, source=str(SOURCE.relative_to(ROOT)),
                source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                limitation='Demand ranking in completed cases only; not the first buckling member or measured capacity')


def weak_direction_global(member: dict) -> np.ndarray:
    """Weak flexural *displacement* direction; not the moment-axis vector."""
    cells = member['fibers']
    cov = sum(float(c['area'])*np.outer([c['y'], c['z']], [c['y'], c['z']]) for c in cells)
    _, directions = np.linalg.eigh(cov)
    direction = directions[:, 0]
    if direction[np.argmax(np.abs(direction))] < 0:
        direction = -direction
    return local_axes(member['coordinates'])[1:].T @ direction


def protocol(member: dict, loading='monotonic', *, steps=400, targets_strain=None) -> tuple[list[dict], list[float]]:
    if isinstance(steps, bool) or int(steps) != steps or steps < 1:
        raise ValueError('steps must be a positive integer')
    ey = member['steel_tower']['fy']/member['steel_tower']['E0']
    if targets_strain is None:
        if loading == 'monotonic':
            targets, maximum_step = [0., -.015], .015/steps
        elif loading == 'elastic':
            # Kept small enough for slender Q235 rod; stress diagnostic verifies.
            targets, maximum_step = [0., -.00001, 0.], .00001/max(10, steps//10)
        elif loading == 'cyclic':
            targets = [0., -.00001, 0.]
            for multiple in (.5, 1., 2., 4.):
                a = ey*multiple
                targets += [-a, a, -a, a]
            targets += [0.]
            maximum_step = ey/max(8., steps/25.)
        else:
            raise ValueError(f'Unknown loading {loading}')
    else:
        targets = [float(v) for v in targets_strain]
        maximum_step = max(abs(b-a) for a,b in zip(targets, targets[1:]))/steps
    if len(targets) < 2 or targets[0] != 0 or not all(math.isfinite(x) for x in targets):
        raise ValueError('Protocol must contain finite strains and start at zero')
    if maximum_step <= 0:
        raise ValueError('Protocol must include a nonzero loading interval')
    points = [dict(target_index=0, leg=0, strain=0., protocol_target=True)]
    for leg, (left,right) in enumerate(zip(targets,targets[1:]), 1):
        count = max(1, math.ceil(abs(right-left)/maximum_step-1e-12))
        for j in range(1,count+1):
            points.append(dict(target_index=len(points),leg=leg,strain=left+(right-left)*j/count,protocol_target=j==count))
    return points, targets


def _build(member, divisions, ratio, direction):
    if isinstance(divisions, bool) or int(divisions) != divisions or divisions < 2:
        raise ValueError('divisions must be integer >=2')
    if not math.isfinite(ratio) or ratio < 0:
        raise ValueError('Imperfection ratio must be finite and nonnegative')
    axes = local_axes(member['coordinates'])
    direction = weak_direction_global(member) if direction is None else np.asarray(direction,dtype=float)
    if direction.shape != (3,) or not np.isfinite(direction).all() or np.linalg.norm(direction) <= 0:
        raise ValueError('A finite nonzero 3D imperfection direction is required')
    direction = direction/np.linalg.norm(direction)
    if abs(float(direction@axes[0])) > 1e-10:
        raise ValueError('Imperfection direction must be perpendicular to the original chord')
    # Same global geometry and per-segment axes as run_axial_boundary_case;
    # compute geometry first so that only one OpenSees model needs building.
    original = np.asarray(member['coordinates'])
    station = np.linspace(0.,1.,divisions+1)
    shape = np.sin(np.pi*station); shape[0]=shape[-1]=0.
    coordinates = ((1-station[:,None])*original[0] + station[:,None]*original[1]
                   + ratio*member['length']*shape[:,None]*direction)
    local_coordinates = (coordinates-coordinates[0])@axes.T
    orientations=[]
    for left,right in zip(coordinates,coordinates[1:]):
        nodes=[dict(zip(('x','y','z'),p)) for p in (left,right)]
        orientations.append((axes@OpenSeesModel._geom_transf_vector(*nodes)).tolist())
    local_member=dict(member, coordinates=[local_coordinates[0].tolist(),local_coordinates[-1].tolist()])
    model=build_member_reference(local_member,divisions=divisions,exact_coordinates=local_coordinates,
                                 orientation_vectors=orientations)
    ni,nj=1,divisions+1
    ops.fix(ni,1,1,1,1,0,0); ops.fix(nj,0,1,1,0,0,0)
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1);ops.load(nj,1.,0.,0.,0.,0.,0.)
    ops.constraints('Plain');ops.numberer('RCM');ops.system('BandGeneral')
    ops.test(SOLVER['test'],SOLVER['tolerance'],SOLVER['iterations'],0)
    ops.algorithm('Newton');ops.integrator('DisplacementControl',nj,1,-1e-7);ops.analysis('Static')
    return model, axes, direction, local_coordinates


def run_case(member: dict, *, output=None, divisions=16, imperfection_ratio=.001,
             unit_direction_global=None, loading='monotonic', steps=400,
             targets_strain=None, max_runtime_seconds=120.) -> dict:
    """Return summary/history/attempts; keep all accepted substeps in order.

    Extrema are sampled at outer fiber centroids in every section, with whole
    section fiberData verification at initial/final/protocol reversal states.
    The query set contains the convex-hull corners of all three rect patches.
    """
    folder=None if output is None else Path(output)
    if folder is not None:
        if (folder/'summary.json').exists():
            raise FileExistsError(f'Refusing to overwrite {folder}')
        folder.mkdir(parents=True,exist_ok=True)
    if not math.isfinite(max_runtime_seconds) or max_runtime_seconds < 0:
        raise ValueError('Runtime budget must be finite and nonnegative')
    points,targets=protocol(member,loading,steps=steps,targets_strain=targets_strain)
    start=time.perf_counter()
    model,axes,direction,coordinates=_build(member,divisions,imperfection_ratio,unit_direction_global)
    rows=[];attempts=[];completed=0;failure=None
    node=divisions+1; count=model['integration_points']; cells=member['fibers']
    # Every patch corner is extreme for a linear section strain plane. Steel02
    # stress extrema need not occur there under arbitrary cycles; therefore the
    # quantity is labelled probed, while all-fiber checks use native fiberData.
    probe_indices=set()
    for a,b in [(1.,0.),(-1.,0.),(0.,1.),(0.,-1.),(1.,1.),(-1.,-1.),(1.,-1.),(-1.,1.)]:
        probe_indices.add(max(range(len(cells)),key=lambda i:a*cells[i]['y']+b*cells[i]['z']))
    probes=[cells[i] for i in sorted(probe_indices)]
    all_fiber_max=0.
    def capture(point,requested,depth):
        nonlocal all_fiber_max
        displacement=float(ops.nodeDisp(node,1));force=float(ops.getLoadFactor(1));ops.reactions()
        reaction=float(ops.nodeReaction(1,1));maxstress=0.;maxstrain=0.
        audit_all=loading=='elastic' or (requested and point['protocol_target'])
        for tag in model['elements']:
            for section in range(1,count+1):
                if audit_all:
                    data=np.asarray(ops.eleResponse(tag,'section',section,'fiberData'),dtype=float)
                    if data.size!=5*len(cells):
                        raise RuntimeError('fiberData recorder has unexpected shape')
                    data=data.reshape((-1,5))
                    maxstress=max(maxstress,float(np.max(np.abs(data[:,3]))))
                    maxstrain=max(maxstrain,float(np.max(np.abs(data[:,4]))))
                else:
                    # Section strain extrema are exact for linear strain fields
                    # but stress extrema are expressly limited to probe fibers.
                    for cell in probes:
                        response=ops.eleResponse(tag,'section',section,'fiber',cell['y'],cell['z'],'stressStrain')
                        if len(response)!=2:raise RuntimeError('Missing fiber response')
                        maxstress=max(maxstress,abs(response[0]));maxstrain=max(maxstrain,abs(response[1]))
        if audit_all:all_fiber_max=max(all_fiber_max,maxstress)
        mid=divisions//2+1
        lateral=np.asarray(ops.nodeDisp(mid)[1:3])
        row=dict(sequence=len(rows),target_index=point['target_index'],leg=point['leg'],requested_point=requested,
            protocol_target=bool(requested and point['protocol_target']),strain=displacement/member['length'],
            displacement_m=displacement,force_N=force,reaction_N=reaction,reaction_balance_N=abs(force+reaction),
            midspan_y_increment_m=float(lateral[0]),midspan_z_increment_m=float(lateral[1]),
            midspan_y_total_m=float(lateral[0]+coordinates[mid-1,1]),midspan_z_total_m=float(lateral[1]+coordinates[mid-1,2]),
            max_abs_fiber_stress_Pa=maxstress,max_abs_fiber_strain=maxstrain,fiber_observation='all' if audit_all else 'extreme_centroid_probes',
            subdivision_depth=depth,iterations=0 if not rows else int(ops.testIter()))
        row['external_work_J']=0. if not rows else rows[-1]['external_work_J']+.5*(rows[-1]['force_N']+force)*(displacement-rows[-1]['displacement_m'])
        rows.append(row)
    def advance(point,target,depth):
        nonlocal failure
        if time.perf_counter()-start>max_runtime_seconds:
            failure=dict(kind='runtime_budget',target_index=point['target_index'],depth=depth);return False
        code=-999
        for algorithm in ('Newton','NewtonLineSearch'):
            u_before=float(ops.nodeDisp(node,1));time_before=float(ops.getTime())
            increment=target-u_before
            ops.test(SOLVER['test'],SOLVER['tolerance'],SOLVER['iterations'] if algorithm=='Newton' else SOLVER['fallback_iterations'],0)
            ops.algorithm(algorithm);ops.integrator('DisplacementControl',node,1,increment)
            code=int(ops.analyze(1));iterations=int(ops.testIter());norms=ops.testNorm()
            norm=float(norms[min(max(iterations-1,0),len(norms)-1)]) if len(norms) else None
            reverted=code==0 or (math.isclose(float(ops.nodeDisp(node,1)),u_before,rel_tol=0,abs_tol=1e-10)
                                  and math.isclose(float(ops.getTime()),time_before,rel_tol=1e-10,abs_tol=1e-8))
            attempts.append(dict(target_index=point['target_index'],depth=depth,algorithm=algorithm,
                increment_m=increment,code=code,iterations=iterations,residual_norm=norm if norm is not None and math.isfinite(norm) else None,
                failed_endpoint_time_reverted=reverted))
            if code==0:
                capture(point,abs(target-point['strain']*member['length'])<1e-12,depth);return True
            if not reverted:
                failure=dict(kind='failed_state_reversion_check',target_index=point['target_index'],depth=depth,return_code=code);return False
        if depth>=SOLVER['max_bisections']:
            failure=dict(kind='nonconvergence',target_index=point['target_index'],depth=depth,return_code=code);return False
        halfway=.5*(float(ops.nodeDisp(node,1))+target)
        return advance(point,halfway,depth+1) and advance(point,target,depth+1)
    try:
        capture(points[0],True,0)
        for point in points[1:]:
            if not advance(point,point['strain']*member['length'],0):break
            completed=point['target_index']
        peak=min(rows,key=lambda r:r['force_N'])
        info=dict(schema='otw2.spatial_segmented_member_case.v1',member_id=member['member_id'],section_name=member['section']['section_name'],
            length_m=member['length'],steel_parameters=member['steel_tower'],profile=member['profile'],divisions=divisions,
            fiber_count=len(cells),fiber_moments=fiber_moments(cells),loading=loading,targets_strain=targets,
            imperfection_ratio=imperfection_ratio,unit_direction_global=direction.tolist(),unit_direction_local_yz=(axes@direction)[1:].tolist(),
            global_to_local_axes=axes.tolist(),coordinates_local=coordinates.tolist(),
            boundary='3D pin ends; translations transverse restrained at both ends; rx_i fixed to remove rigid twist; remaining endpoint rotations free',
            orientation='Production per-segment global reference axes transformed together with geometry; source installation angles not independently verified',
            solver=SOLVER,requested_steps=len(points)-1,completed_steps=completed,accepted_substeps=len(rows)-1,
            complete=completed==len(points)-1,failure=failure,runtime_seconds=time.perf_counter()-start,
            attempts=len(attempts),failed_attempts=sum(a['code']!=0 for a in attempts),
            peak_compression_kN=-peak['force_N']/1000,peak_shortening_mm=-peak['displacement_m']*1000,
            peak_sequence=peak['sequence'],peak_target_index=peak['target_index'],
            peak_is_final_state=peak['sequence']==len(rows)-1,
            observed_monotonic_postpeak_drop_ratio=(rows[-1]['force_N']-peak['force_N'])/abs(peak['force_N'])
                if loading=='monotonic' and peak['force_N']<0 else None,
            observed_descending_branch=bool(loading=='monotonic' and peak['force_N']<0
                and len(rows)-1-peak['sequence']>=3 and rows[-1]['force_N']-peak['force_N']>.01*abs(peak['force_N'])),
            peak_semantics='Maximum sampled compression on the completed prefix; not automatically a buckling capacity',
            final_force_kN=rows[-1]['force_N']/1000,
            final_strain=rows[-1]['strain'],max_reaction_balance_N=max(r['reaction_balance_N'] for r in rows),
            max_observed_fiber_stress_over_fy=max(r['max_abs_fiber_stress_Pa'] for r in rows)/member['steel_tower']['fy'],
            max_all_fiber_stress_at_reversals_over_fy=all_fiber_max/member['steel_tower']['fy'],
            elastic_all_fibers_every_step=loading=='elastic',
            max_abs_fiber_strain=max(r['max_abs_fiber_strain'] for r in rows),external_work_J=rows[-1]['external_work_J'],
            work_note='Signed external integral N du, not automatically dissipated energy',
            physical_validation=False,full_tower_boundary_replay=False)
        if folder is not None:
            write_csv(folder/'history.csv',rows);write_csv(folder/'attempts.csv',attempts);save_json(folder/'summary.json',info)
        return dict(summary=info,history=rows,attempts=attempts)
    finally:
        ops.wipe()


def compare_histories(reference, candidate, *, normalization, requested_steps):
    """Matched ordered requested indices only; expose incomplete common range."""
    left={int(r['target_index']):r for r in reference if r['requested_point']}
    right={int(r['target_index']):r for r in candidate if r['requested_point']}
    indices=sorted(left.keys()&right.keys())
    if not indices:raise ValueError('No common requested points')
    if normalization<=0:raise ValueError('Normalization must be positive')
    for i in indices:
        if not math.isclose(left[i]['strain'],right[i]['strain'],rel_tol=1e-9,abs_tol=1e-11):
            raise ValueError('History protocol differs at a shared requested index')
    diff=np.asarray([right[i]['force_N']-left[i]['force_N'] for i in indices])
    ref_force=np.asarray([left[i]['force_N'] for i in indices]);cand_force=np.asarray([right[i]['force_N'] for i in indices])
    full=indices==list(range(requested_steps+1))
    return dict(common_points=len(indices),coverage=(len(indices)-1)/requested_steps,full_common_history=full,
        first_common_index=indices[0],last_common_index=indices[-1],nrmse_Afy=float(np.sqrt(np.mean(diff**2))/normalization),
        max_abs_force_difference_kN=float(np.max(np.abs(diff)))/1000,
        common_peak_difference_percent=float((np.min(cand_force)/np.min(ref_force)-1)*100) if np.min(ref_force)<0 else None,
        comparison_scope='full prescribed history' if full else 'common accepted requested points only')
