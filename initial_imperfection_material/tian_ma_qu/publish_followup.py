"""Publish the bounded B2 grid/frequency studies without conflating model states."""
from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path


SCHEMAS = {"insulator_grid": "otw2.insulator_grid_study.v1",
           "frequency_response": "otw2.tmq_frequency_response.v1"}
TITLES = {"insulator_grid": "仅受拉V串：20／40／80段大变形对照",
          "frequency_response": "N06：模态扩阶、静柔度与频率响应"}
SCOPES = {
    "insulator_grid": "严格仅受拉绝缘子；0°、45°静态增风；比较挂点运动、塔体响应和线／串内力。",
    "frequency_response": "历史弹性绝缘子、无风重力态K/M；候选比例阻尼；检查指定频带的线性响应截断。",
}
ROOT = Path(__file__).resolve().parents[2]


def read_components(root):
    root = Path(root)
    parts = {}
    for name, schema in SCHEMAS.items():
        path = root / name / "summary.json"
        data = json.loads(path.read_text())
        if data.get("schema") != schema:
            raise ValueError(f"Unsupported B2 component schema: {name}")
        if data.get("physical_validation") != "unvalidated":
            raise ValueError(f"This sensitivity batch cannot certify physical validation: {name}")
        if data.get("execution_status") not in {"complete", "blocked", "partial", "failed"}:
            raise ValueError(f"Unfinished or unknown execution status: {name}")
        if data.get("assessment") not in {"pass", "fail", "limited", "not_assessed"}:
            raise ValueError(f"Missing assessment: {name}")
        for field in ("new_FE_runs", "new_eigen_solves"):
            value = data.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Invalid calculation count: {name}/{field}")
        parts[name] = data
    return parts


def check_baseline(root, project_root=ROOT):
    baseline = json.loads((Path(root) / "baseline.json").read_text())
    checked = {}
    for relative, digest in baseline["sha256"].items():
        path = (Path(project_root) / relative).resolve()
        if not path.is_relative_to(Path(project_root).resolve()):
            raise ValueError("Baseline path escapes project")
        checked[relative] = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    if not checked or not all(checked.values()):
        raise ValueError("Protected B2 sources or historical evidence changed")
    return {"passed": True, "checked_files": len(checked), "files": checked}


def make_summary(root, parts, baseline):
    root = Path(root)
    return {
        "schema": "otw2.tmq_b2_followup.v1",
        "execution_status": "complete" if all(p["execution_status"] == "complete" for p in parts.values()) else "partial",
        "assessment": "limited", "physical_validation": "unvalidated",
        "scope": "N06 bounded numerical audit and tension-only static cable-grid study",
        "baseline": baseline,
        "components": {name: {"title": TITLES[name], "scope": SCOPES[name],
                               "execution_status": p["execution_status"], "assessment": p["assessment"],
                               "physical_validation": p["physical_validation"],
                               "new_FE_runs": p.get("new_FE_runs", 0),
                               "new_eigen_solves": p.get("new_eigen_solves", 0),
                               "report": f"{name}/REPORT.md", "page": f"{name}/index.html"}
                       for name, p in parts.items()},
        "new_FE_runs": sum(p.get("new_FE_runs", 0) for p in parts.values()),
        "new_eigen_solves": sum(p.get("new_eigen_solves", 0) for p in parts.values()),
        "source_sha256": {f"{name}/summary.json": hashlib.sha256((root/name/"summary.json").read_bytes()).hexdigest()
                          for name in parts},
        "gates": {"actual_dynamic_damping": "unverified", "G2": "not_passed", "physical_model": "unvalidated"},
        "limitations": ["The two studies use different insulator laws and equilibrium states.",
                        "N06 applies to its declared candidate C and numerical output scope only.",
                        "Static mesh checks do not establish dynamic time-step convergence.",
                        "100 m/s is a bounded static comparison endpoint, not ultimate wind speed.",
                        "Raw research outputs stay local; reports and methods can be versioned."],
    }


def publish(root):
    root = Path(root)
    if (root / "summary.json").exists() or (root / "index.html").exists():
        raise FileExistsError("Existing B2 publication is protected")
    parts = read_components(root)
    baseline = check_baseline(root)
    summary = make_summary(root, parts, baseline)
    cards = []
    for name, p in parts.items():
        cards.append(f'<section><h2>{escape(TITLES[name])}</h2><p>{escape(SCOPES[name])}</p>'
                     f'<p>执行状态：{escape(p["execution_status"])}；数值评估：{escape(p["assessment"])}；实际物理验证：未完成。</p>'
                     f'<div class="links"><a href="{name}/index.html">打开完整曲线与结果 →</a>'
                     f'<a href="{name}/REPORT.md">步骤和最终结果</a><a href="{name}/summary.json">数值汇总</a></div></section>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>塔线续作：网格与频率响应</title><style>
body{font-family:system-ui,sans-serif;max-width:1080px;margin:30px auto;padding:0 18px;background:#f4f7f9;color:#203340;line-height:1.7}
section{background:white;padding:24px;border-radius:12px;margin:20px 0}a{color:#176b8d}.note{border-left:4px solid #bf7c2b;background:#fff3df;padding:14px}
.links{display:flex;gap:18px;flex-wrap:wrap}h1{line-height:1.3}code{overflow-wrap:anywhere}</style>
<a href="/#tianmaqu">← 返回成果首页</a><h1>塔线续作：导线网格与模态频率响应</h1>
<p class="note">两项研究分别回答静态大变形网格和无风重力态模态截断问题。它们使用不同绝缘子假设；不能将其中一项通过视为另一模型已完成动力验证。</p>
''' + "".join(cards) + '''<section><h2>本批与后续计划</h2><div class="links"><a href="REPORT.md">整合结论与下一步</a><a href="execution_status.json">任务进度</a><a href="verification.json">测试与网页检查</a><a href="summary.json">本批汇总</a></div><p>实际绝缘子类型、角钢材料标定和动力阻尼仍需验证。原始计算数据仅保留本地。</p></section></html>'''
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    (root / "index.html").write_text(page)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.output)
    print(json.dumps({k: result[k] for k in ("execution_status", "assessment", "new_FE_runs", "new_eigen_solves")}))
