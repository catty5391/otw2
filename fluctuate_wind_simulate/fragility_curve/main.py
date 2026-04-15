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


def extract_input_from_opensees(output_root: Path, out_csv: Path, reference_type: str = "node_displacement") -> pd.DataFrame:
    """从 .opensees.output/{speed}/{sample} 提取样本峰值响应。

    reference_type:
    - "node_displacement": 读取 Node_displacement.out 的第2列，取绝对值最大值。
    - "drift": 读取 drift.csv 的各层间位移角列，取绝对值最大值。
    """
    ref = reference_type.strip().lower()
    if ref not in {"node_displacement", "drift"}:
        raise ValueError("reference_type 仅支持 'node_displacement' 或 'drift'。")

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

            if ref == "node_displacement":
                disp_file = sample_dir / "Node_displacement.out"
                if not disp_file.exists():
                    continue

                # 两列: time, disp。取位移绝对值最大值作为该样本响应。
                data = pd.read_csv(disp_file, sep=r"\s+", header=None, engine="python")
                if data.shape[1] < 2:
                    continue
                response_max = float(np.max(np.abs(data.iloc[:, 1].to_numpy(dtype=float))))
            else:
                drift_file = sample_dir / "drift.csv"
                if not drift_file.exists():
                    continue

                drift_df = pd.read_csv(drift_file)
                if "step" in drift_df.columns:
                    drift_vals = drift_df.drop(columns=["step"])
                else:
                    drift_vals = drift_df
                if drift_vals.empty:
                    continue
                response_max = float(np.nanmax(np.abs(drift_vals.to_numpy(dtype=float))))

            rows.append(
                {
                    "wind_speed": speed,
                    "response": response_max,
                    "speed_dir": speed_dir.name,
                    "sample": sample_dir.name,
                    "reference_type": ref,
                }
            )

    if not rows:
        raise RuntimeError(f"未在 {output_root} 下找到可用样本。")

    df = pd.DataFrame(rows).sort_values(by=["wind_speed", "sample"]).reset_index(drop=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"已提取样本响应({ref}): {out_csv}，共 {len(df)} 条")
    return df


def auto_damage_states(response: pd.Series) -> dict:
    """自动生成多级阈值（分位点可按需调整）。"""
    vals = response.to_numpy(dtype=float)
    return {
        "DS1": float(np.quantile(vals, 0.70)),
        "DS2": float(np.quantile(vals, 0.85)),
        "DS3": float(np.quantile(vals, 0.95)),
    }


def build_manual_states(manual_thresholds: list[float]) -> dict:
    if not manual_thresholds:
        raise ValueError("manual_thresholds 不能为空。")

    thresholds = [float(v) for v in manual_thresholds]
    for v in thresholds:
        if v <= 0:
            raise ValueError("阈值必须大于 0。")

    thresholds = sorted(thresholds)
    return {f"DS{i+1}": thr for i, thr in enumerate(thresholds)}


def main():
    fragility_dir = Path(__file__).resolve().parent
    opensees_out_dir = fragility_dir.parent / "static" / ".opensees.output"
    output_dir = fragility_dir / "output"

    # 参考指标设置:
    # - "node_displacement": 使用 Node_displacement.out 作为样本响应
    # - "drift": 使用 drift.csv 作为样本响应
    #reference_type = "drift"
    reference_type = "drift"

    # 阈值设置区：
    # 1) manual_thresholds = None -> 自动按分位点生成多级阈值
    # 2) manual_thresholds = [0.25, 0.5] -> 手动多阈值
    # manual_thresholds = [0.001, 0.0015, 0.002]
    manual_thresholds = [0.001, 0.0015, 0.002]

    ref_tag = reference_type.strip().lower()
    input_csv = fragility_dir / f"input_wind_{ref_tag}.csv"

    data_df = extract_input_from_opensees(opensees_out_dir, input_csv, reference_type=reference_type)

    model = WindFragilityCurve.from_csv(input_csv, wind_col="wind_speed", disp_col="response")

    if manual_thresholds is None:
        states = auto_damage_states(data_df["response"])
    else:
        states = build_manual_states(manual_thresholds)
    model.set_damage_states(states)
    print(f"参考指标: {reference_type}")
    print("阈值设置:", states)

    model.build_empirical()
    params = model.fit()

    print("拟合参数：")
    for k, v in params.items():
        print(f"{k}: median={v.median:.4f}, beta={v.beta:.4f}, thr={v.threshold:.4f}")

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_params(output_dir / f"fragility_params_{ref_tag}.csv")
    model.save_curve(output_dir / f"fragility_curve_{ref_tag}.csv")
    model.plot(save_path=output_dir / f"fragility_curve_{ref_tag}.png", show=True)

    query = model.predict([20, 25, 30, 35, 40])
    print("\n指定风速下超越概率：")
    print(query)


if __name__ == "__main__":
    main()