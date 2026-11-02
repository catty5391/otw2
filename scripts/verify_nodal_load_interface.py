"""Reproducible numerical evidence for the shared wind/rain loading interface.

Uses the analytic test-bench spring (not a tower) and an independently rerun
full-tower static result. Does not replace the prior rain physics validation.
"""
from pathlib import Path
import csv,json,shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import openseespy.opensees as ops
from tests.test_nodal_loads import transient_spring,exact_ramp_response
from rain_loading.physics import marshall_palmer

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'rain_loading/results'


def inputs(dt):
    t=np.arange(round(4/dt)+1)*dt
    wind=20+3*np.sin(2*np.pi*.7*t)
    rain=30+10*(1-np.cos(2*np.pi*.31*t))
    ramp=np.minimum(t/.5,1.)
    dry_force=.5*1.225*.01*wind**2*ramp
    wet_force=np.array([marshall_palmer(r,normalize_rain_rate=True).water_content_kg_m3 for r in rain])*.01*wind**2*ramp
    return t,dry_force,wet_force


def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];convergence=[]
    for dt in (.01,.005,.0025):
        t,wind,rain=inputs(dt)
        response,ledger_error,dynamic_error=transient_spring(wind,rain,dt)
        exact=exact_ramp_response(wind+rain,dt)
        error=float(np.max(abs(response-exact)))
        convergence.append(dict(dt_s=dt,max_displacement_error_m=error,
            relative_peak_error=error/float(np.max(abs(exact))),
            load_ledger_error_N=ledger_error,dynamic_residual_N=dynamic_error))
    w,_,_=transient_spring(wind,rain,dt,mode='wind')
    r,_,_=transient_spring(wind,rain,dt,mode='rain')
    zero,_,_=transient_spring(wind,np.zeros_like(rain),dt)
    superposition=float(np.max(abs(response-w-r)))
    zero_error=float(np.max(abs(zero-w)))
    checks += [dict(name='通用接口：风雨时程叠加与零雨回归',passed=superposition<1e-11 and zero_error<1e-11,
         value=f'叠加误差 {superposition:.3g} m；零雨回归 {zero_error:.3g} m',criterion='同一线性模型，最大差 < 1e-11 m'),
       dict(name='通用接口：实际荷载与动力平衡',passed=max(x['load_ledger_error_N'] for x in convergence)<1e-9 and max(x['dynamic_residual_N'] for x in convergence)<1e-7,
         value=f"账本最大误差 {max(x['load_ledger_error_N'] for x in convergence):.3g} N；动力残差 {max(x['dynamic_residual_N'] for x in convergence):.3g} N",
         criterion='外力=Ma+Cv+Ku，含已平衡预载'),
       dict(name='通用接口：独立精确解与步长收敛',passed=convergence[-1]['relative_peak_error']<.001 and convergence[-1]['max_displacement_error_m']<.2*convergence[0]['max_displacement_error_m'],
         value=f"最细步长相对误差 {convergence[-1]['relative_peak_error']:.3g}；细/粗误差比 {convergence[-1]['max_displacement_error_m']/convergence[0]['max_displacement_error_m']:.3g}",
         criterion='分段线性输入的矩阵指数精确解；细步误差 < 0.1%，且明显下降')]
    old_path=OUT/'runs/angle_0/summary.json'
    new_path=ROOT/'rain_loading/interface_validation/tower_angle_0/summary.json'
    tower=dict(status='not_available')
    if old_path.exists() and new_path.exists():
        old=json.loads(old_path.read_text());new=json.loads(new_path.read_text())
        deltas=[abs(a[k]-b[k]) for a,b in zip(old['states'],new['states']) for k in ('ux_mm','uy_mm','uz_mm','along_wind_mm')]
        reaction_deltas=[abs(a-b) for x,y in zip(old['states'],new['states']) for a,b in zip(x['reactions_force_N'],y['reactions_force_N'])]
        ok=(old['status']==new['status']=='completed' and len(old['states'])==len(new['states'])==2
            and old['source_sha256']==new['source_sha256'] and all(x['equilibrium_passed'] for x in new['states']))
        tower=dict(status=new['status'],max_displacement_difference_mm=max(deltas,default=float('inf')),
            max_reaction_difference_N=max(reaction_deltas,default=float('inf')),
            new_along_wind_mm=[x['along_wind_mm'] for x in new['states']],
            rain_increment_percent=new.get('rain_displacement_increase_percent'),
            original_source_sha256=new['source_sha256'])
        checks.append(dict(name='通用接口：实际Steel02全塔回归',passed=ok and max(deltas)<1e-8 and max(reaction_deltas)<1e-6,
            value=f"位移差 {max(deltas):.3g} mm；反力差 {max(reaction_deltas):.3g} N",
            criterion='0°、30m/s、100mm/h，接口替换前后同模型同荷载'))
    else:checks.append(dict(name='通用接口：实际Steel02全塔回归',passed=False,value='缺少复算结果',criterion='须实际求解后才判定'))
    result=dict(schema='otw2.nodal_load_interface.v1',date='2026-11-02',engine_version=ops.version(),
        passed=all(x['passed'] for x in checks),checks=checks,convergence=convergence,
        superposition_error_m=superposition,zero_rain_regression_error_m=zero_error,tower_regression=tower,
        benchmark=dict(type='single linear spring, not a tower dynamic analysis',mass_kg=2.,stiffness_N_m=200.,
            damping_N_s_m=.4,preload_N=-20.,collector_area_m2=.01,initial_ramp_s=.5),
        nonuniform_hold_workaround='residual Path ending at zero + uniform held step; tested in real OpenSees')
    (OUT/'loading_interface_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (OUT/'loading_interface_history.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['time_s','wind_force_N','rain_force_N','wind_only_m','rain_only_m','combined_m','exact_combined_m'])
        writer.writerows(zip(t,wind,rain,w,r,response,exact))
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.25})
    fig,ax=plt.subplots(1,3,figsize=(13,4))
    ax[0].plot(t,response*1000,label='OpenSees wind + rain');ax[0].plot(t,exact*1000,'--',label='Exact linear-ramp reference')
    ax[0].set(xlabel='Time [s]',ylabel='Displacement increment [mm]',title='Known spring benchmark');ax[0].legend(fontsize=8)
    ax[1].plot(t,(response-w)*1000,label='Combined minus wind');ax[1].plot(t,r*1000,'--',label='Rain-only response')
    ax[1].set(xlabel='Time [s]',ylabel='Rain increment [mm]',title='Independent load superposition');ax[1].legend(fontsize=8)
    ax[2].loglog([x['dt_s'] for x in convergence],[x['max_displacement_error_m'] for x in convergence],'o-')
    ax[2].set(xlabel='Integration dt [s]',ylabel='Max error vs exact [m]',title='Time-step convergence')
    plt.tight_layout();plt.savefig(OUT/'loading_interface_validation.png',dpi=170);plt.close()
    shutil.copy2(ROOT/'util/processing/NODAL_LOADS.md',OUT/'loading_interface.md')
    with (OUT/'loading_interface.md').open('a',encoding='utf-8') as f:
        f.write('\n## 本轮实际运行结果\n\n')
        for x in checks:f.write(f"- {'通过' if x['passed'] else '未通过'}：{x['name']}。{x['value']}。\n")
        f.write('\n完整记录见 `loading_interface_verification.json`；动态图来自已知弹簧验证模型，不是全塔风雨动力响应。\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['passed']:raise SystemExit('Load-interface verification failed')


if __name__=='__main__':main()
