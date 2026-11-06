"""Rebuild the current scientific figures from saved evidence, without FE solves.

Example: python -m scripts.rebuild_scientific_figures --groups tower --skill-root ...
Outputs and audits are local artifacts; --publish copies approved exports to legacy URLs.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from util.postprocess.scientific_figures import RC

ROOT=Path(__file__).resolve().parents[1]
MATERIAL=ROOT/'initial_imperfection_material'
TMQ=MATERIAL/'tian_ma_qu'
DESTINATIONS={
 'tower':MATERIAL/'tower_material_pushover/results',
 'steel02':MATERIAL/'steel02_tmq_comparison/results',
 'liu':MATERIAL/'liu_angle_phm/results',
 'tmq':TMQ/'results',
 'single_wind':TMQ/'followup_results/single_tower_wind_comparison_20261028',
 'tower_line':TMQ/'followup_results/tower_line_wind_comparison_20261028',
 'rain':ROOT/'rain_loading/results',
}

def read_json(path):return json.loads(Path(path).read_text())

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig') as file:rows=list(csv.DictReader(file))
    for row in rows:
        for k,v in row.items():
            if v in ('True','False'):row[k]=v=='True'
            elif v=='':row[k]=None
            else:
                try:row[k]=float(v)
                except ValueError:pass
    return rows


def draw(group):
    root=DESTINATIONS[group]
    if group=='tower':
        from initial_imperfection_material.tower_material_pushover import publication as p
        with patch.object(p,'write_json'),patch.object(p,'save_csv'):
            cases,_,_=p.collect(root)
        p.figures(root,cases)
    elif group=='steel02':
        from initial_imperfection_material.steel02_tmq_comparison import publication as p
        summary=read_json(root/'summary.json')
        histories={k:read_csv(root/'runs'/k/'history.csv') for k in summary['cases']}
        with patch.object(p,'write_report'),patch.object(p,'write_html'),patch.object(p,'write_csv'):
            p.publish(root,summary,histories)
    elif group=='liu':
        from initial_imperfection_material.liu_angle_phm import publication as p
        names=('curved_history','polygon_history','paper_unloading_history','postbuckling_fit','reloading_fit')
        with patch.object(p,'write_report'),patch.object(p,'publish_html'):
            p.publish(root,read_json(root/'summary.json'),*(read_csv(root/f'{name}.csv') for name in names))
    elif group=='tmq':
        from initial_imperfection_material.tian_ma_qu.cases import literature_cases
        from initial_imperfection_material.tian_ma_qu.visualization import create_figures
        bundles=[dict(case=c,rows=read_csv(root/c.key/'history.csv'),events=read_json(root/c.key/'events.json'),
                      opensees_rows=read_csv(root/c.key/'opensees_history.csv')) for c in literature_cases()]
        create_figures(root,bundles,[])
    elif group=='single_wind':
        from initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison import draw_figures
        s=read_json(root/'summary.json');draw_figures(root,s['cases'],s['common_target_comparison'])
    elif group=='tower_line':
        from initial_imperfection_material.tian_ma_qu.tower_line_wind_comparison import draw_figures
        draw_figures(root)
    elif group=='rain':
        from rain_loading import study as p
        original=p.tower_geometry
        with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
            for name in ('csv_save','save_json','write_report'):stack.enter_context(patch.object(p,name))
            stack.enter_context(patch.object(p,'tower_geometry',lambda _:original(Path(temp))))
            p.main()


def inputs_snapshot(group):
    """Hash scientific input tables, excluding enormous unrelated state databases."""
    root=DESTINATIONS[group]
    files=[p for p in root.rglob('*') if p.is_file() and p.suffix in ('.csv','.json')
           and p.stat().st_size<10_000_000 and not p.name.endswith(('.qa.json','.alignment.json'))]
    if group=='liu':files+=list((TMQ/'followup_results/carden_conditional_20261026').glob('*predictions.csv'))
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def publish_exports(output,groups):
    """Check the entire selection before replacing any legacy figure URL."""
    from py_view.results_dashboard.figure_gallery import GROUPS
    selected=[]
    for group in groups:
        for name in GROUPS[group][1]:
            base=output/group/name;qa=read_json(str(base)+'.qa.json')
            if not (qa['data_unchanged'] and qa['text']['auditable'] and
                    qa['text']['below_minimum_count']==0 and
                    qa['collisions']['verdict']=='PASS' and
                    qa['alignment'].get('verdict') in ('PASS','NOT APPLICABLE')):
                raise ValueError(f'Export not cleared by rendered QA: {group}/{name}')
            for ext in ('.png','.pdf','.svg'):
                path=base.with_suffix(ext)
                if not path.is_file():raise FileNotFoundError(path)
                selected.append((group,path))
    for group,path in selected:
        target=DESTINATIONS[group]/path.name
        backup=output/'previous'/group/path.name
        if target.exists() and not backup.exists():
            backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
        shutil.copy2(path,target)
    print('Published',len(selected),'exports to existing figure URLs',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--groups',nargs='+',choices=list(DESTINATIONS),default=list(DESTINATIONS))
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/figure_refactor_20261106')
    parser.add_argument('--skill-root',type=Path,required=True)
    parser.add_argument('--publish',action='store_true',help='Copy cleared exports to the existing module image URLs')
    parser.add_argument('--publish-only',action='store_true',help='Check and publish existing exports without drawing again')
    args=parser.parse_args();args.output=args.output.resolve()
    os.environ['OTW2_FIGURE_SKILL']=str(args.skill_root)
    for group in ([] if args.publish_only else args.groups):
        print('Rendering',group,flush=True)
        dest=args.output/group;dest.mkdir(parents=True,exist_ok=True)
        os.environ['OTW2_FIGURE_OUTPUT']=str(dest)
        before=inputs_snapshot(group)
        with plt.rc_context(RC):draw(group)
        after=inputs_snapshot(group)
        assert before==after,f'Scientific input changed in {group}'
        (dest/'inputs.json').write_text(json.dumps(before,indent=2)+'\n')
        print('Finished',group,len(list(dest.glob('*.qa.json'))),'figures; input hashes unchanged',flush=True)
    os.environ.pop('OTW2_FIGURE_OUTPUT',None)
    if args.publish or args.publish_only:publish_exports(args.output,args.groups)

if __name__=='__main__':main()
