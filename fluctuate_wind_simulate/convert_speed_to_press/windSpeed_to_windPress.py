"""将风速时程批量转换为各层风压时程。

输入目录结构:
    fluctuate_wind_simulate/static/wind_speed_generate/{speed}/{sample}/wind_speed.csv

输出目录结构(镜像):
    fluctuate_wind_simulate/static/wind_press_generate/{speed}/{sample}/
"""

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from model.Area import Area


AIR_DENSITY = 1.225


def convert_one_sample(wind_speed_csv: Path, press_output_dir: Path, areas) -> None:
    node_count = len(areas)
    column_names = ["t"] + [f"n{i}" for i in range(node_count)]

    wind_speed = pd.read_csv(
        wind_speed_csv,
        skiprows=1,
        header=None,
        names=column_names,
    )

    for i in range(node_count):
        area = areas[i]
        wind_speed.iloc[:, i + 1] = 0.5 * AIR_DENSITY * (wind_speed.iloc[:, i + 1] ** 2) * area

    press_output_dir.mkdir(parents=True, exist_ok=True)

    wind_speed.iloc[:, 0].to_csv(press_output_dir / "t.csv", header=None, index=False)

    for i in range(node_count):
        wind_speed.iloc[:, i + 1].to_csv(
            press_output_dir / f"floor{i}_wind_press.csv",
            header=None,
            index=False,
        )


def main() -> None:
    area_obj = Area()
    areas = area_obj.get_area()

    speed_root = PROJECT_ROOT / "fluctuate_wind_simulate/static/wind_speed_generate"
    press_root = PROJECT_ROOT / "fluctuate_wind_simulate/static/wind_press_generate"

    processed = 0
    for speed_dir in sorted(speed_root.iterdir()):
        if not speed_dir.is_dir():
            continue

        for sample_dir in sorted(speed_dir.iterdir()):
            if not sample_dir.is_dir():
                continue

            wind_speed_csv = sample_dir / "wind_speed.csv"
            if not wind_speed_csv.exists():
                continue

            out_dir = press_root / speed_dir.name / sample_dir.name
            convert_one_sample(wind_speed_csv, out_dir, areas)
            processed += 1
            print(f"[OK] {speed_dir.name}/{sample_dir.name} -> {out_dir}")

    print(f"done, total converted samples: {processed}")


if __name__ == "__main__":
    main()