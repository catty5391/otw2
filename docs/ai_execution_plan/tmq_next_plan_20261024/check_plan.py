"""Check this planning package. Does not import OpenSees or execute FE models."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read_json(path: Path):
    def reject_constant(value):
        raise ValueError(f"nonfinite JSON constant in {path}: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check(*, structure_only=False):
    errors: list[str] = []
    counts = {}

    def require(condition, message):
        if not condition:
            errors.append(message)

    plan = read_json(HERE / "NEXT_TASKS.json")
    criteria = read_json(HERE / "ACCEPTANCE.json")["criteria"]
    baseline = read_json(HERE / "BASELINE.json")
    tasks = plan["tasks"]
    by_id = {t["id"]: t for t in tasks}
    expected = [f"N{i:02d}" for i in range(24)]
    require(list(by_id) == expected and len(tasks) == 24, "task IDs must be unique N00..N23")
    counts["tasks"] = len(tasks)
    counts["criteria"] = len(criteria)
    text = (HERE / "PLAN.md").read_text(encoding="utf-8")
    require(re.findall(r"^### (N\d{2}) —", text, re.M) == expected, "task cards differ from JSON")
    graph = {t["id"]: set(t["depends_on"]) for t in tasks}
    gates = plan["gates"]

    def gate_tasks(gate, trail=()):
        require(gate in gates, f"unknown gate {gate}")
        if gate not in gates:
            return set()
        if gate in trail:
            errors.append(f"gate cycle: {trail} -> {gate}")
            return set()
        dependencies = set(gates[gate]["tasks"])
        for parent in gates[gate].get("requires_gates", []):
            dependencies |= gate_tasks(parent, (*trail, gate))
        return dependencies

    for task in tasks:
        task_id = task["id"]
        require(task["execution_status"] == "planned", f"{task_id}: planning snapshot status changed")
        require(task["assessment"] == "not_assessed", f"{task_id}: execution incorrectly claimed")
        require(task["physical_validation"] == "unvalidated", f"{task_id}: physical validation claimed")
        require(task["source_section_marker"] in text, f"{task_id}: missing prose section")
        require((HERE / task["task_card"]).is_file(), f"{task_id}: missing task document")
        for criterion in task["criteria"]:
            require(criterion in criteria, f"{task_id}: unknown criterion {criterion}")
        for gate in task["required_gates"]:
            graph[task_id] |= gate_tasks(gate)
        budget = task["budget"]
        require(budget["maximum_new_full_tower_cases"] >= 0, f"{task_id}: negative budget")
        require(budget["maximum_new_full_tower_cases"] == 0 or
                budget["per_full_tower_process_timeout_seconds"] > 0,
                f"{task_id}: FE case lacks timeout")
        for dep in graph[task_id]:
            require(dep in by_id, f"{task_id}: unknown dependency {dep}")

    visited, visiting = set(), set()

    def visit(task_id):
        if task_id in visiting:
            errors.append(f"dependency cycle involving {task_id}")
            return
        if task_id in visited or task_id not in graph:
            return
        visiting.add(task_id)
        for dependency in sorted(graph[task_id]):
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)
    counts["tasks_with_gate_expanded_dependencies_checked"] = len(visited)
    first = set(plan["first_batch"])
    for task_id in first:
        require(graph[task_id] <= first, f"first batch missing prerequisites of {task_id}")
        require(by_id[task_id]["budget"]["maximum_new_full_tower_cases"] == 0,
                f"first batch {task_id} starts full-tower FE")
    total_cases = sum(t["budget"]["maximum_new_full_tower_cases"] for t in tasks)
    total_seconds = sum(t["budget"]["maximum_new_full_tower_cases"] *
                        t["budget"]["per_full_tower_process_timeout_seconds"] for t in tasks)
    require(total_cases == plan["total_full_tower_fe_cap"] == 43, "FE case budget mismatch")
    require(total_seconds / 60 == plan["total_full_tower_process_minutes_cap"] == 645,
            "FE process time budget mismatch")
    require("**43**" in text and "**645 分钟**" in text, "prose budgets differ from JSON")
    counts["maximum_conditional_full_tower_cases"] = total_cases
    counts["maximum_conditional_full_tower_process_minutes"] = total_seconds / 60
    counts["first_batch_full_tower_FE"] = 0

    link_count = 0
    docs = [*HERE.glob("*.md"), HERE.parent / "README.md"]
    for doc in docs:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or not parsed.path:
                continue
            destination = doc.parent / unquote(parsed.path)
            require(destination.exists(), f"broken local link in {doc.name}: {target}")
            link_count += 1
    counts["local_links_checked"] = link_count
    existing_entries = [
        "initial_imperfection_material/tian_ma_qu/modal_analysis.py",
        "initial_imperfection_material/tian_ma_qu/full_tower.py",
        "initial_imperfection_material/tian_ma_qu/publish_modal.py",
        "initial_imperfection_material/tian_ma_qu/directional_loading.py",
        "fluctuate_wind_simulate/opensees_simulate/wind_refactor_common.py",
        "fluctuate_wind_simulate/fragility_curve/main.py",
        "py_view/results_dashboard",
        "util/analysis", "util/postprocess/energy.py",
    ]
    for entry in existing_entries:
        require((ROOT / entry).exists(), f"missing existing entry: {entry}")
    counts["existing_code_entries_checked"] = len(existing_entries)

    if not structure_only:
        for entry in baseline["protected_files"]:
            path = ROOT / entry["path"]
            require(path.is_file(), f"missing protected file: {entry['path']}")
            if path.is_file():
                require(path.stat().st_size == entry["size_bytes"] and sha256(path) == entry["sha256"],
                        f"protected file changed: {entry['path']}")
        counts["protected_source_and_evidence_files_checked"] = len(baseline["protected_files"])
        source = ROOT / "initial_imperfection_material/tian_ma_qu"
        modal = read_json(source / "modal_results/summary.json")
        wind = read_json(source / "wind_speed_results/summary.json")
        require(baseline["tower_matches"] == modal["tower_matches"], "modal matching baseline mismatch")
        require(baseline["mesh_checks"] == modal["mesh_checks"], "modal mesh baseline mismatch")
        require(baseline["wind_actual_execution_counts"] == wind["actual_execution_counts"],
                "wind execution count baseline mismatch")
        for case in wind["cases"]:
            key = case["key"]
            if key in baseline["wind_key_cases"]:
                for field, value in baseline["wind_key_cases"][key]["peak"].items():
                    require(value == case["peak_point"][field], f"wind peak mismatch: {key}/{field}")

    return {"schema": "otw2.plan_consistency_check.v1",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "passed": not errors, "structure_only": structure_only,
            "counts": counts, "errors": errors,
            "new_FE_runs": 0, "new_mechanics_tests_run": 0,
            "interpretation": "document, dependencies, budgets and evidence consistency only; not new mechanics validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure-only", action="store_true",
                        help="Skip frozen evidence hashes after later implementation has intentionally changed inputs")
    parser.add_argument("--output", type=Path, help="Optional path to save this check report")
    args = parser.parse_args()
    result = check(structure_only=args.structure_only)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
