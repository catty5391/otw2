"""Reproduce spectrum/load checks and publish actual evidence to the dashboard.

Run the independent tower workers first for FE results, then this module.
Missing/failed FE cases remain explicitly missing/failed in the publication.
"""
from __future__ import annotations
import csv,json,math,hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.special import gammainc
from scipy.signal import welch
from .physics import *
from .tower_check import tower_geometry,save_json

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent/'results'
SOURCES=[
 {'title':'Marshall & Palmer (1948): The distribution of raindrops with size','url':'https://doi.org/10.1175/1520-0469(1948)005<0165:TDORWS>2.0.CO;2','note':'指数粒径谱来源；不是雨强时间功率谱。'},
 {'title':'Atlas et al. (1973): Doppler radar characteristics of precipitation at vertical incidence','url':'https://doi.org/10.1029/RG011i001p00001','note':'终速指数近似；本算例限D=0.2–5.8 mm。'},
 {'title':'Tian, Zeng & Fu (2018): Velocity Ratio of Wind-Driven Rain','url':'https://doi.org/10.1061/(ASCE)CF.1943-5509.0001210','note':'雨滴速度比、运动方程与经验冲击模型。常数gamma示例不等于复现其轨迹模型。'},
 {'title':'Fu & Li (2017): Rain load for transmission tower-line system','url':'https://objectext.auckland.ac.nz/figshare/9808657/Fu_Rainloadfortransmissiontowerlinesystem.pdf','note':'公开会议全文；区分雨滴脉冲与湿态导线气动系数。'},
 {'title':'Fu, Li & Yi (2015): Research on motion of wind-driven rain and rain load acting on transmission tower','url':'https://doi.org/10.1016/j.jweia.2015.01.008','note':'原研究提醒关注雨造成的气动性质改变；不能追求固定响应放大比例。'},
 {'title':'Fu & Li (2016): Dynamic analysis of transmission tower-line system subjected to wind and rain loads','url':'https://doi.org/10.1016/j.jweia.2016.08.010','note':'塔线雨荷载和湿态导线气动问题的直接参考。'},
 {'title':'DTU HAWC2 manual: Kaimal spectrum','url':'https://www.hawc2.dk/-/media/sites/hawc2/hawc2-download/hawc2-manual/manual_version_4-7.pdf','note':'用于合成风速谱；不把它命名为雨强谱。'},
 {'title':'Fu et al. (2021): Joint probability distribution of wind speed and rain intensity','url':'https://doi.org/10.1016/j.engstruct.2021.111913','note':'以后进行风险计算需要实际气象联合分布及时间尺度一致性。'},
]


def csv_save(name,rows):
    if not rows:
        (OUT/name).unlink(missing_ok=True)
        return
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def fig_save(name):
    plt.tight_layout();plt.savefig(OUT/name,dpi=170);plt.close()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.25})
    figures=[];checks=[];tables=[]
    def figure(name,title,caption):figures.append(dict(title=title,file=name,caption=caption))
    def check(name,passed,value,criterion):checks.append(dict(name=name,passed=bool(passed),value=value,criterion=criterion))
    def table(title,columns,rows):tables.append(dict(title=title,columns=[dict(key=k,label=v) for k,v in columns],rows=rows))

    # 1. Particle-size distribution and water flux closure.
    rain_rates=[10,25,50,100,200];spectra=[];closure=[]
    fig,ax=plt.subplots(1,2,figsize=(11,4))
    for r in rain_rates:
        raw=marshall_palmer(r);s=marshall_palmer(r,normalize_rain_rate=True)
        ax[0].semilogy(s.diameter_mm,raw.concentration_m3_mm,label=f'{r} mm/h')
        ax[1].plot(s.diameter_mm,s.mass_kg*s.concentration_m3_mm*1000,label=f'{r} mm/h')
        closure.append(dict(rain_mm_h=r,raw_recovered_mm_h=raw.recovered_rain_mm_h,
            closed_recovered_mm_h=s.recovered_rain_mm_h,scale=s.normalization_factor,LWC_g_m3=1000*s.water_content_kg_m3))
        for j,d in enumerate(s.diameter_mm):spectra.append(dict(rain_mm_h=r,D_mm=d,bin_width_mm=s.bin_width_mm[j],
            raw_N_m3_mm=raw.concentration_m3_mm[j],closed_N_m3_mm=s.concentration_m3_mm[j],vt_m_s=s.terminal_speed_m_s[j]))
    ax[0].set(xlabel='Drop diameter D [mm]',ylabel='Raw N(D) [m^-3 mm^-1]',title='Raw Marshall-Palmer number spectrum')
    ax[1].set(xlabel='Drop diameter D [mm]',ylabel='Water mass per diameter [g/m^3/mm]',title='Rain-rate-closed water mass distribution')
    for a in ax:a.legend(fontsize=8)
    fig_save('drop_spectrum.png');figure('drop_spectrum.png','雨滴粒径谱与质量贡献','横轴是雨滴直径，不是频率。左为原始M–P数浓度；右为雨强闭合后的质量谱。200 mm/h仅为敏感性工况，不能证明M–P适合当地强对流暴雨。')
    csv_save('droplet_spectrum.csv',spectra)
    fig,ax=plt.subplots(figsize=(7,4));x=np.array(rain_rates)
    ax.plot(x,x,'k--',label='Requested rain rate');ax.plot(x,[v['raw_recovered_mm_h'] for v in closure],'o-',label='Raw MP + Atlas + finite diameter range')
    ax.plot(x,[v['closed_recovered_mm_h'] for v in closure],'x',ms=9,label='Explicit rain-rate closure')
    ax.set(xlabel='Input R [mm/h]',ylabel='Integrated vertical water flux [mm/h]');ax.legend(fontsize=8)
    fig_save('rain_flux_closure.png');figure('rain_flux_closure.png','输入雨强与谱积分回算雨强','归一化选项通过调整整个数浓度使水量闭合；其有效N0改变，不能仍称原参数M–P谱。')
    table('雨强闭合检查',[('rain_mm_h','输入 mm/h'),('raw_recovered_mm_h','原始回算 mm/h'),('closed_recovered_mm_h','归一化回算 mm/h'),('scale','数浓度缩放'),('LWC_g_m3','含水量 g/m³')],closure)
    check('雨强水量闭合',max(abs(x['closed_recovered_mm_h']-x['rain_mm_h']) for x in closure)<1e-9,'最大绝对误差 < 1e-9 mm/h','所有5档雨强回算正确')
    # Quadrature convergence against a closed-form truncated gamma integral.
    lam=4.1*50**(-.21)
    exact=1000*np.pi/6*1e-9*8000*6/lam**4*(gammainc(4,lam*5.8)-gammainc(4,lam*.2))
    convergence=[dict(bins=n,relative_error=abs(marshall_palmer(50,bins=n).water_content_kg_m3/exact-1)) for n in (60,120,240,480)]
    error=next(v['relative_error'] for v in convergence if v['bins']==240)
    check('粒径积分独立解析检查',error<1e-5,f'240格相对误差 {error:.3g}','截断Gamma矩解析式，相对误差 < 1e-5')
    truncation=[]
    for lo,hi in ((.16,5.8),(.2,5.),(.2,5.8),(.2,6.),(.3,5.8)):
        s=marshall_palmer(100,minimum_mm=lo,maximum_mm=hi,normalize_rain_rate=True)
        truncation.append(dict(Dmin_mm=lo,Dmax_mm=hi,LWC_g_m3=s.water_content_kg_m3*1000,raw_rain_mm_h=s.raw_recovered_rain_mm_h))

    # 2. Force sensitivity: rain impact, empirical multiplier, and wet air Cd separate.
    pressure=[]
    for u in (20,30,40):
        for r in rain_rates:
            s=marshall_palmer(r,normalize_rain_rate=True)
            for gamma in (.6,1.,1.2):
                p=float(plane_normal_pressure(s,drop_velocity(s,[u,0,0],horizontal_ratio=gamma),[1,0,0])[0])
                pw=.5*1.225*u*u
                pressure.append(dict(wind_m_s=u,rain_mm_h=r,gamma=gamma,wind_pressure_Pa=pw,
                    momentum_pressure_Pa=p,tian2018_factor_pressure_Pa=p*np.pi/2,
                    impact_over_dry_percent=100*p/pw))
    csv_save('pressure_sweep.csv',pressure)
    fig,ax=plt.subplots(1,2,figsize=(11,4))
    for gamma in (.6,1.,1.2):
        rows=[v for v in pressure if v['wind_m_s']==30 and v['gamma']==gamma]
        ax[0].plot(rain_rates,[v['impact_over_dry_percent'] for v in rows],'o-',label=f'gamma={gamma}')
    ax[0].set(xlabel='R [mm/h]',ylabel='Rain impact / dry wind pressure [%]',title='Normal plate; dry Cd=1');ax[0].legend()
    s=marshall_palmer(100,normalize_rain_rate=True);p=s.water_content_kg_m3*900;pw=.5*1.225*900
    wet_changes=np.array([-.1,0.,.1]);ax[1].bar(['Cd -10%','Cd unchanged','Cd +10%'],100*wet_changes+100*p/pw)
    ax[1].axhline(0,color='k',lw=.8);ax[1].set(ylabel='Total load change vs dry wind [%]',title='Independent, uncalibrated wet-Cd sensitivity')
    fig_save('load_sensitivity.png');figure('load_sensitivity.png','雨滴冲击与湿态风阻敏感性','左图是同一投影面积、Cd=1的法向平板。γ为人为敏感性输入，可能大于1。右图±10%湿态Cd只是示例，不是本塔导线的试验参数；总效应可能由气动变化主导。')
    table('30 m/s时的独立冲击基线',[('rain_mm_h','雨强 mm/h'),('gamma','γ'),('momentum_pressure_Pa','动量基线 Pa'),('tian2018_factor_pressure_Pa','2018系数模型 Pa'),('impact_over_dry_percent','基线/干风 %')],
          [x for x in pressure if x['wind_m_s']==30 and x['gamma']==1])

    # 3. Synthetic histories: a wind PSD plus a separately declared rain envelope.
    t,u,f,su,wind_audit=kaimal_history()
    r=np.interp(t,[0,150,250,400,500,600],[25,25,100,100,50,50])
    water=np.array([marshall_palmer(value,normalize_rain_rate=True).water_content_kg_m3 for value in r])
    rain_p=water*u*np.abs(u);dry_p=.5*1.225*u*np.abs(u)
    trows=[dict(time_s=a,synthetic_wind_m_s=b,assumed_rain_mm_h=c,dry_pressure_Pa=d,rain_pressure_Pa=e,
                combined_pressure_Pa=d+e) for a,b,c,d,e in zip(t,u,r,dry_p,rain_p)]
    csv_save('synthetic_history.csv',trows)
    fig,ax=plt.subplots(3,1,figsize=(11,7),sharex=True)
    ax[0].plot(t,u,lw=.7);ax[0].set(ylabel='Wind [m/s]',title='Synthetic point wind + prescribed rain envelope (NOT observations)')
    ax[1].plot(t,r,color='#287d52');ax[1].set(ylabel='Assumed R [mm/h]')
    ax[2].plot(t,rain_p,color='#ba601f',lw=.8);ax[2].set(ylabel='Impact pressure [Pa]',xlabel='Time [s]')
    fig_save('synthetic_history.png');figure('synthetic_history.png','从风速时程和雨强包络得到雨荷载时程','风速用单点Kaimal谱合成；雨强包络人为指定，未拟合降雨时间谱、风雨联合概率或空间相干性。该图是荷载时程，不是全塔风雨动力响应。')
    check('合成风有限频带方差',abs(wind_audit['realized_variance']-wind_audit['discrete_band_variance'])<1e-10,
          f"时域方差 {wind_audit['realized_variance']:.6f}，谱离散积分 {wind_audit['discrete_band_variance']:.6f}",
          'Parseval一致；没有偷偷缩放到无限频带方差9')

    # A force PSD can be derived from a declared velocity/arrival model, but
    # must not be mistaken for an observed or universal rainfall-intensity PSD.
    fixed_water=marshall_palmer(50,normalize_rain_rate=True).water_content_kg_m3
    fixed_pressure=fixed_water*u*np.abs(u)
    fw,sw=welch(u,fs=10.,nperseg=2048,detrend='constant')
    _,sp=welch(fixed_pressure,fs=10.,nperseg=2048,detrend='constant')
    target=4*9.*120./30./(1+6*fw*120./30.)**(5/3)
    linear_pressure=(2*fixed_water*30.)**2*target
    csv_save('stationary_load_spectrum.csv',[dict(frequency_Hz=a,wind_welch_m2_s2_per_Hz=b,
        kaimal_target_m2_s2_per_Hz=c,rain_pressure_welch_Pa2_per_Hz=d,
        rain_pressure_linearized_Pa2_per_Hz=e) for a,b,c,d,e in zip(fw,sw,target,sp,linear_pressure)])
    fig,ax=plt.subplots(1,2,figsize=(11,4));keep=fw>0
    ax[0].loglog(fw[keep],sw[keep],lw=.8,label='Synthetic history: Welch estimate')
    ax[0].loglog(fw[keep],target[keep],'k--',label='Kaimal target')
    ax[0].set(xlabel='Frequency [Hz]',ylabel='Wind PSD [(m/s)^2/Hz]',title='Single-point synthetic wind');ax[0].legend(fontsize=8)
    ax[1].loglog(fw[keep],sp[keep],lw=.8,label='p(t)=LWC*U(t)^2: Welch estimate')
    ax[1].loglog(fw[keep],linear_pressure[keep],'k--',label='Small fluctuation approximation')
    ax[1].set(xlabel='Frequency [Hz]',ylabel='Rain pressure PSD [Pa^2/Hz]',title='Fixed R=50 mm/h; gamma=1; plate');ax[1].legend(fontsize=8)
    fig_save('load_power_spectrum.png');figure('load_power_spectrum.png','从风速谱推得条件雨荷载谱','固定R=50 mm/h，p(t)=LWC·U(t)²。虚线近似Sp≈(2LWC·Umean)²Su，仅对小脉动适用；实线为本合成序列Welch估计。这里没有叠加离散雨滴接触脉冲，不是实测或通用雨强PSD。')

    # 4. Particle arrival validation, including bin-duration dependence.
    s=marshall_palmer(50,normalize_rain_rate=True);poisson=[];series=None
    for dt in (.01,.02,.1):
        pt,pf,audit=poisson_plate_history(s,30,dt_s=dt);poisson.append(audit)
        if dt==.02:series=(pt,pf)
        z=abs(audit['observed_mean_N']-audit['expected_mean_N'])/audit['standard_error_mean_N']
        check(f'泊松雨滴冲量均值 dt={dt}s',z<5,f'偏差 {z:.3f} 个标准误','均值与动量通量差 < 5个标准误')
        check(f'泊松雨滴冲量方差 dt={dt}s',abs(audit['observed_variance_N2']/audit['expected_variance_N2']-1)<.1,
              f"实测/解析 {audit['observed_variance_N2']/audit['expected_variance_N2']:.4f}",'方差相对差 < 10%')
    fig,ax=plt.subplots(1,2,figsize=(11,4));pt,pf=series;mask=pt<8
    ax[0].plot(pt[mask],pf[mask],lw=.6,label='Bin-averaged random force')
    ax[0].axhline(poisson[1]['expected_mean_N'],color='r',ls='--',label='Momentum-flux mean')
    ax[0].set(xlabel='Time [s]',ylabel='Force on 0.01 m^2 plate [N]');ax[0].legend(fontsize=8)
    ax[1].loglog([x['dt_s'] for x in poisson],[x['observed_variance_N2'] for x in poisson],'o',label='Poisson realization')
    ax[1].loglog([x['dt_s'] for x in poisson],[x['expected_variance_N2'] for x in poisson],'-',label='Analytic variance proportional to 1/dt')
    ax[1].set(xlabel='Averaging bin dt [s]',ylabel='Force variance [N^2]');ax[1].legend(fontsize=8)
    fig_save('poisson_verification.png');figure('poisson_verification.png','离散雨滴冲量与连续平均荷载交叉检查','独立泊松到达是假设，仅用于检验粒径→碰撞频次→冲量的实现。时间格内平均力的方差随dt变化，不能把这些格内峰值当作物理接触峰值或真实雨谱。')

    # 5. Map to actual tower geometry and one representative sagged conductor.
    _,nodes,members=tower_geometry(OUT/'geometry')
    ss=np.linspace(0,1,21);cnodes={i+1:(0.,300*a,30.-4*8*a*(1-a)) for i,a in enumerate(ss)}
    cmembers=[dict(tag=i,node_i=i,node_j=i+1,breadth_m=.0276) for i in range(1,21)]
    map_rows=[];nodal=[];cnodal=[];maps=[]
    s=marshall_palmer(100,normalize_rain_rate=True)
    for angle in (0,45,90):
        d=np.array([math.cos(math.radians(angle)),math.sin(math.radians(angle)),0.]);v=drop_velocity(s,30*d)
        for label,ns,ms in [('tower',nodes,members),('conductor',cnodes,cmembers)]:
            loads,rows,audit=distribute_members(ns,ms,lambda a,b:cylinder_line_load(s,v,a,b))
            air,_,air_audit=distribute_members(ns,ms,lambda a,b:dry_cylinder_line_load(30*d,a,b))
            maps.append(dict(component=label,angle_deg=angle,**audit))
            horizontal=float(np.array(audit['force_N'])@d);wind=float(np.array(air_audit['force_N'])@d)
            map_rows.append(dict(component=label,angle_deg=angle,rain_horizontal_N=horizontal,
                rain_downward_N=-audit['force_N'][2],dry_horizontal_N=wind,
                ratio_percent=100*horizontal/wind if abs(wind)>1e-9 else None))
            for n,force in sorted(loads.items()):
                (nodal if label=='tower' else cnodal).append(dict(angle_deg=angle,node_tag=n,x_m=ns[n][0],y_m=ns[n][1],z_m=ns[n][2],
                  rain_Fx_N=force[0],rain_Fy_N=force[1],rain_Fz_N=force[2],wind_Fx_N=air[n][0],wind_Fy_N=air[n][1],wind_Fz_N=air[n][2]))
            check(f'{label} {angle}°荷载映射',audit['force_mapping_error_N']<1e-7 and audit['moment_mapping_error_Nm']<1e-5,
                  f"合力误差 {audit['force_mapping_error_N']:.2g} N；力矩误差 {audit['moment_mapping_error_Nm']:.2g} Nm",'保留均布段荷载合力及初始坐标下力矩')
    csv_save('tower_nodal_loads.csv',nodal);csv_save('conductor_nodal_loads.csv',cnodal)
    fig,ax=plt.subplots(1,2,figsize=(11,4))
    for a,label,title in zip(ax,['tower','conductor'],['Actual tower geometry / breadth proxy','300 m sagged conductor / d=27.6 mm']):
        rows=[v for v in map_rows if v['component']==label];xs=np.arange(3)
        a.bar(xs-.17,[x['rain_horizontal_N'] for x in rows],.34,label='Along-wind rain force')
        a.bar(xs+.17,[x['rain_downward_N'] for x in rows],.34,label='Downward rain force')
        a.set(xticks=xs,xticklabels=['0 deg','45 deg','90 deg'],ylabel='Resultant [N]',title=title);a.legend(fontsize=8)
    fig_save('tower_line_loads.png');figure('tower_line_loads.png','作用到塔身与导线的方向分量','U=30 m/s、R=100 mm/h、γ=1。塔用实际1528根杆几何和角钢腿宽代理；线为27.6 mm、300 m跨、8 m初始抛物线弧垂的独立荷载映射。导线含竖向雨滴冲击；这不是完整塔线耦合响应。')
    table('塔身/导线荷载映射',[('component','对象'),('angle_deg','风向 °'),('dry_horizontal_N','干风沿风力 N'),('rain_horizontal_N','雨沿风力 N'),('rain_downward_N','雨向下力 N'),('ratio_percent','沿风增量 %')],map_rows)

    # 6. Include only actual committed and equilibrium-checked FE results.
    cases=[];case_rows=[]
    for angle in (0,45,90):
        path=OUT/'runs'/f'angle_{angle}'/'summary.json'
        if not path.exists():
            check(f'Steel02全塔 {angle}°完成',False,'尚未获得结果','实际完成重力、干风和加雨静力');continue
        case=json.loads(path.read_text());cases.append(case)
        ok=case['status']=='completed' and len(case['states'])==2 and all(x['equilibrium_passed'] for x in case['states'])
        check(f'Steel02全塔 {angle}°完成与平衡',ok,case['status'],'2个状态通过自由自由度与全局合力/力矩检查')
        if ok:
            dry,wet=case['states'];case_rows.append(dict(angle_deg=angle,wind_m_s=30.,rain_mm_h=100.,
                dry_displacement_mm=dry['along_wind_mm'],wet_displacement_mm=wet['along_wind_mm'],
                increase_percent=case['rain_displacement_increase_percent'],
                max_force_residual_N=max(x['force_balance_error_N'] for x in case['states']),
                max_moment_residual_Nm=max(x['moment_balance_error_Nm'] for x in case['states'])))
    if case_rows:
        fig,ax=plt.subplots(1,2,figsize=(10,4));xs=np.arange(len(case_rows));labels=[f"{x['angle_deg']} deg" for x in case_rows]
        ax[0].bar(xs-.17,[x['dry_displacement_mm'] for x in case_rows],.34,label='Dry wind')
        ax[0].bar(xs+.17,[x['wet_displacement_mm'] for x in case_rows],.34,label='Wind + impact')
        ax[0].set(xticks=xs,xticklabels=labels,ylabel='Along-wind displacement [mm]',title='Control node 350, above gravity state');ax[0].legend(fontsize=8)
        ax[1].bar(xs,[x['increase_percent'] for x in case_rows],color='#ba601f');ax[1].set(xticks=xs,xticklabels=labels,ylabel='Displacement increment [%]',title='Steel02 / 4 segments / bow L/1000')
        fig_save('tower_response.png');figure('tower_response.png','现有四分段Steel02全塔静力对照','实际OpenSees求解：重力→30 m/s干风→100 mm/h雨滴冲击。采用共同的杆件法向圆柱代理荷载，与既有推覆的面板/风向插值荷载定义不同；结果不能用于修改既有极限风速或损伤阈值。')
        table('全塔静力响应与独立平衡检查',[('angle_deg','风向 °'),('dry_displacement_mm','干风位移 mm'),('wet_displacement_mm','加雨位移 mm'),('increase_percent','增量 %'),('max_force_residual_N','合力残差 N'),('max_moment_residual_Nm','力矩残差 Nm')],case_rows)
    csv_save('case_summary.csv',case_rows)
    all_ok=all(x['passed'] for x in checks)
    verification=dict(schema='otw2.rain_loading.verification.v1',numerical_checks_passed=all_ok,
        physical_validation=False,checks=checks,quadrature=convergence,truncation=truncation,
        rain_rate_closure=closure,wind=wind_audit,poisson=poisson,load_mapping=maps,tower_cases=cases)
    save_json(OUT/'verification.json',verification)
    summary=dict(schema='otw2.rain_loading.v1',date='2026-11-02',title='雨谱、雨荷载与塔线作用验证',
        subtitle='从粒径数浓度到节点力：文献调查、守恒基线、随机冲量和全塔静力对照',
        status='numerical_verified' if all_ok else 'partial',
        scope='独立研究模块：数值实现验证，不代表气象、雨滴撞击或本塔湿态气动的物理标定。',
        literature_report_available=(ROOT/'literature/rain_loading_investigation_20261102/README.md').exists(),
        findings=[
          'M–P雨谱是粒径分布N(D)，不是雨强时间谱。时间变化还需要R(t)、雨滴速度及空间关系。',
          '雨强50 mm/h时，当前原始M–P + Atlas + 有限粒径窗回算约54.1 mm/h；已保留原谱并另设显式水量闭合选项。',
          '30 m/s、100 mm/h、γ=1的法向平板守恒冲击约3.68 Pa，是Cd=1干风压力的约0.67%；该比例不是全塔或所有暴雨的通用放大系数。',
          '文献冲击模型与动量基线系数存在差异；2018式对应π/2倍。本模块并列报告而未隐式混用。',
          '导线水膜会改变气动性质，可能比单纯雨滴冲击更重要；现有资料不足以给本型号确定湿态Cd。',
          '已经检查粒径积分、水量、泊松冲量和节点荷载守恒；全塔结果只收录实际收敛且通过平衡检查的状态。'],
        assumptions=[
          '角度从全局+X转向+Y，表示流向：0°横线方向，90°沿线方向；独立导线的水平弦沿Y轴。',
          '粒径0.2–5.8 mm、240格；Atlas终速；空气密度1.225 kg/m³、水密度1000 kg/m³；不考虑竖向风。',
          '默认按输入雨强归一化；γ=1为对照假设，0.6/1/1.2为敏感性，不是拟合出的轨迹参数。',
          '杆/线采用投影宽度内横向动量完全截获的collector近似；严格光滑曲面仅局部法向停止给出2/3系数，真实湿态相互作用待试验。',
          '角钢以腿宽代理圆柱直径，无遮挡或真实迎雨截面校准；导线27.6 mm外径取项目参数表。',
          '塔身荷载集中到原始物理杆两端，未施加到四分段内部节点；本轮验证整体传力，不验证局部均布雨载弯矩分布。',
          '雨滴不作为永久附加质量；本轮没有积水、雨凇、接触脉冲形状、湿态Cd或雨线舞动模型。',
          '合成时程无实测雨强谱/风雨联合分布，导线仅荷载映射，全塔仅静力；尚未完成塔线风雨耦合时程与易损性。'],
        steps=[dict(title='1. 文献溯源',detail='区分粒径谱、雨速、雨强时程和冲击力定义；保留未取得公式/参数的缺口。'),
          dict(title='2. 粒径与水量',detail='M–P数浓度→终速→回算雨强；原谱与水量闭合分开。'),
          dict(title='3. 雨滴到荷载',detail='到达率乘单滴冲量，分别处理平板法向、杆/线横向与竖向分量。'),
          dict(title='4. 独立数值核对',detail='解析粒径矩、泊松随机冲量、步长方差及映射合力/力矩交叉验证。'),
          dict(title='5. 现有模型接入',detail='真实塔几何与代表导线输出节点力；四分段Steel02完成静力加雨对照。'),
          dict(title='6. 后续物理验证',detail='取得当地高频雨强/粒径数据及本型号导线湿态Cd，再做空间风雨时程和塔线耦合。')],
        equations=[
          dict(name='粒径谱',expression='N(D)=8000 exp[-4.1 R^(-0.21) D]',description='D:mm；N:m⁻³ mm⁻¹；R:mm/h。'),
          dict(name='水量闭合',expression='R_calc=3.6×10^6 ∫ (π/6)(10^-3 D)^3 vt(D) N(D) dD',description='dD仍按mm积分；体积计算必须将直径转换为m。'),
          dict(name='法向平板动量通量',expression='p=∫ m(D) N(D) |vn(D)| vn(D) dD',description='单位Pa；到达率乘单滴冲量，不是把单滴峰值直接相加。'),
          dict(name='杆/线投影收集器',expression='q=b ∫ m(D) N(D) |v_perp(D)| v_perp(D) dD',description='单位N/m；v_perp=v−(v·e)e，雨滴竖向速度仍保留；不是严格圆柱曲面接触解。'),
          dict(name='节点力',expression='F_i += q L/2 ; F_j += q L/2',description='均匀直线段荷载的端点集中映射，保持合力与力矩；不是梁一致荷载向量。')],
        figures=figures,tables=tables,verification=dict(checks=checks),sources=SOURCES,
        artifacts=[dict(title=title,file=name) for title,name in [('完整研究与复现报告','REPORT.md'),('验证记录','verification.json'),('全塔静力结果','case_summary.csv'),('粒径谱数据','droplet_spectrum.csv'),('合成荷载时程','synthetic_history.csv'),('条件荷载功率谱','stationary_load_spectrum.csv'),('荷载敏感性','pressure_sweep.csv'),('塔身节点荷载','tower_nodal_loads.csv'),('导线节点荷载','conductor_nodal_loads.csv')] if (OUT/name).exists()])
    interface_path=OUT/'loading_interface_verification.json'
    if interface_path.exists():
        interface=json.loads(interface_path.read_text(encoding='utf-8'))
        if interface.get('schema')!='otw2.nodal_load_interface.v1':raise ValueError('Unknown load interface evidence schema')
        summary['verification']['checks']=summary['verification']['checks']+interface['checks']
        summary['status']='numerical_verified' if all(x.get('passed') is True for x in summary['verification']['checks']) else 'partial'
        summary['findings'].append('已完善风雨共用的节点加载接口：支持独立方向/节点时程、选择性移除、失败回滚；旧风入口保留。实际全塔回归与独立弹簧动力验证见新增图和接口报告。')
        summary['steps'].append(dict(title='7. 通用加载接口验证',detail='节点力与物理荷载生成分开；静力、比例时程和非比例多节点时程共用安装层，并核验风雨独立叠加。'))
        if (OUT/'loading_interface_validation.png').exists():
            summary['figures'].append(dict(title='通用荷载接口：动力叠加与精确解验证',file='loading_interface_validation.png',
                caption='已知M=2kg、K=200N/m、C=0.4N·s/m弹簧模型，验证风雨时程输入、独立叠加与步长收敛；不是全塔风雨动力响应。0°实际全塔静力接口回归另记在接口报告中。'))
        for title,file in [('通用加载接口说明与实测验证','loading_interface.md'),('接口验证JSON','loading_interface_verification.json'),('接口验证时程','loading_interface_history.csv')]:
            if (OUT/file).exists():summary['artifacts'].append(dict(title=title,file=file))
    write_report(summary,verification,case_rows)
    if not any(x['file']=='REPORT.md' for x in summary['artifacts']):summary['artifacts'].insert(0,dict(title='完整研究与复现报告',file='REPORT.md'))
    save_json(OUT/'summary.json',summary)
    print(json.dumps(dict(numerical_checks_passed=all_ok,checks=len(checks),tower_cases=len(case_rows),figures=len(figures)),ensure_ascii=False))


def write_report(summary,v,cases):
    lines=['# 雨谱、雨荷载与塔线作用研究及验证','',
      '日期：2026-11-02。当前成果是有来源说明的研究原型和数值检查。没有气象实测、雨滴冲击试验或本塔湿态气动试验，因此不称物理验证完成。','',
      '## 1. 本轮做了什么','']
    lines += [f"{i+1}. **{x['title']}**：{x['detail']}" for i,x in enumerate(summary['steps'])]
    lines+=['','## 2. 雨谱到底是什么','',
      'M–P给定雨强条件下的粒径数浓度。它描述每立方米空气、每毫米粒径区间内的雨滴数，不给雨滴到达时间，也不描述暴雨过程的持续时间。雨强R(t)决定粒径分布随时间变化；雨滴速度决定撞击频次与冲量。把M–P横轴当频率，或把Kaimal风速谱直接命名为雨谱，都不成立。',
      '本轮合成风速使用单点Kaimal形式，雨强包络明确人为指定。若要取得真实雨强PSD，需先明确雨量计/雨滴谱仪采样间隔、平稳时间窗和雨段筛选，再估计谱与风雨互谱；一分钟雨量不能凭插值变成可信的0.1秒波动。空间雨场与风场相干性也须另立假设或用数据估计。','',
      '另外单独使用固定R=50mm/h计算条件雨荷载PSD：对正向来流，p=LWC·U²。小脉动线性化给`S_p≈(2 LWC U_mean)² S_u`；图中与完整平方时程的Welch谱并列，不要求两者严格相等。这是本项目自主推导的条件荷载谱，不是通用雨强谱，未包含随机滴到达的高频接触脉冲。','',
      '## 3. 已实现公式与单位','']
    for e in summary['equations']:lines += [f"- **{e['name']}**：`{e['expression']}`。{e['description']}"]
    lines += ['',
      '终速选用`vt=9.65−10.3 exp(−0.6D)`，D为mm，vt为m/s。基线粒径0.2–5.8mm，不将该式用于0.1mm后偷偷截零。谱积分使用中点求积、240格，另做60/120/240/480格及粒径截断敏感性。',
      '原始MP中N0固定8000。水量闭合选项取`c=R_input/R_calc`并令`N_closed=c N_raw`，这是显式工程修正，不能仍声称N0不变。原谱、c和回算量均导出。',
      '平板采用法向完全非弹性停止；杆/线采用投影宽度截获的横向动量完全吸收，忽略轴向摩擦和端面。后者是collector近似，不是光滑圆柱曲面法向碰撞积分的精确解。若每个曲面点仅停止局部法向速度、切向保持，则圆周积分给出2/3倍系数；这说明表面相互作用也是模型参数。',
      '2018 Tian–Zeng–Fu Eq.(11)在同样数浓度及水平速度下对应`(π²/12)ρ D³ N Vr²`，本守恒基线是`(π/6)ρ D³ N Vr²`，两者比值π/2。我们只并列敏感性，不将经验系数隐藏于动量守恒定义。2017会议单滴峰值经验式还需要脉冲面积；未获取数字化接触波形时，不能由峰值直接推得平均塔荷载。','',
      '## 4. 数值结果','',
      '|输入雨强 mm/h|原谱回算 mm/h|闭合系数|闭合含水量 g/m³|','|---|---|---|']
    for x in v['rain_rate_closure']:lines.append(f"|{x['rain_mm_h']}|{x['raw_recovered_mm_h']:.4f}|{x['scale']:.6f}|{x['LWC_g_m3']:.6f}|")
    lines += ['',
      '法向平板U=30 m/s、R=100 mm/h、γ=1：冲击约3.6778 Pa，干风Cd=1时压力551.25 Pa，比值约0.6672%。这只是当前粒径/雨速/截获模型的力学量级，不是全塔响应放大系数。雨速γ按平方进入该平板模型，不能不加说明地固定为实测值。',
      '干湿Cd±10%的例子刻意显示气动参数的不确定性可能超过单纯雨滴冲击。±10%未标定，不代表湿态风阻必定增大；导线型号、表面粗糙度、Re、水膜/水线都影响它。若试验提供的是已包含雨滴冲击的总力系数，不能再加一次冲击力。','',
      '### 4.1 全塔静力与导线映射','',
      '全塔沿用Z30103A6实际几何和四分段Steel02、L/1000半正弦缺陷，随机种子30103。重力先平衡；随后30m/s干风，再增加100mm/h雨荷载。控制节点350，36.4m，位移扣除重力平衡位移。干风和雨采用相同的成员腿宽圆柱代理，干风Cd=1。没有使用之前推覆的面板插值荷载，因此本结果不能直接用于修订之前的推覆/极限风速。',
      '风向定义为从全局+X转向+Y的流向：0°横线、90°沿线；独立导线弦沿Y。塔身荷载集中到原始物理杆两端，没有在4段内部节点分配均布雨力。因此合力/力矩守恒不代表杆件局部雨载弯矩已复现；本轮定位为整体节点传力验证，后续局部应力分析须改用相容的分段/一致荷载。',
      '|风向 °|干风位移 mm|加雨位移 mm|增量 %|最大合力残差 N|最大力矩残差 Nm|','|---|---|---|---|---|---|']
    for x in cases:lines.append(f"|{x['angle_deg']}|{x['dry_displacement_mm']:.6f}|{x['wet_displacement_mm']:.6f}|{x['increase_percent']:.6f}|{x['max_force_residual_N']:.3g}|{x['max_moment_residual_Nm']:.3g}|")
    if not cases:lines.append('|尚无通过检查的全塔状态||||||')
    lines += ['',
      '导线采用项目JL/G1A-400/50外径27.6mm，以独立300m跨、8m抛物线弧垂、20段映射荷载。这里验证节点力和方向，不包含索找形、绝缘子、导线振动、完整塔线耦合及附加响应。若接入显式导线单元，应把雨荷载施加在线节点，通过结构求解传到塔；不能再把同一跨度雨力等效加到挂点。',
      '雨滴竖直撞击水平导线仍有向下力；风沿线路方向时，水平雨力显著减弱，但竖向雨力不会自动消失。雨滴撞击不是永久附着质量，不能把单位时间降雨总量累加到线质量而不建立排水/附着平衡。','',
      '### 4.2 各项检查','',
      '|检查|状态|结果|准则|','|---|---|---|---|']
    for x in v['checks']:lines.append(f"|{x['name']}|{'通过' if x['passed'] else '未通过/未完成'}|{x['value']}|{x['criterion']}|")
    lines += ['',
      '泊松到达验证了平均动量通量与离散雨滴冲量一致。改变时间平均格dt会改变方差（理论上正比1/dt），这不是物理脉冲峰值收敛。高频接触力需要另有脉冲持续时间与形状；不从本图推导杆件局部高频损伤。','',
      '## 5. 接入OpenSees时程的具体方式','',
      '1. 冻结已平衡重力，保持原质量定义；确定每个塔段/导线段的风速与雨强时间序列。',
      '2. 每个时刻由R(t)生成N(D,t)，由雨滴轨迹模型或有依据的γ(D,z,t)得到速度；如果考虑结构运动，用雨滴与结构的相对速度。',
      '3. 积分得到每段雨力并转全局XYZ分量，守恒映射到节点；跨度只选显式导线或挂点等效的一种表示。',
      '4. 不能默认一个标量Path驱动所有节点：若荷载空间形状随雨速/雨强/风向变化，应按节点/方向或空间一致分组输出多个Path序列。所有Path时间轴、首值和重力冻结时刻要一致。',
      '5. 干风、雨冲击及湿态气动变化分别建账；检查气动系数是否含雨冲击，避免重复。运行Transient并保存状态、支反力和输入输出能量，先做零雨回归与步长/空间离散收敛。',
      '以上为接入方法；本轮仅执行全塔静力接入与合成荷载时程，尚未实施全塔风雨Transient。','',
      '通用安装层已实现于`util/processing/nodal_loads.py`；独立节点/方向力时程用`apply_nodal_load_history`，静力或比例时程用`apply_nodal_loads`。接口验证与调用示例见[通用荷载接口说明](loading_interface.md)。独立弹簧动力验证不等同全塔风雨Transient。','',
      '## 6. 下一步优先补齐的证据','',
      '- 当地同步风速/风向/雨强及采样时长，优先至少有可靠的分段恒定雨强；有雨滴谱仪再拟合当地DSD。',
      '- 雨滴运动模型的高度剖面、初始/边界条件和直径相关速度比；用2018原文轨迹法核验，不能把本轮γ敏感性当标定。',
      '- 本型号导线/分裂数的干湿Cd、升力、水线与Re数据；先明确系数是否含雨滴冲击。',
      '- 塔杆真实角钢朝向、迎雨几何、遮挡与捕获效率。',
      '- 在上述输入可解释后，做同一风样本的无雨/有雨塔线时程配对、多随机种子、时间步/网格收敛；最后才讨论易损性面及联合风险。','',
      '## 7. 复现与文件','',
      '```bash',
      'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_rain_loading -v',
      '# 每次选新的输出目录；tower_check拒绝覆盖已有状态证据',
      '.venv/bin/python -m rain_loading.tower_check --output rain_loading/results/runs/angle_0 --angle 0',
      '.venv/bin/python -m rain_loading.tower_check --output rain_loading/results/runs/angle_45 --angle 45',
      '.venv/bin/python -m rain_loading.tower_check --output rain_loading/results/runs/angle_90 --angle 90',
      'OPENBLAS_NUM_THREADS=1 .venv/bin/python -m rain_loading.study',
      '```','',
      '`verification.json`含积分/截断、随机统计、各模型映射和实际全塔结果。CSV使用UTF-8 BOM便于Excel读取；网页报告按UTF-8响应。原始S2K哈希及OpenSees版本随每个全塔算例记录。',
      '此次只新增rain_loading实验模块和网页入口，未将该雨模型默认注入原风荷载分析。','',
      '## 8. 文献与详细调查','',
      '[文献调查、原式页码及适用边界](../../literature/rain_loading_investigation_20261102/README.md)','']
    lines += [f"- [{x['title']}]({x['url']})：{x['note']}" for x in SOURCES]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
