import pandas as pd
import numpy as np
from pathlib import Path
import re
import json
import argparse
import os
import tempfile

from util.analysis.result_quality import normalize_result_quality
from util.analysis.sample_admission import build_sample_flow, load_manifest_sample

try:
    from wind_fragility import WindFragilityCurve
except ModuleNotFoundError:
    from fluctuate_wind_simulate.fragility_curve.wind_fragility import WindFragilityCurve


def parse_speed_from_dir_name(name: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)mps", name)
    if not m:
        raise ValueError(f"非法风速目录名: {name}")
    return float(m.group(1))


def _write_admission_audit(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".admission-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_response_peak(path: Path, reference_type: str) -> float:
    if reference_type == "node_displacement":
        data = pd.read_csv(path, sep=r"\s+", header=None)
        if data.shape[1] < 2 or data.empty:
            raise ValueError("位移文件至少需要time与disp两列及一个记录。")
        values = data.iloc[:, :2].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("位移文件含非有限的时间或响应。")
        return float(np.max(np.abs(values[:, 1])))
    data = pd.read_csv(path)
    data = data.drop(columns=[name for name in ("step", "time", "t", "accepted_step", "stage_id") if name in data.columns])
    if data.empty:
        raise ValueError("层间位移角文件缺少响应数据。")
    values = data.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("层间位移角文件含非有限响应，不能用nanmax忽略。")
    return float(np.max(np.abs(values)))


def extract_input_from_opensees(
    output_root: Path, out_csv: Path, reference_type: str = "node_displacement", *,
    eligibility_mode: str = "formal", criteria_id: str | None = None,
    audit_json: Path | None = None, expected_samples: list[dict] | None = None,
) -> pd.DataFrame:
    """Extract peaks after lossless admission; default formal is conservative.

    Every discovered sample, including failed/missing/invalid data, is retained
    in sibling *.admission.json before zero-admission raises. expected_samples
    optionally declares missing runs using sample_id/wind_speed/speed_dir.
    Discovery alone does not prove the intended study cohort is complete.

    Explicit exploratory_legacy also permits intact completed, unvalidated
    diagnostics as exploratory_unvalidated_only, never as formal samples.
    """
    output_root, out_csv = Path(output_root), Path(out_csv)
    audit_path = Path(audit_json) if audit_json is not None else out_csv.with_suffix(".admission.json")
    if audit_path.resolve() == out_csv.resolve():
        raise ValueError("样本审计JSON与输出CSV不能使用同一路径。")
    ref = reference_type.strip().lower()
    if ref not in {"node_displacement", "drift"}:
        raise ValueError("reference_type 仅支持 'node_displacement' 或 'drift'。")
    if eligibility_mode not in {"formal", "exploratory_legacy"}:
        raise ValueError("eligibility_mode必须为formal或exploratory_legacy。")
    candidates, notes = [], []
    if output_root.is_dir():
        for speed_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
            try:
                speed = parse_speed_from_dir_name(speed_dir.name)
            except ValueError:
                speed = None
                notes.append({"path": str(speed_dir), "reason": "invalid_wind_speed_directory"})
            for sample_dir in sorted(path for path in speed_dir.iterdir() if path.is_dir()):
                candidates.append((sample_dir.name, speed, speed_dir.name, sample_dir, []))
    else:
        notes.append({"path": str(output_root), "reason": "output_root_missing_or_not_directory"})
    discovered = {(speed, name) for name, speed, _, _, _ in candidates}
    for item in expected_samples or []:
        if not isinstance(item, dict):
            raise ValueError("expected_samples每条必须是含sample_id/wind_speed的对象。")
        name, speed = item.get("sample_id"), item.get("wind_speed")
        valid_speed = isinstance(speed, (int, float)) and not isinstance(speed, bool) and np.isfinite(speed) and speed >= 0
        speed_name = item.get("speed_dir", f"{speed:g}mps" if valid_speed else "invalid_speed")
        valid_name = isinstance(name, str) and name not in {"", ".", ".."} and Path(name).name == name and "/" not in name and "\\" not in name
        try:
            valid_speed_name = isinstance(speed_name, str) and parse_speed_from_dir_name(speed_name) == speed
        except ValueError:
            valid_speed_name = False
        if not (valid_speed and valid_name and valid_speed_name):
            candidates.append((name, speed if valid_speed else None, str(speed_name), None, ["invalid_expected_sample_metadata"]))
        elif (float(speed), name) not in discovered:
            candidates.append((name, float(speed), speed_name, output_root / speed_name / name, []))

    samples, source_meta = [], []
    for name, speed, speed_name, directory, errors in candidates:
        if directory is None:
            sample = {"sample_id": name, "wind_speed": speed, "manifest": None, "input_errors": errors}
        else:
            sample = load_manifest_sample(name, speed, directory / "run_manifest.json")
            response_path = directory / ("Node_displacement.out" if ref == "node_displacement" else "drift.csv")
            sample["response_source"] = str(response_path)
            try:
                sample["response"] = _read_response_peak(response_path, ref)
            except FileNotFoundError:
                sample["input_errors"].append("response_missing")
            except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as error:
                sample["input_errors"].append(f"response_invalid:{type(error).__name__}")
        samples.append(sample)
        source_meta.append({"speed_dir": speed_name, "reference_type": ref})

    audit = build_sample_flow(samples, mode=eligibility_mode, criteria_id=criteria_id)
    for row, sample in zip(audit["rows"], samples):
        quality = normalize_result_quality(sample.get("manifest"))
        row["quality_metadata"] = quality
        if (
            eligibility_mode == "exploratory_legacy" and row["admission_status"] == "excluded"
            and row["execution_status"] == "completed" and row["validation_status"] == "unvalidated"
            and row["domain_status"] in {"unknown", "in_range"}
            and row["purpose"] in {"diagnostic", "training_fit", "independent_validation"}
            and not row["quality_flags"] and not row["input_errors"] and row["response"] is not None
            and not set(row["reason_codes"]) & {"duplicate_sample_identity", "invalid_sample_id", "invalid_wind_speed"}
        ):
            row.update(admission_status="exploratory_unvalidated_only", selected_for_analysis=True)
            row["reason_codes"].append("unvalidated_response_exploration")
    groups = [(audit["overall"], audit["rows"])] + [
        (group, [row for row in audit["rows"] if row["wind_speed_mps"] == group["wind_speed_mps"]])
        for group in audit["by_wind_speed"]
    ]
    for summary, rows_in_group in groups:
        added = sum(row["admission_status"] == "exploratory_unvalidated_only" for row in rows_in_group)
        summary["exploratory_unvalidated_only"] = added
        summary["excluded"] -= added
        summary["selected_for_response_export"] = sum(row["selected_for_analysis"] for row in rows_in_group)
        if added:
            summary["reason_counts"]["unvalidated_response_exploration"] = added
    audit["extraction"] = {
        "output_root": str(output_root), "reference_type": ref, "output_csv": str(out_csv),
        "expected_cohort_supplied": expected_samples is not None, "discovery_notes": notes,
        "fit_performed": False, "formal_thresholds_inferred": False,
    }
    audit["warnings"].append("Discovery alone cannot enumerate absent intended runs; supply expected_samples for a predeclared cohort.")
    audit["warnings"].append("exploratory_unvalidated_only preserves intact unvalidated diagnostic quality; it is never formal admission.")
    _write_admission_audit(audit_path, audit)

    selected = []
    for row, meta in zip(audit["rows"], source_meta):
        if not row["selected_for_analysis"]:
            continue
        physical = row["physical_state_for_selected_criterion"]
        selected.append({
            "wind_speed": row["wind_speed_mps"], "response": row["response"], "speed_dir": meta["speed_dir"],
            "sample": row["sample_id"], "reference_type": ref, "admission_status": row["admission_status"],
            "eligible_for_fragility": row["eligible_for_fragility"], "criteria_id": criteria_id,
            "limit_state_reached": None if physical == "unknown" else physical == "reached",
        })
    if not selected:
        detail = "正式模式缺少已冻结的criteria_id。" if eligibility_mode == "formal" and criteria_id is None else "没有通过所选质量门槛的响应样本。"
        raise RuntimeError(f"{detail} 全部{len(samples)}条样本流转已写入{audit_path}；未读取或复用旧输出CSV。")
    df = pd.DataFrame(selected).sort_values(by=["wind_speed", "sample"]).reset_index(drop=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    df.attrs["admission_audit"] = str(audit_path)
    df.attrs["eligibility_mode"] = eligibility_mode
    print(f"已提取样本响应({ref}, {eligibility_mode}): {out_csv}，准入{len(df)}/{len(samples)}条；完整流转: {audit_path}")
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
        if not np.isfinite(v) or v <= 0:
            raise ValueError("阈值必须为有限正数。")

    thresholds = sorted(thresholds)
    return {f"DS{i+1}": thr for i, thr in enumerate(thresholds)}


def main(argv=None):
    fragility_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="保守样本准入；正式模式不自动推断物理阈值或拟合易损性。")
    parser.add_argument("--output-root", type=Path, default=fragility_dir.parent / "static" / ".opensees.output")
    parser.add_argument("--output-dir", type=Path, default=fragility_dir / "output")
    parser.add_argument("--reference-type", choices=("node_displacement", "drift"), default="drift")
    parser.add_argument("--eligibility-mode", choices=("formal", "exploratory_legacy"), default="formal")
    parser.add_argument("--criteria-id", help="必须与样本证据中已冻结的物理判据ID相同；不是随意填写的新名称。")
    parser.add_argument("--cohort-json", type=Path, help="可选预声明sample_id/wind_speed/speed_dir对象列表，包括缺失运行。")
    thresholds = parser.add_mutually_exclusive_group()
    thresholds.add_argument("--manual-thresholds", nargs="+", type=float, help="仅显式历史探索模式使用，不构成冻结物理判据。")
    thresholds.add_argument("--auto-thresholds", action="store_true", help="仅显式历史探索模式使用分位数演示。")
    parser.add_argument("--show", action="store_true", help="显示探索图；默认只保存图。")
    args = parser.parse_args(argv)
    if args.eligibility_mode == "formal" and (args.manual_thresholds is not None or args.auto_thresholds):
        parser.error("formal模式不接受临时手填或分位数阈值作为已冻结物理判据。")
    expected = json.loads(args.cohort_json.read_text(encoding="utf-8")) if args.cohort_json else None
    if expected is not None and not isinstance(expected, list):
        parser.error("--cohort-json必须为样本对象列表。")
    ref_tag = args.reference_type
    label = "formal" if args.eligibility_mode == "formal" else "exploratory"
    output_dir = args.output_dir
    input_csv = output_dir / f"input_wind_{ref_tag}_{label}.csv"
    data_df = extract_input_from_opensees(
        args.output_root, input_csv, reference_type=ref_tag,
        eligibility_mode=args.eligibility_mode, criteria_id=args.criteria_id, expected_samples=expected,
    )
    if args.eligibility_mode == "formal":
        print("已输出正式准入表和完整队列事件计数。未自动拟合概率曲线；T22仍需冻结物理阈值映射、统计方案及未知样本处理。")
        return data_df
    if args.manual_thresholds is None and not args.auto_thresholds:
        parser.error("探索响应已导出；拟合演示还需显式--manual-thresholds或--auto-thresholds。")
    model = WindFragilityCurve.from_csv(input_csv, wind_col="wind_speed", disp_col="response")
    if args.auto_thresholds:
        states = auto_damage_states(data_df["response"])
    else:
        states = build_manual_states(args.manual_thresholds)
    model.set_damage_states(states)
    print(f"仅探索性演示，非正式易损性结论。参考指标: {ref_tag}；阈值: {states}")

    model.build_empirical()
    params = model.fit()

    print("拟合参数：")
    for k, v in params.items():
        print(f"{k}: median={v.median:.4f}, beta={v.beta:.4f}, thr={v.threshold:.4f}")

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_params(output_dir / f"fragility_params_{ref_tag}_exploratory.csv")
    model.save_curve(output_dir / f"fragility_curve_{ref_tag}_exploratory.csv")
    model.plot(save_path=output_dir / f"fragility_curve_{ref_tag}_exploratory.png", show=args.show)

    query = model.predict([20, 25, 30, 35, 40])
    print("\n指定风速下超越概率：")
    print(query)


if __name__ == "__main__":
    main()
