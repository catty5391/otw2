"""Read-only audit of saved tower member parameters; no FE or parameter changes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

MODULE = Path(__file__).resolve().parent
DEFAULT_SOURCE = MODULE / "tower_results/tmq_bounded_03/model_data/tmq_member_parameters.csv"
COEFFICIENTS = ("elastic_modulus", "rho", "alpha", "beta", "gamma", "tau", "mu", "nu", "zeta", "eta", "theta", "kappa")
EXPECTED_HISTORICAL = dict(zip(COEFFICIENTS, (210e9, .03, .506, .020, .5, 1.449, .474, 1.549, .1, .544, .020, .0044)))


def audit(source: Path) -> dict:
    source = Path(source)
    with source.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Empty member parameter evidence")
    tags = [r["element_tag"] for r in rows]
    if len(set(tags)) != len(tags):
        raise ValueError("Duplicate member tags in saved evidence")
    for row in rows:
        for key in (*COEFFICIENTS, "length_m", "area_m2", "yield_stress", "phi", "slenderness_K1", "perry_first_yield_N"):
            value = float(row[key])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Nonpositive or nonfinite {key}")
        peak = float(row["phi"]) * float(row["area_m2"]) * float(row["yield_stress"])
        if not math.isclose(peak, float(row["perry_first_yield_N"]), rel_tol=1e-10):
            raise ValueError("Saved phi disagrees with declared Perry first-yield load")
        if ("Perry first-yield phi K=1 e0/L=0.001; p102_row_a" not in row["provenance"]
                or "UNVALIDATED" not in row["provenance"]):
            raise ValueError("Unexpected parameter source; this audit is for the declared historical tower model")
        if any(not math.isclose(float(row[k]), value, rel_tol=1e-12) for k, value in EXPECTED_HISTORICAL.items()):
            raise ValueError("Changed coefficients need a new provenance report, not the historical description")

    def describe(group):
        result = {"count": len(group)}
        for key in ("length_m", "phi", "slenderness_K1", "yield_stress"):
            values = [float(r[key]) for r in group]
            result[key + "_range"] = [min(values), max(values)]
        return result

    constants = {key: sorted({float(r[key]) for r in rows}) for key in COEFFICIENTS}
    groups = {name: describe([r for r in rows if r["material_name"] == name])
              for name in sorted({r["material_name"] for r in rows})}
    return {"schema": "otw2.tmq_parameter_provenance.v1", "scope": "historical saved tower parameter table only",
            "source": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "member_count": len(rows), "section_count": len({r["section_name"] for r in rows}),
            "by_steel_grade": groups, "coefficient_values": constants,
            "source_provenance": sorted({r["provenance"] for r in rows}),
            "physical_calibration_complete": False, "production_parameters_changed": False, "new_FE_runs": 0,
            "interpretation": "E/fy/A/L are model inputs; phi is a Perry first-fiber-yield proxy, not a test fit. "
                              "Pipe cyclic coefficients and assumed closure parameters have not been validated for these single angles."}


def publish(source, output):
    summary = audit(Path(source))
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    rows = []
    for grade, group in summary["by_steel_grade"].items():
        rows.append(f"| {grade} | {group['count']} | "
                    f"{group['phi_range'][0]:.6f}–{group['phi_range'][1]:.6f} | "
                    f"{group['slenderness_K1_range'][0]:.2f}–{group['slenderness_K1_range'][1]:.2f} |")
    report = """# 当前全塔 TMQ 参数来源审计

读取已保存的 `tower_results/tmq_bounded_03/model_data/tmq_member_parameters.csv`，未启动有限元分析。
这张表代表该历史算例，不自动代表以后改变参数的所有算例。文件哈希见 summary.json。

## 已核实的现状

共 MEMBER_COUNT 根物理杆件、SECTION_COUNT 类截面；E=210 GPa，钢级为 Q235/Q345/Q420。
所有杆件的 α=.506、β=.020、τ=1.449、μ=.474、ν=1.549、η=.544、θ=.020、κ=.0044，
来自既有 `p102_row_a` 圆管参数。ρ=.03 来自塔模型配置，不是这篇论文已经核实的试验值；γ=.5、ζ=.1 仍是显式假设。

| 钢级 | 杆件数 | 已存 φ 范围 | 已存 K=1 长细比范围 |
| --- | ---: | ---: | ---: |
TABLE

φ逐杆由 Perry 首次纤维屈服荷载/(Af_y)生成，K=1、e0/L=.001。它不是试验识别值，也不是已经验证的极限承载力。
表中长细比以当前 K=1 计算；2023论文的有效长细比与固定端条件不能直接等同。
Q355试验数据也不能直接当作本塔Q345/Q420的材料测值。

## 本轮参数采用结论

1. 保留该历史参数组及结果作为探索基线，不将其称作角钢已标定模型。
2. 新识别的 Black 试件 φ 仅用于对应试件的首峰核验；双角钢和圆管均不直接替换本塔单角钢。
3. 2022论文的双角钢九参数可作有来源的候选或优化初始点；当前公开转录仍须原PDF校对，且组合截面与边界必须匹配。
4. 优先取得 2023 固定端单等边角钢 PHM 的完整公式、系数和试验协议，再判断它与当前 TMQ 实现的关系。
5. 正式角钢识别应按截面、有效长细比、端部/连接条件和材料等级分组，以实际循环数据或经试验校核的空间参考模型为目标。
   训练与独立加载协议验证分别保存；峰值、卸载刚度、捏拢、残余位移、回线面积分别评估。
   对所有参数只给一组最优值而无可识别性证据，不能作为全塔升级依据。

[2023单角钢研究（出版社）](https://www.sciencedirect.com/science/article/abs/pii/S0263823122008874)

## 为什么不把全塔现有曲线直接用于材料拟合

全塔位移同时受风荷载、连接边界、导线和材料影响，单条推覆曲线不能唯一分解出九个循环系数；
更不能以当前圆管系数生成的全塔结果反过来证明角钢系数真实。
本轮遗传算法的合成数据恢复检验仅验证数值流程，真实试验的首峰反算仅确定条件φ，二者分别报告。
"""
    report = report.replace("MEMBER_COUNT", str(summary["member_count"])).replace("SECTION_COUNT", str(summary["section_count"])).replace("TABLE", "\n".join(rows))
    (output / "REPORT.md").write_text(report)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.source, args.output)
    print(json.dumps({"members": result["member_count"], "new_FE_runs": 0, "parameters_changed": False}))


if __name__ == "__main__":
    main()
