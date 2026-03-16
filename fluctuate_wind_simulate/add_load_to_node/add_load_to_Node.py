#将每层风荷载分配到节间点上，同时生成相应的tcl文件

import json
import re
from pathlib import Path

import pandas as pd


def get_floor_index(floor_name: str) -> int:
    """
    从 'floor10' 这种名字中提取数字 10
    """
    match = re.fullmatch(r"floor(\d+)", floor_name)
    if not match:
        raise ValueError(f"非法楼层名: {floor_name}")
    return int(match.group(1))


# 当前脚本工作目录
base_dir = Path.cwd()

# 配置文件
config_path = base_dir / "fluctuate_wind_simulate" / ".config" / "node_to_add_wind_press.json"

# 输出目录
output_dir = base_dir / "fluctuate_wind_simulate" / "static" / "wind_force_tcl"
output_dir.mkdir(parents=True, exist_ok=True)

# 读取配置
with config_path.open("r", encoding="utf-8") as f:
    config = json.load(f)

dt = 1 / 12

# 按 floor 后面的数字排序，避免 floor10 排到 floor2 前面
floor_names = sorted(config.keys(), key=get_floor_index)

with (output_dir / "timeseries.tcl").open("w", encoding="utf-8") as ts, \
     (output_dir / "pattern.tcl").open("w", encoding="utf-8") as pattern:

    for ts_id, floor_name in enumerate(floor_names):
        node_list = config[floor_name]
        node_num = len(node_list)

        floor_idx = get_floor_index(floor_name)

        # 输入 csv
        read_filename = base_dir/ "fluctuate_wind_simulate" / "static" / "wind_press_generate" / f"floor{floor_idx}_wind_press.csv"

        # 每层风压均分到该层节点
        floor_wind = pd.read_csv(read_filename, header=None) / node_num

        # 每层生成一个 tcl 数据文件
        write_filename = output_dir / f"floor{floor_idx}.tcl"
        floor_wind.to_csv(write_filename, header=False, index=False)

        # timeSeries
        ts.write(
            f"timeSeries Path {ts_id} -dt {dt} "
            f"-filePath ../fluctuate_wind_simulate/wind_press/wind_force_tcl/floor{floor_idx}.tcl\n"
        )

        # pattern + load
        for node_tag in node_list:
            pattern_id = (ts_id + 1) * node_tag
            pattern.write(f"pattern Plain {pattern_id} {ts_id} " + "{\n")
            pattern.write(f"load {node_tag} 0 1 0 0 0 0\n")
            pattern.write("}\n")
