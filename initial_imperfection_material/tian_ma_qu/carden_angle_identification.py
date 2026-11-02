"""Conditional capacity-ratio identification from published single-angle tests.

Uses the directly reported coupon-based yield force, avoiding an invented split
into measured A and fy. This is scalar feature identification, not a loop fit.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import math
from pathlib import Path

from .parameter_identification import Bound, genetic_minimize, write_csv, write_json

SOURCE = "https://ej.aisc.org/index.php/engj/article/download/875/874"
DOI = "https://doi.org/10.62913/engj.v43i2.875"
REVIEWED_PDF_SHA256 = "7c4e1e208e95ec5aa7ef932abccb3563ca6853f1eef493d9f6f5116e6a9a4205"


def published_features():
    # Table 1 (printed112/PDF2), Table4 (printed120/PDF10), visually checked.
    # Thin-angle thickness glyph is not reliably rendered in publisher PDF;
    # no thickness or area is inferred for this force-ratio calculation.
    peak = [15.9, 27.7, 20.4, 17.8, 29.9, 33.7, 33.9, 31.3, 30.5, 20.2, 20.8, 28.5, 28.7, 6.3, 4.6, 12., 10.7]
    length = [40.5]*5 + [22.5]*4 + [40.5]*2 + [22.5]*2 + [50.5]*2 + [25.4]*2
    slender = [119] + [83]*4 + [46]*4 + [83]*2 + [46]*2 + [181]*2 + [91]*2
    compression_first = set("ABEFGIJLNP")
    result = []
    for i, specimen in enumerate("ABCDEFGHIJKLMNOPQ"):
        result.append({"specimen_id": specimen, "source": SOURCE, "source_pages": "Table1 PDF2; Table4 PDF10 (1-based)",
                       "grade": "ASTM A36, three coupon batches", "cross_section_family": "single_equal_leg_angle",
                       "connection": ("bolted_reinforced" if specimen in "DEHI" else "bolted") if i < 9 else "balanced_welded",
                       "reported_net_to_gross_area_ratio": .93 if specimen in "DH" else .81 if specimen in "ABCFG" else 1.,
                       "gusset_plate_thickness_in": .5 if specimen == "A" else 1.,
                       "coupon_batch": 1 if i < 9 else 2 if i < 13 else 3,
                       "first_cycle": "compression" if specimen in compression_first else "tension",
                       "prior_tensile_yield_before_buckling": specimen in "CDFGHIMOQ",
                       "prior_yield_source": "Carden et al. 2008 MCEER-08-0002 Table3-4 footnote, printed p74 / PDF104",
                       "reported_length_in": length[i], "length_definition": "centroid-to-centroid connection distance; Table1 and printed118/121/124 discussion",
                       "reported_KL_over_r": slender[i], "reported_K": 1. if specimen == "A" else .7,
                       "coupon_yield_force_kip": 45.5 if i < 9 else 37.2 if i < 13 else 16.7,
                       "measured_buckling_capacity_kip": peak[i],
                       "force_basis": "coupon-based Ag*fy from Table4, not nominal 36ksi force or AISC expected strength"})
    return result


def fit_capacity(feature):
    if feature["first_cycle"] != "compression":
        raise ValueError("Tension-preloaded specimen cannot identify a virgin compression capacity")
    if feature.get("prior_tensile_yield_before_buckling"):
        raise ValueError("Initial compression direction does not guarantee virgin buckling: original report identifies prior tensile yield")
    y, p = float(feature["coupon_yield_force_kip"]), float(feature["measured_buckling_capacity_kip"])
    if not all(map(math.isfinite, (y, p))) or not 0 < p <= y:
        raise ValueError("Positive capacity below coupon-based yield force required")
    phi = p / y
    bound = Bound("phi", .01, 1.)
    ga = genetic_minimize(lambda g: ((bound.value(float(g[0]))*y-p)/p)**2, 1,
                          seed=17, population=20, generations=45, timeout_seconds=15.)
    # Table4 is rounded to 0.1kip: this interval quantifies display rounding ONLY.
    return {**feature, "conditional_phi": phi, "rounding_only_phi_interval": [(p-.05)/(y+.05), (p+.05)/(y-.05)],
            "ga_phi": bound.value(ga["genes"][0]), "ga_relative_capacity_error": math.sqrt(ga["objective"]),
            "ga": ga, "identification_scope": "one capacity ratio, conditional on mapping compression-first reported maximum to first buckling",
            "first_peak_mapping": "compression-first table selection; exact first-cycle point not independently digitized",
            "full_hysteresis_validated": False, "calibrated_to_Z30103A6": False}


def publish(output, source_pdf):
    source_pdf = Path(source_pdf)
    raw_pdf = source_pdf.read_bytes()
    if not raw_pdf.startswith(b"%PDF") or hashlib.sha256(raw_pdf).hexdigest() != REVIEWED_PDF_SHA256:
        raise ValueError("The reviewed original PDF is required; a different edition needs table/provenance review")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    features = published_features()
    cases = [fit_capacity(f) for f in features if f["first_cycle"] == "compression" and not f["prior_tensile_yield_before_buckling"]]
    excluded = [f["specimen_id"] for f in features if f["first_cycle"] == "tension"]
    summary = {"schema": "otw2.tmq_single_angle_capacity_identification.v1", "source": SOURCE, "doi": DOI,
               "source_pdf_sha256": hashlib.sha256(source_pdf.read_bytes()).hexdigest(), "source_pdf_bytes": source_pdf.stat().st_size,
               "published_specimens": len(features), "selected_compression_first": len(cases),
               "excluded_tension_first": excluded, "cases": cases, "data_kind": "published_experimental_scalar_features",
               "excluded_compression_first_with_prior_tensile_yield": ["F", "G", "I"],
               "conditional_phi_range": [min(c["conditional_phi"] for c in cases), max(c["conditional_phi"] for c in cases)],
               "full_hysteresis_validation": False, "production_parameters_changed": False,
               "single_angle_complete_parameter_set_determined": False, "new_FE_runs": 0,
               "unidentified": ["E", "rho", "alpha", "beta", "gamma", "tau", "mu", "nu", "zeta", "eta", "theta", "kappa"],
               "force_product_only": "A and fy are not separately identified; source directly reports their product as coupon yield force",
               "rounding_only_intervals_are_confidence_intervals": False}
    write_json(output / "summary.json", summary)
    write_json(output / "source_features.json", features)
    fields = ("specimen_id", "connection", "reported_net_to_gross_area_ratio", "gusset_plate_thickness_in", "coupon_batch", "reported_length_in", "reported_KL_over_r", "reported_K",
              "coupon_yield_force_kip", "measured_buckling_capacity_kip", "conditional_phi", "ga_phi", "ga_relative_capacity_error")
    write_csv(output / "conditional_phi.csv", [{k: c[k] for k in fields} for c in cases])

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    labels = [c["specimen_id"] for c in cases]
    axes[0].bar(labels, [c["conditional_phi"] for c in cases], color="#167d9a")
    axes[0].set(xlabel="Compression-first specimen", ylabel="Pcr / (coupon-based Ag fy)", ylim=(0, 1), title="Conditional phi from single-angle tests")
    for connection, marker in (("bolted", "o"), ("bolted_reinforced", "^"), ("balanced_welded", "s")):
        group = [c for c in cases if c["connection"] == connection]
        axes[1].scatter([c["reported_KL_over_r"] for c in group], [c["conditional_phi"] for c in group], marker=marker, label=connection)
    for c in cases:
        offset = {"F": (12, -15), "G": (12, -2), "L": (12, 12)}.get(c["specimen_id"], (4, 4))
        axes[1].annotate(c["specimen_id"], (c["reported_KL_over_r"], c["conditional_phi"]), xytext=offset, textcoords="offset points", fontsize=8)
    axes[1].set(xlabel="Reported effective slenderness K L / r", ylabel="Conditional phi", ylim=(0, 1), title="Different connections and coupon batches; no fitted universal law")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.grid(axis="y", alpha=.2)
    fig.suptitle("Carden et al. 2006 | 10 compression-first tests | scalar capacity evidence, not cyclic calibration")
    fig.tight_layout()
    for ext in ("svg", "png", "pdf"):
        fig.savefig(output / f"single_angle_capacity.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)

    table = "\n".join(f"| {c['specimen_id']} | {c['connection']} | {c['reported_KL_over_r']} | {c['coupon_yield_force_kip']:.1f} | {c['measured_buckling_capacity_kip']:.1f} | {c['conditional_phi']:.6f} |" for c in cases)
    report = f"""# 单等边角钢：实测容量比与条件φ识别

来源：Carden等，2006，Engineering Journal43(2):111–126，[原论文]({DOI})；原始PDF哈希保存在summary.json。
逐页目视核对表1（PDF2/印刷112）及表4（PDF10/印刷120）。采用其直接报告的材性试验屈服力Ag·fy和压屈容量，避免反造面积和fy。

17件中选择{len(cases)}件首方向为压缩且未被2008原报告标记前序拉屈服的候选；7件先拉试件 {', '.join(excluded)} 及先压但压屈前已有拉屈服的F/G/I不用于virgin初始压屈比识别。未标记前序拉屈服不等于已独立核验每个初始状态，仍为条件容量代理。
φ=Pcr/(Ag·fy)可解析求得；再用真实遗传算法核对同一标量目标。遗传算法不是该比例的必要条件，零拟合误差也不代表整条滞回已验证。

| 试件 | 连接 | 论文KL/r | 材性屈服力/kip | 实测压屈容量/kip | 条件φ |
| --- | --- | ---: | ---: | ---: | ---: |
{table}

## 解释边界

表4报告最大压屈容量；本轮用先压组将其作为首峰代理，未逐条数字化核实首循环的具体点，故称条件φ。
直接分母取“Yield Force Coupon Tests”，不取“Measured Yield Strength”或规范“Expected Yield Strength”。
小截面的厚度字形在PDF中显示不完整，此处无需厚度，不从模糊字形推断精确面积。
表中K来自原文对连接塑性铰的判断，不能当作本塔杆件的已知K。
连接细节另保存在source_features.json及CSV：E/I为加固螺栓连接，An/Ag=1.00；普通螺栓先压组为.81。
A节点板厚.5in，其他为1in。未入选的D/H加固螺栓组An/Ag=.93。不能仅按长细比忽略这些差异。
φ的显示舍入范围按两个力各±0.05kip计算，只表示一位小数舍入，不是测量置信区间。

这批参数属于ASTM A36桥梁横撑角钢，连接和尺寸与本塔有差异。它提供真实单角钢标量证据，
不能由此确定α/β/τ/μ/ν/η/θ/κ及ρ/γ/ζ，也没有辨识局部连接损伤、刚度或全塔失效。
完整往复图见原文图7–11；原图是叠线，未编造加载次序。拟合完整循环仍需要可追溯的有序u–F数据。

## 步骤与复现

公开下载PDF → 目视核表 → 按首载方向筛选 → 直接容量比 → GA核对 → 保存筛选和舍入限制。
运行 `python -m initial_imperfection_material.tian_ma_qu.carden_angle_identification --source-pdf PATH --output NEW_DIRECTORY`。
本轮不修改生产参数，新增全塔计算0次。
连接元数据复核前的输出保存在同批_revisions目录；容量比和入选试件数没有改变。
"""
    (output / "REPORT.md").write_text(report)
    trs = "".join(f"<tr><td>{c['specimen_id']}</td><td>{c['connection']}</td><td>{c['reported_KL_over_r']}</td><td>{c['conditional_phi']:.6f}</td></tr>" for c in cases)
    (output / "index.html").write_text(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>单角钢试验：条件φ识别</title><style>body{{font:16px/1.7 system-ui,sans-serif;margin:auto;max-width:1100px;padding:24px;background:#f4f7fa;color:#172b3d}}img{{width:100%;background:white}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:10px;border-bottom:1px solid #dde5ec;text-align:left}}a{{color:#12647f}}.note{{background:#fff3d6;padding:16px}}</style><a href="../index.html">← 参数识别总览</a><h1>真实单等边角钢：{len(cases)}件容量候选</h1><p>依据Carden等2006年公开试验表，使用材性屈服力与实测压屈容量识别条件φ。</p><p class="note">仅确定一个容量比，未完成滞回系数标定。先压组的报告最大容量作为首峰代理；7件先拉及压屈前已拉屈服的F/G/I均已排除。本塔参数未替换。</p><img src="single_angle_capacity.svg" alt="通过前史筛选的条件phi及其与有效长细比关系"><table><thead><tr><th>试件</th><th>连接</th><th>KL/r</th><th>条件φ</th></tr></thead><tbody>{trs}</tbody></table><p><a href="REPORT.md">完整步骤与限制</a> · <a href="conditional_phi.csv">参数CSV</a> · <a href="source_features.json">全部17件来源数据</a> · <a href="summary.json">GA结果</a> · <a href="{html.escape(SOURCE)}">原始论文</a></p></html>""")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.output, args.source_pdf)
    print({"selected": result["selected_compression_first"], "phi_range": result["conditional_phi_range"], "full_hysteresis_validation": False})


if __name__ == "__main__":
    main()
