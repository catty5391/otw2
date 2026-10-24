"""Offline damping candidates and source audit; never constructs an OpenSees domain."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


PROJECT = Path(__file__).resolve().parents[2]
OFFICIAL = {
    "rayleigh": "https://opensees.github.io/OpenSeesDocumentation/user/manual/model/damping/rayleigh.html",
    "corot_truss": "https://openseespydoc.readthedocs.io/en/latest/src/corotTruss.html",
}


def equal_target_coefficients(f1: float, f2: float, damping_ratio: float) -> tuple[float, float]:
    """Positive two-distinct-frequency proportional-damping interpolation, SI units."""
    if not all(math.isfinite(v) and v > 0 for v in (f1, f2, damping_ratio)):
        raise ValueError("finite positive frequencies and target damping required")
    if f1 == f2:
        raise ValueError("two identical frequencies do not identify two coefficients")
    a, b = sorted((2 * math.pi * f1, 2 * math.pi * f2))
    return 2 * damping_ratio * a * b / (a + b), 2 * damping_ratio / (a + b)


def spectrum(frequencies, alpha_m, beta_k):
    fs = np.asarray(frequencies, dtype=float)
    if fs.ndim != 1 or not len(fs) or not np.all(np.isfinite(fs)) or np.any(fs <= 0):
        raise ValueError("nonempty finite positive frequency vector required")
    if not all(math.isfinite(v) and v >= 0 for v in (alpha_m, beta_k)):
        raise ValueError("finite nonnegative coefficients required")
    w = 2 * np.pi * fs
    return .5 * (alpha_m / w + beta_k * w)


def source_audit(project=PROJECT):
    """Record actual source statements; do not infer runtime damping from flags alone."""
    names = ["model/tower_line_system_model.py", "model/tower_model_with_tian_ma_qu.py",
             "fluctuate_wind_simulate/opensees_simulate/wind_refactor_common.py",
             "initial_imperfection_material/full_tower_cyclic.py"]
    records = []
    sources = {}
    for name in names:
        path = Path(project) / name
        source = path.read_text(encoding="utf-8")
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            if method not in {"element", "rayleigh", "region", "constraints", "system", "test", "integrator"}:
                continue
            first = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            if method == "element" and first not in {"corotTruss", "corotTrussSection", "dispBeamColumn"}:
                continue
            record = {"source": name, "line": node.lineno, "method": method,
                      "first_argument": first, "statement": ast.get_source_segment(source, node)}
            if method == "element" and first in {"corotTruss", "corotTrussSection"}:
                flags = [i for i, a in enumerate(node.args)
                         if isinstance(a, ast.Constant) and a.value == "-doRayleigh"]
                record["explicit_doRayleigh"] = bool(flags)
                record["documented_default_element_rayleigh_flag"] = 0
                record["runtime_damping_verified"] = False
            records.append(record)
    return {"sources_sha256": sources, "calls": records,
            "runtime_verified": False,
            "interpretation": "Missing element Rayleigh flag does not establish absent nodal mass-proportional damping."}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(output, modal_root=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refuse to overwrite damping audit: {output}")
    modal_root = Path(modal_root or Path(__file__).with_name("modal_results"))
    source = modal_root / "summary.json"
    saved = json.loads(source.read_text())
    primary = saved["primary_case"]
    modes = saved["cases"][primary]["modes"]
    fs = np.array([m["frequency_Hz"] for m in modes])
    towers = [m["frequency_Hz"] for m in saved["tower_matches"][primary]]
    # 1% is a deliberately declared diagnostic target, not an inferred physical value.
    target = .01
    designs = [
        ("broad_band_candidate", "跨导线与塔体频带的候选", fs[0], max(towers), "offline_reference_only"),
        ("tower_band_sensitivity", "仅塔体频带锚点的敏感性对照", min(towers), max(towers), "sensitivity_only"),
        ("first_two_global_counterexample", "全局前两阶锚点的反例", fs[0], fs[1], "not_recommended_unchecked"),
    ]
    output.mkdir(parents=True)
    candidates = []
    rows = []
    for key, label, f1, f2, purpose in designs:
        alpha, beta = equal_target_coefficients(float(f1), float(f2), target)
        values = spectrum(fs, alpha, beta)
        definition = {"scheme_id": key, "construction": "C_candidate = alphaM * M_saved + betaK * K_gravity_saved",
                      "DOF_coverage": "all saved free equations, including massless rotations; hypothetical full K participation",
                      "alphaM_per_s": alpha, "betaK_s": beta,
                      "input_matrix_paths": [str(modal_root / "runs" / primary / n) for n in ("mass.npz", "stiffness.npz")],
                      "input_matrix_sha256": {n: hashlib.sha256((modal_root / "runs" / primary / n).read_bytes()).hexdigest()
                                              for n in ("mass.npz", "stiffness.npz")},
                      "frequency_band_Hz": [.05, 10.], "outputs": "modal damping spectrum only; no actual time response"}
        fingerprint = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
        candidates.append({**definition, "construction_sha256": fingerprint, "label": label, "purpose": purpose,
                           "anchor_frequencies_Hz": [float(f1), float(f2)], "diagnostic_target_ratio": target,
                           "target_source": "assumed 1% for software comparison, no measured/angle-tower physical calibration",
                           "anchor_relative_gap": abs(float(f2 / f1 - 1)),
                           "lowest_cable_damping_ratio": float(values[0]),
                           "tower_damping_ratios": spectrum(towers, alpha, beta).tolist(),
                           "saved_frequency_range_damping_ratio": [float(values.min()), float(values.max())],
                           "implemented_C_confirmed": False, "candidate_linear_C_computed": True,
                           "G1_passed": False, "G2_passed": False})
        rows.extend({"scheme_id": key, "mode": m["mode"], "frequency_Hz": m["frequency_Hz"],
                     "candidate_damping_ratio": float(z)} for m, z in zip(modes, values))
    with (output / "damping_spectrum.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    audit = source_audit()
    limitations = [
        "These coefficients describe an offline mathematical C, not a verified OpenSees implementation.",
        "K_gravity is not automatically the initial element stiffness used by betaKInit.",
        "Line/insulator element flags, nodal mass damping and regional assignments require separate runtime checks.",
        "Current/committed/initial stiffness choices during nonlinear softening require new assessment.",
        "TMQ material parameter zeta is not this viscous damping ratio.",
        "No new FE, eigen solve, free-decay or transient analysis was performed.",
    ]
    summary = {"schema": "otw2.damping_audit.v1", "execution_status": "complete", "assessment": "limited",
               "physical_validation": "unvalidated", "new_FE_runs": 0, "primary_case": primary,
               "modal_summary_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "candidates": candidates, "source_audit": audit, "sources": OFFICIAL,
               "limitations": limitations, "next_runtime_verification_tasks": ["N07", "N08"],
               "artifacts": ["damping_spectrum.csv", "damping_spectrum.svg", "damping_spectrum.png",
                             "damping_spectrum.pdf", "transient_adapter_spec.md", "REPORT.md"]}
    write_json(output / "damping_candidates.json", summary)
    write_json(output / "summary.json", summary)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    grid = np.geomspace(.05, 10, 700)
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    for candidate in candidates:
        ax.semilogx(grid, 100*spectrum(grid, candidate["alphaM_per_s"], candidate["betaK_s"]),
                    label=candidate["scheme_id"])
    ax.axhline(100*target, color="#6c7c88", linestyle=":", label="Assumed 1% diagnostic target")
    ax.axvspan(min(towers), max(towers), color="#14816d", alpha=.12, label="Tower shape band")
    ax.axvline(fs[0], color="#8c690c", linestyle="--", linewidth=.8)
    spectrum_top=max(float(np.max(100*spectrum(grid,c["alphaM_per_s"],c["betaK_s"]))) for c in candidates)
    ax.set(xlabel="Frequency (Hz)", ylabel="Candidate modal damping (%)", ylim=(0, 1.05*spectrum_top),
           title="Offline full-K Rayleigh candidates; actual element coverage NOT verified")
    ax.grid(alpha=.2); ax.legend(fontsize=8)
    for ext in ("svg", "png", "pdf"):
        fig.savefig(output / f"damping_spectrum.{ext}", dpi=170)
    plt.close(fig)
    table = "\n".join(f'|{c["label"]}|{c["anchor_frequencies_Hz"][0]:.6f} / {c["anchor_frequencies_Hz"][1]:.6f}|'
                      f'{100*c["lowest_cable_damping_ratio"]:.3f}%|'
                      + " / ".join(f'{100*z:.3f}%' for z in c["tower_damping_ratios"]) + "|" for c in candidates)
    report = f'''# N04 阻尼与瞬态接口审计

本项已完成离线方案计算和源码审计，尚未验证实际动力阻尼；physical_validation=unvalidated。新FE=0。

## 实际步骤

1. 从已发布80段重力态模态与前三塔体匹配读取锚点，冻结仅供诊断的1%目标。
2. 计算三个候选C及逐阶谱，保存矩阵/构造指纹；没有在OpenSees中施加它们。
3. 用Python AST记录塔梁、导线、绝缘子单元语句及旧瞬态分析配置。
4. 编写后续适配规格与小扰动验收流程，输出科学图和CSV。

|方案|锚点Hz|最低导线模态候选阻尼|扭转 / X / Y候选阻尼|
|---|---|---|---|
{table}

跨频带方案保留为N06数学参照候选；不能据此认定1%是该塔的真实阻尼。全局前两阶反例会给塔体频带更高阻尼；只锚定塔体也会增加低频导线阻尼。

线与绝缘子构造没有显式`-doRayleigh`，文档默认元素标志为0；节点质量比例项须另核，不能写成导线完全无阻尼。[官方杆单元文档]({OFFICIAL['corot_truss']})
Rayleigh各刚度选项和设置时机见[官方说明]({OFFICIAL['rayleigh']})。保存的重力切线K与`betaKInit`的初始元素K不是可互换名称。

## 后续判定

N06在候选C下检查频响/截断，形成candidate_linear_C条件结果；N07/N08核实实际元素/节点覆盖和自由衰减，离线回检后才允许implemented_C_confirmed和G2。当前G1/G2均未通过。
完整缺口与实施顺序见[适配规格](transient_adapter_spec.md)。本次测试记录由批次verification汇总，曲线是计算得到的候选频谱，非自由衰减实测。
'''
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    (output / "transient_adapter_spec.md").write_text(ADAPTER_SPEC, encoding="utf-8")
    return summary


ADAPTER_SPEC = '''# N07/N08 瞬态适配实施规格（本批尚未实现）

1. 在TMQ模块建立专用runner，或向旧runner注入明确的wind_loader/analysis配置/observer；旧API目前只含model_factory与initialize_model等已有钩子，不接受这些拟议参数。
2. 每样本独立进程/域：建塔线→重力一次→平衡检查→冻结恒载→需要时平均风平衡→设定时程基点→定义阻尼→加载真实空间时变节点向量。保留初应力，禁止继承前次推覆状态。
3. 载荷schema：physical_time_s、node_tag、Fx/Fy/Fz/Mx/My/Mz、group_id、source_field_id、mean_or_fluctuating、units。独立空间组不同Path；负公共压力系数不是反风向。
4. solver schema：constraints、numberer、system、test（带单位/尺度）、algorithm、Newmark、dt/min_dt、尝试/时长上限。旧Plain/BandGeneral/NormDispIncr0.001不直接作为小扰动默认。
5. damping schema：scheme_id、目标来源、DOF覆盖、每种单元flag、节点/region、alphaM/betaK/betaKInit/betaKcomm及设置时机；候选K_gravity不能直接用betaKInit替代。
6. 输出真实accepted子步时刻、u/v/a、风/重力完整账本、惯性与阻尼、塔脚/远端反力、1528塔杆端力、导线/绝缘子轴力和TMQ历史分支。失败尝试另表，partial不补尾。
7. 观察坐标：沿风(cosα,sinα)、横风(-sinα,cosα)、RZ；控制X/H独立。旧漂移器Y平动/X转角约定需替换为显式截面运动，改变control_dof并不够。
8. 单元/小结构测试：解析振子幅值与相位、线性动力平衡、无质量转动、输入插值/起终点、标签清理、重复重力防护、A→B与独立B一致、失败回滚和记录关闭。
9. 全塔6主例：两模型各零扰动、自由衰减、谐波；最多2重试，先冻结幅值保持弹性。低频检验覆盖足够的5.126s周期，近重根通过投影/辨识分离拍振。
10. N08把实测C实现与候选C匹配；不匹配先回检N06离线截断，G2/G3不得通过。每步动态平衡Fext−Fint−Ma−Cv，平动与转动独立，含远端反力。
11. 能量完整检查只用于已知线性储能的小模型；非线性TMQ未知储能/耗散填null及原因。外功不能冒充滞回耗能。
12. 所有成果区分execution_status、assessment、physical_validation。候选谱、数值接入、真实角钢/气动的物理验证各自独立。
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--modal-root", type=Path)
    args = parser.parse_args()
    result = run(args.output, args.modal_root)
    print(json.dumps({"assessment": result["assessment"], "candidates": len(result["candidates"]), "new_FE_runs": 0}))
