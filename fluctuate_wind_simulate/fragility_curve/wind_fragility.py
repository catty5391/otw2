from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from pathlib import Path
from typing import Dict, Iterable, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _std_norm_cdf(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    return np.array([0.5 * (1.0 + erf(v / sqrt(2.0))) for v in z], dtype=float)


@dataclass
class FragilityParam:
    state: str
    threshold: float
    median: float  # 对数正态中位值 c
    beta: float    # 对数标准差 β


class WindFragilityCurve:
    """
    根据风速-塔顶位移样本，拟合易损性曲线：
        P(DS_i | V) = Φ((ln(V) - ln(c_i)) / β_i)

    参数
    ----
    wind_speed: 风速序列（m/s）
    top_disp:   对应塔顶位移序列
    """

    def __init__(self, wind_speed: Iterable[float], top_disp: Iterable[float]) -> None:
        self.data = pd.DataFrame(
            {"wind_speed": list(wind_speed), "top_disp": list(top_disp)}
        ).dropna()

        if self.data.empty:
            raise ValueError("输入数据为空。")
        if (self.data["wind_speed"] <= 0).any():
            raise ValueError("风速必须 > 0。")

        self.damage_states: Dict[str, float] = {}
        self.empirical_: Optional[pd.DataFrame] = None
        self.params_: Dict[str, FragilityParam] = {}

    @classmethod
    def from_csv(
        cls,
        csv_path: str | Path,
        wind_col: str = "wind_speed",
        disp_col: str = "top_disp",
    ) -> "WindFragilityCurve":
        df = pd.read_csv(csv_path)
        if wind_col not in df.columns or disp_col not in df.columns:
            raise KeyError(f"CSV 必须包含列: {wind_col}, {disp_col}")
        return cls(df[wind_col].values, df[disp_col].values)

    def set_damage_states(self, states: Dict[str, float]) -> None:
        """
        states 示例:
        {
            "DS1_轻微": 0.10,
            "DS2_中等": 0.20,
            "DS3_严重": 0.35,
            "DS4_倒塌": 0.50
        }
        """
        if not states:
            raise ValueError("damage states 不能为空。")
        for k, v in states.items():
            if v <= 0:
                raise ValueError(f"{k} 阈值必须 > 0。")
        # 按阈值从小到大排序
        self.damage_states = dict(sorted(states.items(), key=lambda kv: kv[1]))

    def build_empirical(self) -> pd.DataFrame:
        """按风速分组，计算每个损伤状态的经验超越概率。"""
        if not self.damage_states:
            raise RuntimeError("请先调用 set_damage_states()。")

        g = self.data.groupby("wind_speed")
        speeds = np.array(sorted(g.size().index.values), dtype=float)
        n = g.size().reindex(speeds).values.astype(int)

        out = pd.DataFrame({"wind_speed": speeds, "n": n})

        for state, thr in self.damage_states.items():
            k = g["top_disp"].apply(lambda s: int((s >= thr).sum())).reindex(speeds).values
            p = k / n
            out[f"{state}_k"] = k
            out[f"{state}_p"] = p

        self.empirical_ = out
        return out

    def _fit_one_state(self, speeds: np.ndarray, n: np.ndarray, k: np.ndarray, threshold: float, state: str) -> FragilityParam:
        """
        用分组二项似然网格搜索拟合 (median=c, beta)。
        """
        min_v, max_v = speeds.min(), speeds.max()
        c_grid = np.geomspace(min_v * 0.6, max_v * 1.6, 220)
        beta_grid = np.linspace(0.08, 1.20, 180)

        # 退化情况处理
        if np.all(k == 0):
            return FragilityParam(state=state, threshold=threshold, median=max_v * 2.0, beta=0.35)
        if np.all(k == n):
            return FragilityParam(state=state, threshold=threshold, median=min_v * 0.5, beta=0.35)

        best_nll = np.inf
        best_c, best_b = None, None
        ln_v = np.log(speeds)

        for c in c_grid:
            z_base = ln_v - np.log(c)
            for b in beta_grid:
                z = z_base / b
                p = _std_norm_cdf(z)
                p = np.clip(p, 1e-8, 1 - 1e-8)
                nll = -np.sum(k * np.log(p) + (n - k) * np.log(1 - p))
                if nll < best_nll:
                    best_nll = nll
                    best_c, best_b = c, b

        return FragilityParam(state=state, threshold=threshold, median=float(best_c), beta=float(best_b))

    def fit(self) -> Dict[str, FragilityParam]:
        """拟合所有损伤状态的参数。"""
        if not self.damage_states:
            raise RuntimeError("请先调用 set_damage_states()。")
        if self.empirical_ is None:
            self.build_empirical()

        emp = self.empirical_
        speeds = emp["wind_speed"].values.astype(float)
        n = emp["n"].values.astype(int)

        params: Dict[str, FragilityParam] = {}
        for state, thr in self.damage_states.items():
            k = emp[f"{state}_k"].values.astype(int)
            params[state] = self._fit_one_state(speeds, n, k, thr, state)

        self.params_ = params
        return params

    def predict(self, speeds: Iterable[float]) -> pd.DataFrame:
        """输出给定风速下各损伤状态超越概率。"""
        if not self.params_:
            raise RuntimeError("请先调用 fit()。")

        v = np.asarray(list(speeds), dtype=float)
        if np.any(v <= 0):
            raise ValueError("预测风速必须 > 0。")

        out = pd.DataFrame({"wind_speed": v})
        for state, p in self.params_.items():
            z = (np.log(v) - np.log(p.median)) / p.beta
            out[state] = _std_norm_cdf(z)
        return out

    def build_curve(self, n_points: int = 200) -> pd.DataFrame:
        """在数据范围上自动生成平滑易损性曲线（从 0 风速开始）。"""
        vmax = self.data["wind_speed"].max() * 1.2
        grid = np.linspace(0.0, vmax, n_points)  # 从0开始
        # predict要求>0，这里仅在计算时做极小值保护
        grid_safe = np.clip(grid, 1e-6, None)
        out = self.predict(grid_safe)
        out["wind_speed"] = grid  # 显示与保存时保持0起点
        return out

    def save_params(self, filepath: str | Path) -> None:
        if not self.params_:
            raise RuntimeError("请先调用 fit()。")
        rows = [
            {
                "state": p.state,
                "threshold": p.threshold,
                "median": p.median,
                "beta": p.beta,
            }
            for p in self.params_.values()
        ]
        pd.DataFrame(rows).to_csv(filepath, index=False)

    def save_curve(self, filepath: str | Path, n_points: int = 200) -> None:
        self.build_curve(n_points=n_points).to_csv(filepath, index=False)

    def plot(self, save_path: Optional[str | Path] = None, show: bool = True) -> None:
        if not self.params_:
            raise RuntimeError("请先调用 fit()。")
        if self.empirical_ is None:
            self.build_empirical()

        curve = self.build_curve()

        plt.figure(figsize=(8, 5))
        for state in self.damage_states.keys():
            # 仅绘制拟合曲线，不绘制散点
            plt.plot(curve["wind_speed"], curve[state], linewidth=2, label=f"{state} fitted curve")

        plt.xlabel("Wind speed")
        plt.ylabel("Exceedance probability")
        plt.xlim(left=0)      # x轴从0开始
        plt.ylim(0, 1.02)
        plt.grid(alpha=0.25)
        plt.legend()
        plt.tight_layout()

        if save_path is not None:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=180)
        if show:
            plt.show()
        else:
            plt.close()