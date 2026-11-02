"""Independent global force and deformed-coordinate moment checks from saved CSVs."""
from __future__ import annotations
from collections import defaultdict
import csv
import json
from pathlib import Path
from .experiment import OUTPUT, write_json
from .publication import load_history


def rows(path):
    with path.open(encoding='utf-8') as f:yield from csv.DictReader(f)


def global_balance(folder):
    coordinates={int(r['node_tag']):[float(r[d]) for d in ('x','y','z')] for r in rows(folder/'model_data/nodes.csv')}
    masses={int(r['node_tag']):float(r['mz']) for r in rows(folder/'model_data/masses.csv')}
    wind={int(r['node_tag']):[float(r[d]) for d in ('Fx_N','Fy_N','Fz_N','Mx_Nm','My_Nm','Mz_Nm')] for r in rows(folder/'wind_nodal_loads.csv')}
    reactions=defaultdict(dict)
    for r in rows(folder/'support_reactions.csv'):
        reactions[int(r['step'])][int(r['node_tag'])]=[float(r[d]) for d in ('Rx_N','Ry_N','Rz_N','Mx_Nm','My_Nm','Mz_Nm')]
    history={int(r['step']):r for r in load_history(folder/'history.csv')}
    positions=defaultdict(dict)
    for r in rows(folder/'node_states.csv'):
        if r['stage']!='pushover':continue
        tag=int(r['node_tag']);positions[int(r['step'])][tag]=[coordinates[tag][i]+float(r[d]) for i,d in enumerate(('ux','uy','uz'))]
    checks=[]
    for step,h in history.items():
        if not h['equilibrium_passed']:continue
        resultant=[0.]*6;scale=0.;factor=h['wind_load_factor']
        for tag,pos in positions[step].items():
            load=[factor*v for v in wind.get(tag,[0.]*6)];load[2]-=9.81*masses.get(tag,0.)
            scale+=sum(abs(v) for v in load[:3])
            v=[a+b for a,b in zip(load,reactions[step].get(tag,[0.]*6))]
            x,y,z=pos;fx,fy,fz=v[:3]
            v[3]+=y*fz-z*fy;v[4]+=z*fx-x*fz;v[5]+=x*fy-y*fx
            resultant=[a+b for a,b in zip(resultant,v)]
        ftol=.001+1e-6*max(1.,scale);mtol=.001+1e-6*max(1.,scale)*36.4
        checks.append({'step':step,'resultant_N_Nm':resultant,'force_tolerance_N':ftol,'moment_tolerance_Nm':mtol,
            'passed':max(map(abs,resultant[:3]))<=ftol and max(map(abs,resultant[3:]))<=mtol})
    return dict(checked_points=len(checks),all_passed=bool(checks) and all(r['passed'] for r in checks),
        maximum_force_residual_N=max((max(map(abs,r['resultant_N_Nm'][:3])) for r in checks),default=None),
        maximum_moment_residual_Nm=max((max(map(abs,r['resultant_N_Nm'][3:])) for r in checks),default=None),
        method='External loads plus support reactions; moments use original coordinates + saved total translations. Gravity=-9.81*mz, wind=lambda*saved nodal pattern. No FE rerun.',points=checks)


def verify(root=OUTPUT):
    root=Path(root);summary=json.loads((root/'summary.json').read_text());cases={}
    for r in summary['cases']:
        cases[r['case']]=global_balance(root/'runs'/r['case'])
    v=dict(schema='otw2.tower_pushover_saved_verification.v1',cases=cases,
        all_global_equilibria_passed=all(c['all_passed'] for c in cases.values()),
        checked_points=sum(c['checked_points'] for c in cases.values()),
        common_inputs_passed=all(v['all_three_present'] and all(v['equal_inputs'].values()) for v in summary['common_input_checks'].values()),
        physical_validation=False,damage_state_thresholds_established=False)
    write_json(root/'verification.json',v)
    print(json.dumps({k:v[k] for k in ('all_global_equilibria_passed','checked_points','common_inputs_passed')}))
    return v

if __name__=='__main__':verify()
