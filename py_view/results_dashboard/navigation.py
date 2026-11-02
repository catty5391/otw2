"""Small server-rendered module directory. Result artifacts keep their URLs."""
from html import escape
from pathlib import Path
import re


# title, description, destination; all destinations are fixed project routes.
GROUPS = {
    'materials': ('材料研究', '单杆本构、分段参考、参数识别与试验核查。', (
        ('四分段初始缺陷：空间验证', '实际塔杆的完整材料参数、分段与截面网格、缺陷方向及幅值对比。', '/segmented-validation/results/index.html'),
        ('Steel02 四分段与 TMQ', '统一参数的单调、完整往复、网格和缺陷对照。', '/steel02-tmq/results/index.html'),
        ('刘俊才角钢曲线本构', '解析曲线、真实分支拟合与单杆往复试验。', '/liu-phm/results/index.html'),
        ('Tian–Ma–Qu 单杆滞回', '三组参数的完整加载历史、曲线回放和数值检查。', '/tmq/results/index.html'),
        ('新材料开发与参数说明', '实现流程、公式、参数缺口及确定方法。', '/tmq/followup_results/development_notes_20261028/index.html'),
        ('Carden 真实回线拟合', 'P 条件标定、Q 诊断与完整历史误差。', '/tmq/followup_results/carden_conditional_20261026/index.html'),
        ('Carden 偏左与符号审计', '核对原图坐标、零点与恢复支历史规则。', '/tmq/followup_results/carden_sign_audit_20261028/index.html'),
        ('有序试验记录', '单角钢原始证据、加载顺序与分组识别条件。', '/tmq/followup_results/ordered_history_20261026/index.html'),
        ('参数文献与遗传算法', '参数来源、首峰特征和拟合算法检查。', '/tmq/followup_results/parameter_identification_20261026/index.html'),
        ('旧版等效材料标定', '骨架重构、峰前卸载与代表杆长对照。', '/modules/member/'),
    )),
    'tower': ('单塔分析', '全塔往复、薄弱位置、关键杆诊断与试验记录。', (
        ('全塔位移控制推覆', 'Steel01、Steel02 四分段与 TMQ：四风角曲线、屈服观察和首次停止位置。', '/tower-pushover/results/index.html'),
        ('TMQ 全塔往复', '新材料全塔曲线、压屈杆件和逐步结果。', '/tmq/tower_results/index.html'),
        ('薄弱位置分析', '参照罗贤超方法的杆件位置与节间变形筛查。', '/tmq/weakness_results/index.html'),
        ('旧版全塔往复对照', '等效模型与四分段参考的整体反力及共同目标。', '/modules/cyclic/'),
        ('收敛与关键杆诊断', '三个历史查因案例、轴力与应变全过程。', '/modules/diagnostics/'),
        ('试验记录与质量状态', '计算覆盖、适用域及独立验证状态。', '/modules/followup/'),
    )),
    'tower-line': ('塔线体系', '导线模态、离散网格、频率响应和绝缘子行为。', (
        ('加导线后的模态', '振型动画、频率匹配与塔身质量参与。', '/tmq/modal_results/index.html'),
        ('网格与频率响应', '导线网格敏感性、静力和频率响应结果。', '/tmq/followup_results/B2_20261024/index.html'),
        ('模态截断与阻尼诊断', '成组模态、风荷载投影和阻尼审计。', '/tmq/followup_results/B1_20261024/index.html'),
        ('V 形绝缘子敏感性', '受压、松弛与不同绝缘子模型对照。', '/tmq/followup_results/insulator_sensitivity_20261024/index.html'),
    )),
    'wind': ('风荷载对比', '单塔与塔线分别比较新旧方案、风攻角和风速。', (
        ('单塔：新旧材料与风攻角', 'Steel02 四分段和 TMQ 在四个风角下的响应。', '/tmq/followup_results/single_tower_wind_comparison_20261028/index.html'),
        ('塔线：新旧材料与风攻角', '塔身位移、挂点、索力与共同完成范围。', '/tmq/followup_results/tower_line_wind_comparison_20261028/index.html'),
        ('多风角施加载荷方法', '单塔与一塔四档的风荷载分配和小循环验证。', '/tmq/directional_results_v2/index.html'),
        ('极限风速探索', '单调增风、首次压屈及数值停止位置复核。', '/tmq/wind_speed_results/index.html'),
    )),
}
PAGES = {
    'rain': ('雨谱与风雨荷载', 'rain'),
    'member': ('旧版等效材料标定', 'materials'),
    'cyclic': ('旧版全塔往复', 'tower'),
    'diagnostics': ('收敛与关键杆诊断', 'tower'),
    'followup': ('试验记录与质量状态', 'tower'),
    'forces': ('内力探索', 'forces'),
    'resources': ('报告与文献', 'resources'),
    'archive': ('既有计算成果', 'archive'),
}
NAVIGATION = [('home','成果首页'),('materials','材料研究'),('tower','单塔分析'),
              ('tower-line','塔线体系'),('wind','风荷载对比'),('rain','雨谱与风雨荷载'),('forces','内力探索'),
              ('resources','报告与文献'),('archive','既有成果')]
LEGACY_HASHES = {'overview':'/', 'tianmaqu':'/modules/materials/', 'member':'/modules/member/',
                 'cyclic':'/modules/cyclic/', 'forces':'/modules/forces/', 'resources':'/modules/resources/'}


def cards(items, *, extra_class=''):
    return '<div class="module-grid '+extra_class+'">'+''.join(
        f'<a class="module-card" href="{escape(url,quote=True)}"><span class="module-card-number">{i:02d}</span>'
        f'<h3>{escape(title)}</h3><p>{escape(description)}</p><span class="module-card-action">进入模块 <b aria-hidden="true">→</b></span></a>'
        for i,(title,description,url) in enumerate(items,1))+'</div>'


def group_content(key):
    title,description,items=GROUPS[key]
    note=''
    if key=='materials':
        note='<p class="catalog-note">新材料仍处于条件验证阶段；每个模块分别列明公式、数据来源和适用边界。</p>'
    return (f'<section class="section module-directory"><div class="section-heading"><div><div class="section-index">MODULE DIRECTORY / {len(items):02d}</div>'
            f'<h1>{escape(title)}</h1></div><p>{escape(description)}</p></div>{note}{cards(items)}</section>')


def home_content(root):
    content=(root/'index.html').read_text(encoding='utf-8')
    items=[(v[0],v[1],f'/modules/{key}/') for key,v in GROUPS.items()]
    rain=('雨谱与风雨荷载','雨滴粒径、雨强时程、塔身与导线荷载的来源及数值验证。','/rain-loading/')
    items += [rain, ('内力探索','按模型、分量和时间段查看全塔内力分布。','/modules/forces/'),
              ('报告与文献','查看方法说明、计算报告和本地论文。','/modules/resources/'),
              ('既有计算成果','查看初缺陷模型、推覆、找形和历史图表。','/modules/archive/')]
    recent=[rain,GROUPS['tower'][2][0],GROUPS['materials'][2][0]]
    return content.replace('{{categories}}',cards(items)).replace('{{recent}}',cards(recent,extra_class='recent-grid'))


def render_page(root: Path, key: str) -> str:
    if key=='home': title='成果首页';active='home';body=home_content(root)
    elif key in GROUPS: title=GROUPS[key][0];active=key;body=group_content(key)
    elif key in PAGES:
        title,active=PAGES[key];body=(root/'pages'/f'{key}.html').read_text(encoding='utf-8')
    else: raise KeyError(key)
    links=''.join(f'<a class="nav-link{" active" if name==active else ""}" href="{url}"'
                  f'{" aria-current=\"page\"" if name==active else ""}><span>{i:02d}</span>{escape(label)}</a>'
                  for i,(name,label) in enumerate(NAVIGATION,1)
                  for url in ['/' if name=='home' else f'/modules/{name}/'])
    breadcrumb='<a href="/">成果首页</a>'
    if active!='home':
        if key!=active:breadcrumb+=f'<span>/</span><a href="/modules/{active}/">{dict(NAVIGATION)[active]}</a>'
        breadcrumb+=f'<span>/</span><b>{escape(title)}</b>'
    template=(root/'layout.html').read_text(encoding='utf-8')
    values={'title':escape(title),'page':key,'navigation':links,'breadcrumb':breadcrumb,'body':body,
            'application': ('<script src="/static/rain.js?v=20261102" defer></script>' if key=='rain' else
                            '<script src="/static/app.js?v=modules-20261028" defer></script>' if key in PAGES and key!='archive' else '')}
    for name,value in values.items():template=template.replace('{{'+name+'}}',value)
    return template


def add_detail_navigation(document: str, url: str) -> str:
    """A consistent return path on existing result pages without changing files."""
    category=next((key for key,(_,_,items) in GROUPS.items() if any(url==item[2] for item in items)),None)
    if category is None: return document
    bar=(f'<div class="otw2-module-navigation" style="position:relative;z-index:30;display:flex;flex-wrap:wrap;gap:20px;'
         f'padding:12px 20px;background:#071725;color:#eef8fa;font:14px/1.5 system-ui,sans-serif;border-bottom:1px solid #34505e">'
         f'<a href="/" style="color:inherit;text-decoration:none">← 成果首页</a>'
         f'<a href="/modules/{category}/" style="color:#67ddd3;text-decoration:none">{GROUPS[category][0]}目录</a></div>')
    if re.search(r'<body\b[^>]*>',document,re.I):
        return re.sub(r'(<body\b[^>]*>)',lambda m:m.group(1)+bar,document,count=1,flags=re.I)
    if re.search(r'<main\b',document,re.I):
        return re.sub(r'(<main\b)',lambda m:bar+m.group(1),document,count=1,flags=re.I)
    return re.sub(r'(<h1\b)',lambda m:bar+m.group(1),document,count=1,flags=re.I)
