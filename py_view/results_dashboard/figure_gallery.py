"""Read-only catalogue of the locally regenerated scientific figure exports."""
from html import escape
from pathlib import Path

RELATIVE_ROOT='artifacts/figure_refactor_20261106'
GROUPS={
 'tower':('全塔位移控制推覆',('capacity','alongwind_capacity','member_events','story_drift','stiffness')),
 'steel02':('四分段 Steel02 与 TMQ',('monotonic','hysteresis','mesh_and_step','imperfection','mechanism','convergence','loading_and_geometry','forcebeam_hysteresis')),
 'liu':('曲线型角钢 PHM',('full_hysteresis','branch_fits','literature_envelopes','observed_diagnostics')),
 'tmq':('TMQ 完整滞回与机制',('full_hysteresis','loading_history','mechanism_checks')),
 'single_wind':('单塔静风对比',('displacement_comparison','difference_comparison','force_displacement_comparison')),
 'tower_line':('塔线静风对比',('control_displacement','tower_base_shear','hanger_displacement','cable_tension','v_string_force','pushover_curve')),
 'rain':('雨谱与风雨荷载',('drop_spectrum','rain_flux_closure','load_sensitivity','synthetic_history','load_power_spectrum','poisson_verification','tower_line_loads','tower_response')),
}

def artifact(project_root,relative):
    parts=relative.split('/')
    if len(parts)!=2:return None
    group,name=parts;path=Path(name)
    if group not in GROUPS or path.stem not in GROUPS[group][1] or path.suffix not in {'.png','.svg','.pdf'}:return None
    root=(Path(project_root)/RELATIVE_ROOT).resolve();target=(root/group/name).resolve()
    return target if target.is_relative_to(root) and target.is_file() else None


def render(project_root):
    groups=[];count=0
    for group,(title,names) in GROUPS.items():
        cards=[]
        for name in names:
            if artifact(project_root,f'{group}/{name}.png') is None:continue
            url=f'/scientific-figures/{group}/{name}'
            cards.append(f'<figure><a href="{url}.png"><img loading="lazy" src="{url}.png" alt="{escape(title)} — {name}"></a>'
                f'<figcaption>{escape(title)} · {name}<nav><a href="{url}.png">PNG</a> · <a href="{url}.pdf">PDF</a> · <a href="{url}.svg">SVG</a></nav></figcaption></figure>')
        count+=len(cards)
        groups.append(f'<section id="{group}"><h2>{title}</h2><div class="grid">'+''.join(cards or ['<p>本地尚未生成本组图表。</p>'])+'</div></section>')
    nav=' · '.join(f'<a href="#{key}">{value[0]}</a>' for key,value in GROUPS.items())
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<title>科研图表 · 统一重绘</title><style>body{margin:0;background:#f2f5f7;color:#20323e;font:16px/1.7 system-ui,sans-serif}main{max-width:1320px;margin:auto;padding:24px}a{color:#006a94}header{background:white;padding:24px;border-radius:12px}h1{margin:8px 0}h2{margin-top:36px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}figure{margin:0;background:white;border-radius:10px;padding:16px}img{width:100%;height:auto;display:block}figcaption{overflow-wrap:anywhere;margin-top:12px}nav{margin-top:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}main{padding:12px}}</style>'
      f'<main><header><a href="/">← 成果首页</a><h1>科研图表 · 统一重绘</h1><p>{count} 幅图，保留已保存的曲线、计算停止点及适用范围。PNG 用于浏览，PDF/SVG 用于排版与编辑。</p>'
      f'<p>本次只调整图形表达，数值结果与物理验证状态不变。历史模态、三维视图及本页未列图表沿用既有版本。</p><nav>{nav}</nav></header>'+''.join(groups)+'</main></html>')
