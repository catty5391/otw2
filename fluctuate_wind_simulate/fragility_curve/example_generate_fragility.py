import pandas as pd
import numpy as np
from pathlib import Path
import re

try:
    from wind_fragility import WindFragilityCurve
except ModuleNotFoundError:
    from fluctuate_wind_simulate.fragility_curve.wind_fragility import WindFragilityCurve


def parse_speed_from_dir_name(name: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)mps", name)
    if not m:
        raise ValueError(f"非法风速目录名: {name}")
    return float(m.group(1))


def extract_input_from_opensees(output_root: Path, out_csv: Path) -> pd.DataFrame:
    """从 .opensees.output/{speed}/{sample}/Node_displacement.out 提取样本最大位移。"""
    rows = []

    for speed_dir in sorted(output_root.iterdir()):
        if not speed_dir.is_dir():
            continue

        try:
            speed = parse_speed_from_dir_name(speed_dir.name)
        except ValueError:
            continue

        for sample_dir in sorted(speed_dir.iterdir()):
            if not sample_dir.is_dir():
                continue

            disp_file = sample_dir / "Node_displacement.out"
            if not disp_file.exists():
                continue

            # 两列: time, disp。取位移绝对值最大值作为该样本塔顶响应。
            data = pd.read_csv(disp_file, delim_whitespace=True, header=None)
            if data.shape[1] < 2:
                continue
            top_disp_max = float(np.max(np.abs(data.iloc[:, 1].to_numpy(dtype=float))))

            rows.append(
                {
                    "wind_speed": speed,
                    "top_disp": top_disp_max,
                    "speed_dir": speed_dir.name,
                    "sample": sample_dir.name,
                }
            )

    if not rows:
        raise RuntimeError(f"未在 {output_root} 下找到可用样本。")

    df = pd.DataFrame(rows).sort_values(by=["wind_speed", "sample"]).reset_index(drop=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"已提取样本位移: {out_csv}，共 {len(df)} 条")
    return df


def auto_damage_states(top_disp: pd.Series) -> dict:
    """仅保留 1 条易损性曲线阈值（可按需要调整分位点）。"""
    threshold = float(np.quantile(top_disp.to_numpy(dtype=float), 0.85))
    return {"DS": threshold}


def main():
    fragility_dir = Path(__file__).resolve().parent
    opensees_out_dir = fragility_dir.parent / "static" / ".opensees.output"
    input_csv = fragility_dir / "input_wind_disp.csv"
    output_dir = fragility_dir / "output"

    # 手动阈值设置区：
    # 1) 保持 None -> 自动按分位点生成阈值
    # 2) 改成数字(如 0.12) -> 使用手动阈值，仅生成一条 DS 曲线
    manual_threshold = 0.5

    data_df = extract_input_from_opensees(opensees_out_dir, input_csv)

    model = WindFragilityCurve.from_csv(input_csv, wind_col="wind_speed", disp_col="top_disp")

    if manual_threshold is None:
        states = auto_damage_states(data_df["top_disp"])
    else:
        states = {"DS": float(manual_threshold)}
    model.set_damage_states(states)
    print("手动阈值:", states)

    model.build_empirical()
    params = model.fit()

    print("拟合参数：")
    for k, v in params.items():
        print(f"{k}: median={v.median:.4f}, beta={v.beta:.4f}, thr={v.threshold:.4f}")

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_params(output_dir / "fragility_params.csv")
    model.save_curve(output_dir / "fragility_curve.csv")
    model.plot(save_path=output_dir / "fragility_curve.png", show=True)

    query = model.predict([20, 25, 30, 35, 40])
    print("\n指定风速下超越概率：")
    print(query)


if __name__ == "__main__":
    main()