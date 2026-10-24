"""Create auditable local reference tables from a complete instrumented run."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from util.processing.member_state_recorder import iter_member_states


def summarize(history: Path, output: Path) -> dict:
    manifest=json.loads(history.with_name('run_manifest.json').read_text())
    if manifest.get('status')!='completed':
        raise ValueError('A completed run is required for a final local reference report')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite local report: {output}')
    metadata_path=history.with_suffix('.metadata.json')
    metadata=json.loads(metadata_path.read_text())
    coordinates=metadata['node_coordinates']
    material_parameters=metadata['material_parameters']
    traces,events,seen={},[],set()
    for state in iter_member_states(history):
        for member in state['members']:
            tag=member['original_member_id']
            entries=metadata['members'][str(tag)]
            steel=material_parameters[str(entries[0]['mat_tag'])]
            ni,nj=str(member['node_i']),str(member['node_j'])
            a=[coordinates[ni][i]+state['node_displacements'][ni][i] for i in range(3)]
            b=[coordinates[nj][i]+state['node_displacements'][nj][i] for i in range(3)]
            axis=[(coordinates[nj][i]-coordinates[ni][i])/member['initial_chord_m'] for i in range(3)]
            end_i=member['segments'][0]['global_force'][:6]
            end_j=member['segments'][-1]['global_force'][6:]
            force=sum(end_j[i]*axis[i] for i in range(3))
            bow=0.0
            vector=[b[i]-a[i] for i in range(3)]
            for entry in entries[:-1]:
                n=str(entry['node_j'])
                point=[coordinates[n][i]+state['node_displacements'][n][i] for i in range(3)]
                ratio=sum((point[i]-a[i])*vector[i] for i in range(3))/sum(x*x for x in vector)
                bow=max(bow,math.sqrt(sum((point[i]-a[i]-ratio*vector[i])**2 for i in range(3))))
            sections=[s for segment in member['segments'] for s in segment['sections']]
            if any(s.get('fiber_status')!='available' for s in sections):
                raise ValueError(f'Incomplete fiber reference for {tag} at {state["accepted_step"]}')
            stress=max(sections,key=lambda s:abs(s['max_abs_stress']['stress']))['max_abs_stress']
            strain=max(sections,key=lambda s:abs(s['max_abs_strain']['strain']))['max_abs_strain']
            row={'member_id':tag,'accepted_step':state['accepted_step'],'source_step':state['source_step'],
                'stage_id':state['stage_id'],'stage_progress':state['stage_progress'],
                'original_axis_N':force,'compression_shortening_m':member['initial_chord_m']-member['current_chord_m'],
                'chord_strain':member['chord_strain'],'maximum_bow_m':bow,
                'maximum_abs_fiber_stress_Pa':abs(stress['stress']),
                'maximum_abs_fiber_strain':abs(strain['strain']),
                'nominal_stress_utilization':abs(stress['stress'])/steel['fy'],
                'nominal_strain_utilization':abs(strain['strain'])/(steel['fy']/steel['e0']),
                'end_i_moment_norm_Nm':math.sqrt(sum(v*v for v in end_i[3:])),
                'end_j_moment_norm_Nm':math.sqrt(sum(v*v for v in end_j[3:]))}
            traces.setdefault(tag,[]).append(row)
            for kind,value in [('fiber_stress_reaches_nominal_fy',row['nominal_stress_utilization']),
                               ('fiber_strain_reaches_nominal_fy_over_E',row['nominal_strain_utilization'])]:
                if value>=1 and (tag,kind) not in seen:
                    seen.add((tag,kind))
                    events.append({'member_id':tag,'kind':kind,'accepted_step':state['accepted_step'],
                                   'source_step':state['source_step'],'stage_id':state['stage_id'],'value':value,
                                   'interpretation':'nominal_threshold_marker_not_a_unique_Steel02_plastic_yield_state'})
    output.mkdir(parents=True,exist_ok=False)
    summaries=[]
    for tag,rows in traces.items():
        with (output/f'member_{tag}_reference.csv').open('x',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        endpoints={}
        for row in rows: endpoints[row['stage_id']]=row
        summaries.append({'member_id':tag,'points':len(rows),
            'maximum_compression_N':max(max(0,-r['original_axis_N']) for r in rows),
            'maximum_abs_fiber_stress_Pa':max(r['maximum_abs_fiber_stress_Pa'] for r in rows),
            'maximum_abs_fiber_strain':max(r['maximum_abs_fiber_strain'] for r in rows),
            'maximum_nominal_stress_utilization':max(r['nominal_stress_utilization'] for r in rows),
            'maximum_nominal_strain_utilization':max(r['nominal_strain_utilization'] for r in rows),
            'maximum_bow_m':max(r['maximum_bow_m'] for r in rows),
            'final_N':rows[-1]['original_axis_N'],'endpoints':endpoints})
    flattened=[{k:v for k,v in s.items() if k!='endpoints'} for s in summaries]
    with (output/'local_response_truth_table.csv').open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(flattened[0]));writer.writeheader();writer.writerows(flattened)
    with (output/'reference_events.csv').open('x',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['member_id','kind','accepted_step','source_step','stage_id','value','interpretation'])
        writer.writeheader();writer.writerows(events)
    payload={'schema':'otw2.local_reference_truth.v1','members':summaries,'events':events,
        'source_history':str(history),'source_sha256':hashlib.sha256(history.read_bytes()).hexdigest(),
        'source_run_id':manifest['run_id'],'reference_mesh_converged':False,
        'limits':'Nominal thresholds and bow histories are diagnostic observables; no automatic collapse/buckling certification.'}
    (output/'reference_summary.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    fig,axes=plt.subplots(len(traces),2,figsize=(12,3*len(traces)),squeeze=False,constrained_layout=True)
    for ax,(tag,rows) in zip(axes,traces.items()):
        ax[0].plot([r['compression_shortening_m']*1000 for r in rows],[-r['original_axis_N']/1000 for r in rows])
        ax[0].set(xlabel='Original-chord shortening (mm)',ylabel='Compression force (kN)',title=f'Member {tag}: full spatial boundary')
        ax[1].plot([r['nominal_stress_utilization'] for r in rows],label='max |fiber stress| / fy')
        ax[1].plot([r['nominal_strain_utilization'] for r in rows],label='max |fiber strain| / (fy/E)')
        ax[1].axhline(1,color='crimson',linestyle='--');ax[1].set(xlabel='Committed sample (not seconds)',ylabel='Nominal utilization')
        ax[1].legend()
        for a in ax: a.grid(alpha=.2)
    fig.savefig(output/'local_reference_response.png',dpi=160);plt.close(fig)
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=summarize(args.history,args.output)
    print(json.dumps({'members':len(result['members']),'events':len(result['events'])}))


if __name__=='__main__': main()
