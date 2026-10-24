"""Matplotlib figures for the single-member validation experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .material import EquivalentImperfectionMaterial, MemberProperties, PushoverPoint


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 180,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 10,
        }
    )


def plot_pushover(
    path: Path,
    curves: Mapping[str, Sequence[PushoverPoint]],
    summary: Mapping[str, Any],
) -> None:
    labels = {
        "segmented_reference": "16-segment geometric reference",
        "equivalent_calibrated": "1-element reversible calibrated law",
        "equivalent_perry": "1-element reversible Perry trial",
        "perfect_steel_corot_truss": "1-element perfect Steel02",
    }
    styles = {
        "segmented_reference": dict(color="#202020", linewidth=2.4),
        "equivalent_calibrated": dict(color="#d1495b", linewidth=2.0, linestyle="--"),
        "equivalent_perry": dict(color="#00798c", linewidth=1.8, linestyle="-."),
        "perfect_steel_corot_truss": dict(color="#edae49", linewidth=1.5, linestyle=":"),
    }
    figure, axis = plt.subplots(figsize=(8.2, 5.2))
    for name, curve in curves.items():
        axis.plot(
            [point.shortening * 1000.0 for point in curve],
            [point.force / 1000.0 for point in curve],
            label=labels[name],
            **styles[name],
        )
    theory = summary["theory"]
    axis.axhline(
        theory["gb50017_curve_a_load"] / 1000.0,
        color="#6a4c93",
        linewidth=1.0,
        alpha=0.8,
        label="GB 50017 curve a",
    )
    axis.axhline(
        theory["ec3_curve_b_load"] / 1000.0,
        color="#1982c4",
        linewidth=1.0,
        alpha=0.8,
        label="EC3 curve b",
    )
    axis.set_xlabel("Axial shortening (mm)")
    axis.set_ylabel("Compression force (kN)")
    axis.set_title("L125x8Q345 single-member compression pushover")
    axis.legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_normalized_pushover(
    path: Path,
    member: MemberProperties,
    curves: Mapping[str, Sequence[PushoverPoint]],
) -> None:
    figure, axis = plt.subplots(figsize=(8.2, 5.2))
    colors = ("#202020", "#d1495b", "#00798c", "#edae49")
    yield_shortening = member.length * member.yield_strength / member.elastic_modulus
    for (name, curve), color in zip(curves.items(), colors):
        axis.plot(
            [point.shortening / yield_shortening for point in curve],
            [point.force / member.squash_load for point in curve],
            label=name,
            color=color,
            linewidth=1.8,
        )
    axis.set_xlabel(r"Normalized shortening  $\Delta/(L f_y/E)$")
    axis.set_ylabel(r"Normalized force  $N/(A f_y)$")
    axis.set_title("Normalized model comparison")
    axis.legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_material_backbones(
    path: Path,
    materials: Mapping[str, EquivalentImperfectionMaterial],
) -> None:
    figure, axis = plt.subplots(figsize=(8.2, 5.2))
    colors = {"equivalent_calibrated": "#d1495b", "equivalent_perry": "#00798c"}
    for name, material in materials.items():
        points = list(reversed(material.compression_envelope)) + [
            type(material.compression_envelope[0])(0.0, 0.0)
        ] + list(material.tension_envelope())
        axis.plot(
            [point.strain * 100.0 for point in points],
            [point.stress / 1e6 for point in points],
            marker="o",
            markersize=3,
            linewidth=1.8,
            color=colors[name],
            label=name,
        )
    axis.axhline(0.0, color="black", linewidth=0.7)
    axis.axvline(0.0, color="black", linewidth=0.7)
    axis.set_xlabel("Equivalent axial strain (%)")
    axis.set_ylabel("Equivalent stress (MPa)")
    axis.set_title("Asymmetric equivalent member backbones")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_sensitivity(path: Path, summary: Mapping[str, Any]) -> None:
    rows = summary["sensitivity"]
    figure, axis = plt.subplots(figsize=(7.4, 4.8))
    axis.plot(
        [row["imperfection_ratio"] * 100.0 for row in rows],
        [row["peak_load"] / 1000.0 for row in rows],
        marker="o",
        linewidth=2.0,
        color="#00798c",
    )
    for row in rows:
        axis.annotate(
            f"L/{row['imperfection_denominator']:.0f}",
            (row["imperfection_ratio"] * 100.0, row["peak_load"] / 1000.0),
            xytext=(4, 5),
            textcoords="offset points",
            fontsize=8,
        )
    axis.set_xlabel("Initial bow ratio e0/L (%)")
    axis.set_ylabel("Perry first-yield load (kN)")
    axis.set_title("Sensitivity to initial crookedness")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_pre_yield_unloading(
    path: Path,
    histories: Mapping[str, Sequence[Any]],
) -> None:
    labels = {
        "segmented_reference": "16-segment reference",
        "equivalent_reversible": "reversible equivalent law",
        "legacy_hysteretic": "legacy HystereticSM carrier",
    }
    styles = {
        "segmented_reference": dict(color="#202020", linewidth=2.4),
        "equivalent_reversible": dict(color="#d1495b", linewidth=2.0, linestyle="--"),
        "legacy_hysteretic": dict(color="#6a4c93", linewidth=1.6, linestyle=":"),
    }
    figure, axis = plt.subplots(figsize=(7.4, 4.8))
    for name, history in histories.items():
        axis.plot(
            [point.strain * 100.0 for point in history],
            [point.axial_force / 1000.0 for point in history],
            label=labels[name],
            **styles[name],
        )
    axis.axhline(0.0, color="black", linewidth=0.7)
    axis.axvline(0.0, color="black", linewidth=0.7)
    axis.set_xlabel("Axial strain (%)")
    axis.set_ylabel("Axial force, tension positive (kN)")
    axis.set_title("Pre-yield compression-unloading acceptance check")
    axis.legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_convergence(path: Path, summary: Mapping[str, Any]) -> None:
    rows = summary.get("convergence", [])
    mesh = [row for row in rows if row["study"] == "mesh"]
    step = [row for row in rows if row["study"] == "step"]
    if not mesh:
        return
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.4))
    axes[0].plot(
        [row["divisions"] for row in mesh],
        [row["peak_force_n"] / 1000.0 for row in mesh],
        marker="o",
        color="#00798c",
    )
    axes[0].set_xlabel("Member divisions")
    axes[0].set_ylabel("Peak force (kN)")
    axes[0].set_title("Mesh convergence")
    axes[0].set_xticks([row["divisions"] for row in mesh])
    axes[1].plot(
        [row["steps"] for row in step],
        [row["peak_shortening_m"] * 1000.0 for row in step],
        marker="o",
        color="#d1495b",
    )
    axes[1].set_xlabel("Displacement-control steps")
    axes[1].set_ylabel("Shortening at peak (mm)")
    axes[1].set_title("Step-size convergence")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def plot_actual_member_validation(path: Path, summary: Mapping[str, Any]) -> None:
    rows = summary.get("actual_member_validation", [])
    if not rows:
        return
    figure, axis = plt.subplots(figsize=(7.4, 4.8))
    positions = list(range(len(rows)))
    axis.bar(
        [position - 0.18 for position in positions],
        [abs(row["normalized_rmse_percent"]) for row in rows],
        width=0.36,
        color="#00798c",
        label="NRMSE",
    )
    axis.bar(
        [position + 0.18 for position in positions],
        [abs(row["monotonic_work_error_percent"]) for row in rows],
        width=0.36,
        color="#d1495b",
        label="monotonic-work error",
    )
    axis.set_xticks(
        positions,
        [f"{row['representative']}\nL={row['length_m']:.3f} m" for row in rows],
    )
    axis.set_ylabel("Absolute error (%)")
    axis.set_title("Validation on actual Z30103A6 L125x8 member lengths")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def create_all_figures(
    destination: Path,
    member: MemberProperties,
    curves: Mapping[str, Sequence[PushoverPoint]],
    materials: Mapping[str, EquivalentImperfectionMaterial],
    summary: Mapping[str, Any],
    *,
    cyclic_histories: Mapping[str, Sequence[Any]],
) -> None:
    _style()
    plot_pushover(destination / "pushover_comparison.png", curves, summary)
    plot_normalized_pushover(destination / "normalized_pushover.png", member, curves)
    plot_material_backbones(destination / "material_backbones.png", materials)
    plot_sensitivity(destination / "imperfection_sensitivity.png", summary)
    plot_pre_yield_unloading(destination / "pre_yield_unloading.png", cyclic_histories)
    plot_convergence(destination / "convergence_study.png", summary)
    plot_actual_member_validation(destination / "actual_member_validation.png", summary)
