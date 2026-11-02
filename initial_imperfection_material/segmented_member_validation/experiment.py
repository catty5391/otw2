"""Length, section and protocol checks on three actual tower members.

Reproduce with python -m initial_imperfection_material.segmented_member_validation.experiment.
An existing output directory is refused to preserve the original evidence.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np

from .mechanics import (DEFAULT_MEMBERS, ROOT, SOLVER, compare_histories, read_members,
                        run_case, save_json, selection_provenance, write_csv)

OUTPUT=Path(__file__).resolve().parent/'results/convergence'


def case_key(member_id, divisions, long, short, loading, steps=400):
    return f'm{member_id}_d{divisions}_f{long}x{short}_{loading}'+(f'_steps{steps}' if steps!=400 else '')


def study_plan():
    cases=[]
    for tag in DEFAULT_MEMBERS:
        for divisions in (4,8,16,32):
            cases.append(dict(member_id=tag,divisions=divisions,long=8,short=1,loading='monotonic',steps=400,group='length_mesh'))
        for long,short in ((16,2),(32,4)):
            cases.append(dict(member_id=tag,divisions=16,long=long,short=short,loading='monotonic',steps=400,group='fiber_mesh'))
        cases.append(dict(member_id=tag,divisions=16,long=8,short=1,loading='monotonic',steps=800,group='step_size'))
        for long,short in ((8,1),(32,4)):
            cases.append(dict(member_id=tag,divisions=16,long=long,short=short,loading='elastic',steps=400,group='elastic_recovery'))
        for divisions,long,short in ((4,8,1),(16,8,1),(16,32,4)):
            cases.append(dict(member_id=tag,divisions=divisions,long=long,short=short,loading='cyclic',steps=400,group='cyclic'))
    for case in cases:
        case['key']=case_key(case['member_id'],case['divisions'],case['long'],case['short'],case['loading'],case['steps'])
    return cases


def run(output=OUTPUT):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Refusing to overwrite study output {output}')
    output.mkdir(parents=True,exist_ok=True)
    provenance=selection_provenance()
    catalogs={(long,short):read_members(long_edge_segments=long,short_edge_segments=short)
              for long,short in ((8,1),(16,2),(32,4))}
    plan=study_plan()
    source_files=[Path(__file__),Path(__file__).with_name('mechanics.py'),
                  ROOT/'model/mechanical_profile.py',ROOT/'model/steel02_parameters.py',
                  ROOT/'model/tower_model.py',ROOT/'initial_imperfection_material/member_reference_3d.py']
    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    save_json(output/'plan.json',dict(cases=plan,selection=provenance,solver=SOLVER,code_sha256=source_hashes))
    summaries={};histories={}
    for index,case in enumerate(plan,1):
        print(f"[{index}/{len(plan)}] {case['key']}",flush=True)
        member=catalogs[(case['long'],case['short'])][case['member_id']]
        result=run_case(member,output=output/'runs'/case['key'],divisions=case['divisions'],
                        loading=case['loading'],steps=case['steps'])
        info=result['summary'];info.update(key=case['key'],group=case['group'],path=f"runs/{case['key']}",
                                          fiber_mesh=[case['long'],case['short']])
        save_json(output/'runs'/case['key']/'summary.json',info)
        summaries[case['key']]=info;histories[case['key']]=result['history']
        print(f"  complete={info['complete']} peak={info['peak_compression_kN']:.6f} kN; "
              f"steps={info['completed_steps']}/{info['requested_steps']} failures={info['failed_attempts']}",flush=True)
    comparisons={};mesh_rows=[];fiber_rows=[];elastic_rows=[]
    for tag in DEFAULT_MEMBERS:
        def key(d=16,l=8,s=1,loading='monotonic',steps=400):return case_key(tag,d,l,s,loading,steps)
        reference_key=key(32);ref=summaries[reference_key]
        member=catalogs[(8,1)][tag];normalization=member['section']['area']*member['steel_tower']['fy']
        for d in (4,8,16):
            candidate_key=key(d)
            comparisons[f'{candidate_key}_vs_{reference_key}']=compare_histories(histories[reference_key],histories[candidate_key],
                normalization=normalization,requested_steps=ref['requested_steps'])
        for d in (4,8,16,32):
            candidate=summaries[key(d)]
            mesh_rows.append(dict(member_id=tag,section_name=member['section']['section_name'],length_m=member['length'],
                divisions=d,peak_compression_kN=candidate['peak_compression_kN'],
                peak_difference_to_32_percent=100*(candidate['peak_compression_kN']/ref['peak_compression_kN']-1)
                    if ref['complete'] and candidate['complete'] else None,complete=candidate['complete']))
        fine_key=key(l=32,s=4);fine=summaries[fine_key]
        for l,s in ((8,1),(16,2),(32,4)):
            candidate_key=key(l=l,s=s);candidate=summaries[candidate_key]
            comparisons[f'{candidate_key}_vs_{fine_key}']=compare_histories(histories[fine_key],histories[candidate_key],
                normalization=normalization,requested_steps=fine['requested_steps'])
            exact_weak=float(np.linalg.eigvalsh([[member['section']['i22'],member['section']['i23']],
                                               [member['section']['i23'],member['section']['i33']]])[0])
            fiber_rows.append(dict(member_id=tag,long_edge_segments=l,short_edge_segments=s,fiber_count=candidate['fiber_count'],
                weak_inertia_m4=candidate['fiber_moments']['weak_principal'],
                weak_inertia_difference_percent=100*(candidate['fiber_moments']['weak_principal']/exact_weak-1),
                peak_compression_kN=candidate['peak_compression_kN'],peak_difference_to_fine_percent=
                100*(candidate['peak_compression_kN']/fine['peak_compression_kN']-1) if fine['complete'] and candidate['complete'] else None,
                complete=candidate['complete']))
        # Fine step shares the same monotonic protocol at every second point.
        fine_steps=[dict(row,target_index=row['target_index']//2) for row in histories[key(steps=800)]
                    if row['requested_point'] and row['target_index']%2==0]
        comparisons[f'{key()}_vs_half_step']=compare_histories(fine_steps,histories[key()],normalization=normalization,
            requested_steps=summaries[key()]['requested_steps'])
        for candidate_key,reference_key in [(key(d=4,loading='cyclic'),key(loading='cyclic')),
                                           (key(loading='cyclic'),key(l=32,s=4,loading='cyclic'))]:
            comparisons[f'{candidate_key}_vs_{reference_key}']=compare_histories(histories[reference_key],histories[candidate_key],
                normalization=normalization,requested_steps=summaries[reference_key]['requested_steps'])
        for l,s in ((8,1),(32,4)):
            c=summaries[key(l=l,s=s,loading='elastic')]
            elastic_rows.append(dict(member_id=tag,fiber_count=c['fiber_count'],complete=c['complete'],final_force_N=c['final_force_kN']*1000,
                max_observed_fiber_stress_over_fy=c['max_observed_fiber_stress_over_fy'],
                max_reaction_balance_N=c['max_reaction_balance_N']))
    write_csv(output/'mesh_summary.csv',mesh_rows);write_csv(output/'fiber_summary.csv',fiber_rows);write_csv(output/'elastic_summary.csv',elastic_rows)
    summary=dict(schema='otw2.spatial_segmented_member_validation.v1',selection=provenance,
        members={str(i):catalogs[(8,1)][i] for i in DEFAULT_MEMBERS},cases=summaries,comparisons=comparisons,
        total_cases=len(summaries),complete_cases=sum(c['complete'] for c in summaries.values()),
        physical_validation=False,full_tower_mesh_convergence_established=False,full_tower_boundary_replay=False,
        code_sha256=source_hashes,
        scope='Three actual rods; synthetic 3D pinned axial protocols; production section, materials, elements and per-segment frame convention',
        limitations=['Local plate buckling and warping torsion absent from the standard beam model',
            'Steel coupon parameters not independently measured',
            'Production section orientation convention retained; actual installation orientation unverified',
            'Runtime or nonlinear solver failure is not physical collapse',
            'Numerical comparisons only over common accepted protocol points; no extrapolation'])
    save_json(output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();run(args.output)


if __name__=='__main__':main()
