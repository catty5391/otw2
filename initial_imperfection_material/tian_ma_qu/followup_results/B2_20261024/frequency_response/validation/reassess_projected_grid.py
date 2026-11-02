import csv,json,hashlib
from pathlib import Path
import numpy as np
from initial_imperfection_material.tian_ma_qu.frequency_response import (BANDS,COUNTS,projected_grid_checks,response_metrics,publish)
from initial_imperfection_material.tian_ma_qu.wind_projection import write_json,write_csv
root=Path('initial_imperfection_material/tian_ma_qu/followup_results/B2_20261024/frequency_response')
arrays=dict(np.load(root/'frequency_responses.npz'));f=arrays['frequencies_Hz'];direct=arrays['direct']
assert len(f)==1465
summary=json.loads((root/'summary.json').read_text());descriptors=json.loads((root/'output_descriptors.json').read_text())
old_admission=json.loads((root/'modal_admission.json').read_text())
grid=[]
for level,stride in [(1,2),(2,1)]:
 checks=projected_grid_checks(f[::stride*2],direct[::stride*2],f[::stride],direct[::stride],descriptors)
 grid.append({'level':level,'coarse_count':len(f[::stride*2]),'fine_count':len(f[::stride]),'all_passed':all(r['passed'] for r in checks),'checks':checks})
lookup={(r['angle_deg'],r['name'],r['direction'],r['band']):r['passed'] for r in grid[-1]['checks']}
metrics=[]
for n in COUNTS:
 vals=np.load(root/'expanded_modes.npz')['values'] if n==300 else np.load('initial_imperfection_material/tian_ma_qu/modal_results/runs/coupled_80_checked/equation_modes.npz')['values'][:n]
 for correction in ['raw','residual_flexibility']:
  for band,(lo,hi) in BANDS.items():
   mask=(f>=lo-1e-12)&(f<=hi+1e-12);coverage=float(np.sqrt(vals[-1])/(2*np.pi))>=hi
   for j,desc in enumerate(descriptors):
    metric=response_metrics(f[mask],direct[mask,j],arrays[f'modes_{n}_{correction}'][mask,j]);gp=lookup[(desc['angle_deg'],desc['name'],desc['direction'],band)]
    metrics.append({**desc,'modes':n,'correction':correction,'band':band,'band_covered_by_modes':coverage,**metric,'frequency_grid_passed':gp,'frequency_passed':coverage and gp and metric['L2_passed'] and metric['peak_passed']})
ml={(m['angle_deg'],m['name'],m['direction'],m['band'],m['modes'],m['correction']):m for m in metrics}
changed=[]
for row in old_admission['outputs']:
 key=tuple(row[k] for k in ['angle_deg','name','direction','band','modes','correction'])
 before=row['candidate_C_output_passed'];row['frequency_passed']=ml[key]['frequency_passed'];row['candidate_C_output_passed']=row['static_passed'] and row['frequency_passed']
 if before!=row['candidate_C_output_passed']:changed.append({'identity':key,'before':before,'after':row['candidate_C_output_passed']})
old_admission['frequency_grid_passed']=grid[-1]['all_passed']
summary['frequency_grid_passed']=grid[-1]['all_passed'];summary['admitted_outputs']=sum(r['candidate_C_output_passed'] for r in old_admission['outputs'])
summary['grid_checked_output_bands']=len(grid[-1]['checks']);summary['grid_failed_output_bands']=sum(not r['passed'] for r in grid[-1]['checks'])
summary['postprocessing_revision']='Projected outputs and both bands independently checked; raw complex responses unchanged'
summary['artifacts']+=['postprocessing_revision.json']
audit={'schema':'otw2.n06_postprocessing_revision.v1','new_FE_runs':0,'new_eigen_solves':0,'new_frequency_matrix_solves':0,'raw_responses_modified':False,'initial_publication_retained':'iterations/cartesian_grid_check_v1',
 'raw_responses_sha256':hashlib.sha256((root/'frequency_responses.npz').read_bytes()).hexdigest(),
 'reasons':['First publication checked Cartesian channels over full band; final check covers every final projected output in both frozen bands','Peak criterion means band maximum amplitude, not independent acceptance of every local resonance peak','Mass audit helper converted sparse input explicitly to CSC for general DIA test inputs; actual stored matrix already CSC, no mathematical change'],
 'assessment_changes':changed,'grid_failed_output_bands':summary['grid_failed_output_bands'],
 'source_sha256':hashlib.sha256(Path('initial_imperfection_material/tian_ma_qu/frequency_response.py').read_bytes()).hexdigest()}
write_json(root/'frequency_grid_checks.json',grid);write_csv(root/'response_metrics.csv',metrics);write_json(root/'modal_admission.json',old_admission);write_json(root/'summary.json',summary);write_json(root/'postprocessing_revision.json',audit)
static_rows=[]
with (root/'static_metrics.csv').open() as file:
 for r in csv.DictReader(file):
  for k in ('angle_deg','node_tag','modes'):r[k]=int(r[k])
  for k in ('reference_m','approximation_m','absolute_error_m','relative_error','remaining_static_flexibility_m'):r[k]=float(r[k]) if r[k] else None
  r['passed']=r['passed']=='True';static_rows.append(r)
publish(root,summary,descriptors,arrays,metrics,static_rows)
with (root/'REPORT.md').open('a') as file:
 file.write('\n## 发布前投影与子频带复核\n\n首版只用XYZ全带频率网格判断，已保留在iterations/cartesian_grid_check_v1。随后使用同一保存复数响应及其隔点粗网格，\n逐项核对最终XYZ/沿风/横风输出在两个冻结频带的最大幅值与RMS；没有新增矩阵、特征或有限元求解。\n最终'+str(summary['grid_checked_output_bands'])+'个输出×频带中的'+str(summary['grid_failed_output_bands'])+'个网格检查未通过；准入状态变化'+str(len(changed))+'条。\n完整修订台账见[postprocessing_revision.json](postprocessing_revision.json)。原始复数响应未改动。\n')
print(json.dumps({'grid_failures':summary['grid_failed_output_bands'],'admission_changes':len(changed),'admitted_outputs':summary['admitted_outputs']}))
