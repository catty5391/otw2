"""Export a fully committed protocol prefix while a longer run continues.

The derived run declares only its completed prefix. It never reclassifies the
parent as completed and never restarts a nonlinear domain at an interior state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from util.analysis import RunManifest
from util.analysis.result_quality import ResultQuality


def export_prefix(history: Path, output: Path, targets: int=6):
    if isinstance(targets,bool) or not isinstance(targets,int) or targets<1:
        raise ValueError('targets must be a positive integer')
    if output.exists():
        raise FileExistsError(f'Prefix output already exists: {output}')
    parent_manifest_path=history.with_name('run_manifest.json')
    parent=json.loads(parent_manifest_path.read_text())
    protocol=parent['parameters']['targets']
    if targets>len(protocol):
        raise ValueError('Requested prefix exceeds the declared parent protocol')
    selected=[]
    stages={}
    gravity=[]
    with history.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.endswith('\n'):
                break  # A concurrently written tail is not a committed row.
            row=json.loads(line)
            if row.get('committed') is not True:
                raise ValueError('Prefix cannot contain trial states')
            stage=row['stage_id']
            match=re.match(r'^target_(\d+)_',stage)
            if match and int(match[1])>targets:
                break
            selected.append(line)
            if stage=='gravity': gravity.append(row['stage_progress'])
            if match:
                stages.setdefault(int(match[1]),[]).append(row['stage_progress'])
                if int(match[1])==targets and abs(row['stage_progress']-1)<=1e-8:
                    break
    if not selected or json.loads(selected[0])['stage_id']!='initial':
        raise ValueError('Initial unloaded state is required')
    if not gravity or abs(gravity[-1]-1)>1e-8:
        raise ValueError('Complete preceding gravity history is required')
    if set(stages)!=set(range(1,targets+1)) or any(
            abs(p[0])>1e-8 or abs(p[-1]-1)>1e-8 or any(a>b+1e-9 for a,b in zip(p,p[1:]))
            for p in stages.values()):
        raise ValueError('Requested prefix is not completely committed yet')
    output.mkdir(parents=True,exist_ok=False)
    destination=output/'member_states.jsonl'
    with destination.open('x',encoding='utf-8') as stream: stream.writelines(selected)
    shutil.copyfile(history.with_suffix('.metadata.json'),destination.with_suffix('.metadata.json'))
    snapshot=output/'source_manifest_at_export.json'
    snapshot.write_text(json.dumps(parent,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    last=json.loads(selected[-1])
    target_stage_ids=list(dict.fromkeys(json.loads(line)['stage_id'] for line in selected
                                       if json.loads(line)['stage_id'].startswith('target_')))
    scope={'requested_target_count':targets,'completed_target_count':targets,
           'source_requested_target_count':len(protocol),'target_stage_ids':target_stage_ids,
           'starts_from_unloaded':True,'includes_complete_gravity':True,
           'last_source_step':last['source_step']}
    derivation={'method':'committed_prefix_from_initial_not_restart','source_run_id':parent['run_id'],
        'source_run_status_at_snapshot':parent['status'],'source_history_path':str(history),
        'source_history_prefix_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
        'source_metadata_sha256':hashlib.sha256(destination.with_suffix('.metadata.json').read_bytes()).hexdigest(),
        'source_manifest_sha256_at_snapshot':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'last_included_accepted_step':last['accepted_step']}
    q=ResultQuality(purpose='independent_validation')
    q.set_coverage(targets,targets,unit='targets')
    run=RunManifest(output,parameters={**parent['parameters'],'targets':protocol[:targets],
        'analysis':'derived_committed_boundary_prefix','parent_run_id':parent['run_id'],
        'parent_status_at_export':parent['status'],'parent_requested_targets':len(protocol),
        'prefix_requested_targets':targets,'scope':'complete initial/gravity/history through selected prefix only',
        'artifact_type':'derived_committed_prefix','prefix_scope':scope,'derivation':derivation,
        'nonlinear_domain_restarted':False},input_files=[destination,destination.with_suffix('.metadata.json'),snapshot],quality=q)
    run.payload.update(artifact_type='derived_committed_prefix',scope=scope,derivation=derivation)
    with run:
        run.update(completed_steps=json.loads(selected[-1])['source_step'],completed_targets=targets,
                   recorded_points=len(selected))
        run.add_artifact('member_states',destination)
        run.add_artifact('parent_manifest_snapshot',snapshot)
        run.finish()
    return {'exported_targets':targets,'parent_status':parent['status'],'rows':len(selected),
            'output':str(output),'parent_is_not_reclassified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--targets',type=int,default=6)
    args=parser.parse_args()
    print(json.dumps(export_prefix(args.history,args.output,args.targets)))


if __name__=='__main__':main()
