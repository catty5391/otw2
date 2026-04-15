import csv
from pathlib import Path


class DriftPeakFinder:
    """Find peak interstory drift info from a drift.csv file.

    CSV format example:
    step,floor0-floor1,floor1-floor2,...
    0,1.2e-5,2.3e-5,...
    """

    def __init__(self, drift_csv_abs_path):
        self.csv_path = Path(drift_csv_abs_path)
        if not self.csv_path.is_absolute():
            raise ValueError("请传入 drift.csv 的绝对路径。")
        if not self.csv_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.csv_path}")

    def get_peak(self, use_abs=True):
        """Return peak drift with step and story label.

        Args:
            use_abs: True 时按绝对值找最大层间位移角；False 时按原值最大。

        Returns:
            dict with keys:
            - step: int
            - story: str
            - drift: float (该点原始值，保留正负号)
            - abs_drift: float (该点绝对值)
        """
        with self.csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "step" not in reader.fieldnames:
                raise ValueError("drift.csv 缺少 step 列。")

            story_cols = [c for c in reader.fieldnames if c != "step"]
            if not story_cols:
                raise ValueError("drift.csv 未找到层间位移角列。")

            best = None
            for row_idx, row in enumerate(reader, start=2):
                step_text = (row.get("step") or "").strip()
                if step_text == "":
                    continue

                step = int(float(step_text))
                for story in story_cols:
                    val_text = (row.get(story) or "").strip()
                    if val_text == "":
                        continue

                    drift = float(val_text)
                    score = abs(drift) if use_abs else drift

                    if best is None or score > best["score"]:
                        best = {
                            "score": score,
                            "step": step,
                            "story": story,
                            "drift": drift,
                            "abs_drift": abs(drift),
                        }

            if best is None:
                raise ValueError("未读取到有效的位移角数据。")

            return {
                "step": best["step"],
                "story": best["story"],
                "drift": best["drift"],
                "abs_drift": best["abs_drift"],
            }

if __name__ == "__main__":
    finder = DriftPeakFinder("/home/panqiheng/OTW/fluctuate_wind_simulate/static/.opensees.output/40mps/sample_05/drift.csv")
    peak = finder.get_peak(use_abs=True)
    print(f"峰值出现在 step={peak['step']}，{peak['story']}，drift={peak['drift']:.6e}，abs_drift={peak['abs_drift']:.6e}")