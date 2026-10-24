"""Read-only input validation and batch-run inventory, with optional JSON export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .time_series import validate_wind_sample


def main() -> None:
    parser = argparse.ArgumentParser(description="通用分析工具：输入预检查与任务清单。")
    commands = parser.add_subparsers(dest="command", required=True)
    wind = commands.add_parser("check-wind", help="不建模，检查一个或整批风荷载样本")
    wind.add_argument("root", type=Path)
    wind.add_argument("--node-config", type=Path, required=True)
    wind.add_argument("--output", type=Path)
    runs = commands.add_parser("list-runs", help="汇总运行状态，不启动或续算任何任务")
    runs.add_argument("root", type=Path)
    runs.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.root.is_dir():
        parser.error(f"目录不存在: {arguments.root}")
    rows = []
    failed = 0
    if arguments.command == "check-wind":
        node_config = json.loads(arguments.node_config.read_text(encoding="utf-8"))
        directories = sorted({path.parent for path in arguments.root.rglob("t.csv")})
        if not directories:
            parser.error("未发现任何含 t.csv 的风荷载样本。")
        for directory in directories:
            try:
                checked = validate_wind_sample(directory, node_config)
                rows.append({"sample": str(directory), "status": "valid", "dt": checked["dt"],
                             "nsteps": checked["nsteps"], "channels": len(checked["channels"])})
            except (OSError, ValueError) as error:
                rows.append({"sample": str(directory), "status": "invalid", "error": str(error)})
                failed += 1
    else:
        for path in sorted(arguments.root.rglob("run_manifest.json")):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                rows.append({"manifest": str(path), "status": run["status"],
                             "run_id": run["run_id"], "completed_steps": run["completed_steps"],
                             "error": run.get("error")})
            except (OSError, ValueError, KeyError) as error:
                rows.append({"manifest": str(path), "status": "unreadable", "error": str(error)})
                failed += 1
    payload = {"command": arguments.command, "total": len(rows), "invalid": failed, "items": rows}
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"检查完成: total={len(rows)}, invalid={failed}, output={arguments.output}")
    else:
        print(encoded)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
