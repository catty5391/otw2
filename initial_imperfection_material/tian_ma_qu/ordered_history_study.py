"""Acquire and audit public RESSLab angle histories without inventing chronology.

Downloaded CSV row order is preserved byte-for-byte. Curator digitization is
not an instrument time history. Missing coupon/initial-state evidence blocks
physical fitting; this command publishes observations and an admission audit.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import urllib.request

import numpy as np

from .parameter_identification import ROOT, write_json, write_csv

API = "https://resslab-hub.epfl.ch/api"
DATABASE = "https://resslab-hub.epfl.ch/braces/database"
PAPER = "https://www.iitk.ac.in/nicee/wcee/article/WCEE2012_4366.pdf"
THESIS = "https://deepblue.lib.umich.edu/handle/2027.42/127507"
DEFAULT_SOURCE = ROOT/"literature/tmq_ordered_history_20261026"
DEFAULT_OUTPUT = Path(__file__).parent/"followup_results/ordered_history_20261026"


def read_curve(payload):
    """Preserve source order, duplicates, offsets and physical units."""
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    if not rows or rows[0] != ["Displacement [mm]", "Force [kN]"]:
        raise ValueError("Unexpected source units/CSV schema")
    values = np.asarray([[float(x) for x in row] for row in rows[1:] if row], float)
    if values.ndim != 2 or values.shape[1] != 2 or len(values) < 3 or not np.isfinite(values).all():
        raise ValueError("Invalid source curve")
    return values


def candidate_group(row):
    """Catalog grouping only: this does not verify connection equivalence."""
    return (row["cross_section_size"], row["l_b"], row["area"], row["fy_m"],
            row["e"], row["boundary_condition"], row["steel"])


def audit_specimen(row, payload=None):
    checks = {
        "E": "200 GPa is a database value; coupon measurement not verified",
        "fy": "fy_m is labelled measured in the database; original coupon table not checked",
        "geometry": "catalog geometry; original dimensions and displacement gauge length not checked",
        "boundary": "Gusset plate alone does not specify rotational restraint or connection details",
        "order": "curator CSV row order retained; not independently matched to original cycle numbering",
        "initial_state": "virgin zero-load state / any earlier loading not verified",
        "phases": "no source-reviewed phase boundaries yet",
        "displacement": "brace versus machine/gusset deformation not verified",
    }
    result = {"specimen_id": row["id"], "section": row["cross_section_size"],
        "length_mm": row["l_b"], "area_mm2": row["area"], "database_E_MPa": row["e"],
        "database_fy_m_MPa": row["fy_m"], "boundary_catalog": row["boundary_condition"],
        "database_kl_r": row["kl_r"], "database_k_assumed": row["k_assumed"],
        "database_protocol": row["loading_protocol"], "source": THESIS,
        "curve_available": payload is not None, "strict_fit_admitted": False,
        "missing_evidence": checks, "fitted_parameters": None}
    ideal_area = row["t_br"]*(row["b_br"]+row["d_br"]-row["t_br"])
    discrepancy = row["area"]/ideal_area-1
    result["sharp_corner_area_mm2"] = ideal_area
    result["catalog_to_sharp_corner_area_difference_ratio"] = discrepancy
    result["geometry_review_flag"] = abs(discrepancy) > .1
    if payload is None:
        result["missing_evidence"]["history"] = "Database reports no displacement history"
        return result
    curve = read_curve(payload)
    result.update({"point_count": len(curve), "source_sha256": hashlib.sha256(payload).hexdigest(),
        "first_displacement_mm": float(curve[0, 0]), "first_force_kN": float(curve[0, 1]),
        "displacement_min_mm": float(curve[:, 0].min()), "displacement_max_mm": float(curve[:, 0].max()),
        "whole_record_min_force_kN": float(curve[:, 1].min()), "whole_record_max_force_kN": float(curve[:, 1].max()),
        "force_extrema_are_not_first_buckling_features": True, "normalization_applied": False,
        "sort_applied": False, "time_available": False})
    return result


def acquire(source):
    """Public anonymous endpoints only; cache files are never overwritten."""
    source.mkdir(parents=True, exist_ok=True)
    raw = source/"raw"
    raw.mkdir(exist_ok=True)
    downloads = []
    def fetch(name, url):
        path = raw/name
        if not path.exists():
            content = urllib.request.urlopen(url, timeout=40).read()
            # Save only complete responses; a failed transfer leaves no cached file.
            with path.open("xb") as stream:
                stream.write(content)
        content = path.read_bytes()
        downloads.append({"file": f"raw/{name}", "url": url, "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "cache_checked_utc": datetime.now(timezone.utc).isoformat()})
        return content
    catalog = json.loads(fetch("braces.json", API+"/braces?size=500&page=1"))
    if len(catalog["items"]) != catalog["total"]:
        raise ValueError("Incomplete catalog pagination; do not publish a partial count")
    rows = [r for r in catalog["items"] if r["cross_section_shape"] == "Angle"]
    # Sorting specimen metadata for presentation is safe; curve samples are never sorted.
    rows.sort(key=lambda r: r["id"])
    curves = {}
    for row in rows:
        if row["displacement_count"]:
            if row["displacement_count"] != 1:
                raise ValueError("Multiple histories require explicit source-series selection")
            curves[row["id"]] = fetch(row["id"]+".csv", API+f"/braces/{row['id']}/displacement/csv")
            read_curve(curves[row["id"]])
    write_json(source/"download_manifest.json", {"source": DATABASE, "total_catalog_records": catalog["total"],
        "records": downloads, "raw_data_policy": "local only; preserve downloaded bytes"})
    return rows, curves


def publish(source=DEFAULT_SOURCE, output=DEFAULT_OUTPUT):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    rows, curves = acquire(source)
    audits = [audit_specimen(row, curves.get(row["id"])) for row in rows]
    groups = {}
    for row in rows:
        key = candidate_group(row)
        if key not in groups:
            groups[key] = {"group_id": f"G{len(groups)+1:02d}", "specimens": [], "catalog_signature": list(key),
                "status": "catalog_candidate_only", "training_specimens": [], "holdout_specimens": [],
                "shared_parameters_allowed": False}
        groups[key]["specimens"].append(row["id"])
    for row, audit in zip(rows, audits):
        audit["group_id"] = groups[candidate_group(row)]["group_id"]
    output.mkdir(parents=True)
    summary = {"schema": "otw2.tmq_ordered_history_audit.v1", "date": "2026-10-26",
        "database_source": DATABASE, "database_methods_source": PAPER,
        "catalog_count": len(rows), "curve_count": len(curves), "group_count": len(groups),
        "point_count": sum(a.get("point_count", 0) for a in audits),
        "strict_fit_admitted_count": 0, "real_history_fit_executed": False,
        "physical_validation": "pending_source_and_initial_state_verification",
        "production_parameters_changed": False, "new_full_tower_runs": 0,
        "observations": "curated experimental digitization, original row order; no physical timestamps",
        "specimens": audits, "groups": list(groups.values()),
        "stage_plan": [
            {"stage": "first_compression", "candidate_coefficients": ["phi", "alpha", "beta", "gamma"],
             "required": "virgin compression-first peak and both descending branches; freeze E/fy/A/L"},
            {"stage": "unload_reload", "candidate_coefficients": ["tau", "mu", "nu", "zeta", "rho"],
             "required": "reviewed reversal, pinching and tension recovery; rho only with tensile plastic branch"},
            {"stage": "subsequent_compression", "candidate_coefficients": ["eta", "theta", "kappa"],
             "required": "complete second/later buckling with all prior loading retained"}],
        "next_evidence": ["Jain 1978 coupon E/fy and geometry/connection/gauge tables",
                          "Original cycle numbering and specimen loading/preloading protocol",
                          "Documented initial state or justified instrument/scan zero correction",
                          "Reviewed phase map, digitization uncertainty and frozen training/holdout split"]}
    write_json(output/"summary.json", summary)
    fields = ("specimen_id", "group_id", "section", "length_mm", "area_mm2", "database_E_MPa",
        "database_fy_m_MPa", "curve_available", "strict_fit_admitted", "point_count",
        "first_displacement_mm", "first_force_kN", "geometry_review_flag")
    write_csv(output/"specimen_audit.csv", [{k: a.get(k) for k in fields} for a in audits])
    payload = {"units": {"displacement": "mm", "force": "kN"}, "axis": "source_row_index_not_time",
        "curves": [{"id": key, "samples": read_curve(value).tolist()} for key, value in curves.items()]}
    write_json(output/"curves.json", payload)
    plot_groups(output, groups, curves)
    table = "\n".join(f"| {a['specimen_id']} | {a['group_id']} | {a['length_mm']:.0f} | {a['area_mm2']:g} | {a['database_fy_m_MPa']:g} | {a.get('point_count', 0)} | {a.get('first_displacement_mm', '—')} | {a.get('first_force_kN', '—')} |" for a in audits)
    report = f'''# 单角钢有序历史候选数据与分组识别准入

2026-10-26。已取得 {len(curves)} 条真实试验的数据库数字化记录，共 {summary['point_count']} 点；按数据库几何和边界标签整理为 {len(groups)} 个候选组。严格识别准入为 0 件，本轮没有执行真实试验参数拟合。

## 1. 本次实施步骤与实际结果

1. 检索 [EPFL RESSLab 公开数据库]({DATABASE})，读取匿名 API 元数据和单角钢 CSV；保存下载地址、完整原文件和 SHA-256。全库本次为 294 件，单角钢 8 件，Jain_1L 没有曲线。
2. 按截面、杆长、面积、数据库 E/fy、连接标签和钢材分组。G01：1L/5L；G02：2L/6L；G03：3L/7L；G04：4L/8L。它们只是待审查的几何组，不表示连接细节、加载顺序及系数可以共享；尚未指定训练/留出试件。
3. CSV 每一行原样保留；不按位移排序、不补造时间、不合并重复位移、不自动移零、不补原点、不删除起始非零数据。网页展示原始行序与完整曲线，未将它称作仪器原始时程。
4. 对实测参数、连接、位移定义、前序加载和相位划分设置准入条件。当前均缺少原报告逐项核对，因此没有输出貌似确定的循环参数。
5. 实现可复用的三阶段识别器：固定实测 E/fy/A/L；先首压峰与下降段，再卸载—再加载，最后后续压屈。每次评价都从已确认初态重放完整历史，只在目标支路计算误差。各阶段冻结先前参数，留出试件不参与优化。

## 2. 取得的数据

数据源为 Jain (1978) 博士论文的数据库数字化副本。[原论文入口]({THESIS})本次返回 HTTP 403，未取得正文。[数据库作者 2012 方法论文]({PAPER})第 2 节说明多数结果从原试验报告数字化，包含轴力—位移历史。本文仍将单条 CSV 的原始循环对应关系列为待核验，不根据图形交叉点猜时序。

| 试件 | 候选组 | 数据库 L/mm | A/mm² | fy_m/MPa | 点数 | 首点 u/mm | 首点 F/kN |
|---|---|---:|---:|---:|---:|---:|---:|
{table}

所有数据库 E 都为 200000 MPa；数据库没有给出这些 E 的券样测定依据，不能改写为“实测 200 GPa”。fy_m 是数据库标注的实测屈服强度，仍需原始券样表确认。

特别注意：Jain_7L 首点已有约 17.84 kN 拉力，不能直接以无应力材料起算；其它试件也有不同程度起点偏移。偏移究竟来自扫描误差、仪器零点还是缺失前序加载，当前未知。Jain_3L/7L 名义 L37.7×37.7×3.18 的尖角面积约 229.66 mm²，与数据库 273 mm² 相差约 18.9%，这只是复核提示，不是已证明数据库错误，也不能自行替换。数据库 K=0.7 是 assumed 字段，不是实测约束。

当前各记录的最大/最小轴力仅作为完整记录范围展示，不能自动代替首次压屈峰。相同几何组的曲线差异也可能包含加载前史和连接差异，应先查证后决定是否合并。

## 3. 识别方案及执行接口

| 阶段 | 候选参数 | 必需证据 / 停止条件 |
|---|---|---|
| 固定物理量 | E、fy、A、L，不进入优化 | 实测券样 E/fy，核对几何、位移量测区间、端部约束及初态 |
| 首压 | φ、α、β；γ 只在转折可分辨时加入 | 先压且无前序塑性；解析到内部峰值和连续下降支；只有弹性段拒绝识别 |
| 卸载再加载 | τ、μ、ν；ζ、ρ 仅在相应段覆盖时加入 | 保留之前的加载，跨过捏拢与恢复段；ρ 需要拉伸屈服后数据 |
| 后续压屈 | η、θ、κ | 至少第二次压屈及下降支，包含完整前序历史 |
| 检验 | 不调参 | 冻结训练/留出划分；完整滞回叠图、峰值/刚度/残余量和局部可辨识性；失配不能用优化误差小掩盖 |

`grouped_identification.py` 在现有严格有序数据格式之上要求 `verification` 中 E、fy、geometry、boundary、displacement、initial_state、order、phases、group 均有 verified 和 source_reference；E/fy 的 basis 必须是 measured_coupon。加载顺序依据只接受仪器序列、作者序列或已对照原文的数据库序列。`samples[].phase` 明确支路，不能由无序点自动生成。

一个组当前要求 E/fy/A/L 一致且已确认同类边界，避免把不同杆长共同识别为同一 φ。模板未识别系数仍是先验，报告应列清其来源；局部 Jacobian 满秩只说明局部数值敏感，不等于全局唯一或物理有效。组内留出也不证明能迁移到本塔。

复算数据审计：

```sh
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.ordered_history_study --output /tmp/tmq-history-audit-new
```

取得并核对输入后运行（输入格式详见模块 README）：

```sh
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.grouped_identification reviewed_plan.json --output /tmp/tmq-group-fit-new
```

输出目录不可覆盖。下载的数据/PDF、曲线 JSON、图像和拟合原始输出保留本地；方法、测试和本报告可以版本管理。

## 4. 当前限制与下一项可执行工作

本轮推进到“真实试验候选记录已取得、完整展示、分组完成、准入检查与分阶段工具已实现”。尚未达到“取得经原文确认的零初态有序历史及实测 E 后完成参数识别”。下一项依赖是 Jain 原文的券样与试件表、循环编号/加载协议、位移测量定义；若用户已有满足条件的试验 CSV，可直接走同一接口。不得把本轮曲线展示当成新材料拟合成功，也没有据此更新全塔材料。
'''
    (output/"REPORT.md").write_text(report)
    publish_page(output, summary)
    print(json.dumps({k: summary[k] for k in ("curve_count", "point_count", "group_count", "strict_fit_admitted_count")}))
    return summary


def plot_groups(output, groups, curves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for axis, group in zip(axes.flat, groups.values()):
        for specimen in group["specimens"]:
            if specimen in curves:
                xy = read_curve(curves[specimen])
                line, = axis.plot(xy[:, 0], xy[:, 1], linewidth=.85, alpha=.85, label=specimen)
                axis.scatter(*xy[0], s=30, color=line.get_color(), marker="s", zorder=4)
        axis.set(title=f"{group['group_id']}: {', '.join(group['specimens'])}",
                 xlabel="Source displacement (mm)", ylabel="Source axial force (kN)")
        axis.grid(alpha=.2); axis.legend(fontsize=8)
    fig.suptitle("Jain angle tests | RESSLab curated digitization\nOriginal CSV order; square = first sample; no fitted material")
    fig.tight_layout()
    for ext in ("png", "svg", "pdf"):
        fig.savefig(output/f"grouped_observations.{ext}", dpi=170, bbox_inches="tight")
    plt.close(fig)


def publish_page(output, summary):
    table = "".join(f"<tr><td>{html.escape(a['specimen_id'])}</td><td>{a['group_id']}</td><td>{a.get('point_count', 0)}</td><td>{a['length_mm']:g}</td><td>{a['database_fy_m_MPa']:g}</td><td>待核对原文与初态</td></tr>" for a in summary["specimens"])
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>单角钢真实记录与分组识别</title>
<style>body{margin:0;background:#eef2f6;color:#172d40;font:16px/1.7 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:24px}section{background:white;border-radius:16px;padding:22px;margin:20px 0}h1{line-height:1.3}a{color:#145da0}.note{border-left:4px solid #b67014;padding:12px;background:#fff6e7}img{width:100%}canvas{display:block;width:100%;height:360px;background:#f8fafc}input{width:100%}select{font-size:16px;padding:6px}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{padding:8px;border-bottom:1px solid #dde3e9;text-align:left}.scroll{overflow:auto}#point{font-variant-numeric:tabular-nums}footer{font-size:14px;color:#526573}@media(max-width:600px){main{padding:12px}section{padding:14px}canvas{height:300px}}</style>
<main><a href="/">← 成果主页</a><h1>单角钢真实记录与分组识别</h1><p>7 条公开试验数字化记录 · 4 个候选几何组 · 严格拟合准入 0 件</p>
<p class="note">目前展示的是数据库保存的试验曲线，没有进行材料拟合。E 的实测依据、起始状态和原始循环顺序仍待核对；本塔材料参数未更新。</p>
<section><h2>逐点查看数据库原始行序</h2><p>横坐标为端部位移，纵坐标为轴力，拉力为正。灰线显示完整记录，蓝线显示选定行之前的记录。行号没有物理时间含义。</p><label>试件 <select id="specimen"></select></label><canvas id="plot" aria-label="试验力位移曲线"></canvas><label for="sequence">原始记录行号</label><input id="sequence" type="range" min="0" value="0" step="1"><p id="point" aria-live="polite">正在读取本地数据…</p></section>
<section><h2>候选组完整曲线</h2><p>方块标出 CSV 首点；未移零、未补原点、未按位移排序。同组不意味着可以直接共享参数。</p><a href="grouped_observations.pdf"><img src="grouped_observations.svg" alt="四个候选组的完整力位移曲线"></a></section>
<section><h2>试件资料</h2><p>下表 fy 为数据库 fy_m 字段，E 统一记录为 200 GPa；原始券样表仍待核对。1L 无曲线，7L 首点已有约 17.84 kN 拉力。3L/7L 的面积与名义尺寸需要复核。</p><div class="scroll"><table><thead><tr><th>试件</th><th>候选组</th><th>点数</th><th>L/mm</th><th>fy_m/MPa</th><th>识别状态</th></tr></thead><tbody>TABLE</tbody></table></div></section>
<section><h2>识别顺序与交付</h2><p>固定实测 E、fy 和几何 → 首压峰及下降支 → 卸载与再加载 → 后续压屈 → 留出试件检验。每次都重放完整前史；仅有弹性段的记录不能识别屈曲后系数。</p><p><a href="REPORT.md">详细步骤、结果与待补证据</a> · <a href="summary.json">机器可读审计</a> · <a href="specimen_audit.csv">试件表</a> · <a href="verification.json">测试结果</a></p><p><a href="https://resslab-hub.epfl.ch/braces/database">EPFL 数据库</a> · <a href="https://www.iitk.ac.in/nicee/wcee/article/WCEE2012_4366.pdf">数据库方法论文</a></p></section>
<footer>数据和图形保留在本地。当前没有真实试验拟合结果，也没有完成全塔材料验证。</footer></main>
<script>
const select=document.querySelector('#specimen'),slider=document.querySelector('#sequence'),canvas=document.querySelector('#plot'),label=document.querySelector('#point');let curves=[];
function draw(){if(!curves.length)return;const curve=curves[Number(select.value)],a=curve.samples,k=Number(slider.value),w=canvas.clientWidth,h=canvas.clientHeight,dpr=window.devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);const xs=a.map(p=>p[0]),ys=a.map(p=>p[1]),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),X=x=>55+(x-xmin)/(xmax-xmin)*(w-80),Y=y=>h-42-(y-ymin)/(ymax-ymin)*(h-70);c.font='12px sans-serif';c.strokeStyle='#d3dce6';c.fillStyle='#536677';for(let j=0;j<=4;j++){let x=xmin+(xmax-xmin)*j/4,y=ymin+(ymax-ymin)*j/4;c.beginPath();c.moveTo(X(x),25);c.lineTo(X(x),h-42);c.moveTo(55,Y(y));c.lineTo(w-25,Y(y));c.stroke();c.fillText(x.toFixed(1),X(x)-10,h-22);c.fillText(y.toFixed(1),5,Y(y)+4)}c.fillText('F (kN)',5,15);c.fillText('u (mm)',w-55,h-5);function line(n,color){c.strokeStyle=color;c.lineWidth=1.3;c.beginPath();for(let i=0;i<=n;i++){if(i===0)c.moveTo(X(a[i][0]),Y(a[i][1]));else c.lineTo(X(a[i][0]),Y(a[i][1]))}c.stroke()}line(a.length-1,'#c6d0d9');line(k,'#1675ac');c.fillStyle='#c04f28';c.beginPath();c.arc(X(a[k][0]),Y(a[k][1]),4,0,2*Math.PI);c.fill();label.textContent=`${curve.id} · 原始行 ${k+1} / ${a.length} · u = ${a[k][0].toFixed(4)} mm · F = ${a[k][1].toFixed(4)} kN`;}
function change(){slider.max=curves[Number(select.value)].samples.length-1;slider.value=0;draw()}select.addEventListener('change',change);slider.addEventListener('input',draw);window.addEventListener('resize',draw);fetch('curves.json').then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}).then(d=>{curves=d.curves;curves.forEach((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=v.id;select.append(o)});change()}).catch(e=>{label.textContent='数据加载失败：'+e.message});
</script></html>'''
    (output/"index.html").write_text(page.replace("TABLE", table))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    publish(args.source, args.output)


if __name__ == "__main__":
    main()
