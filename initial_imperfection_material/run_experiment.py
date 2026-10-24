"""Command-line entry point for the isolated single-member experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experiment import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the equivalent imperfection material experiment.")
    parser.add_argument("--output", type=Path, default=None, help="Result directory")
    parser.add_argument("--length", type=float, default=3.0, help="Member length in metres")
    parser.add_argument(
        "--imperfection-ratio",
        type=float,
        default=1.0 / 1000.0,
        help="Initial bow e0/L",
    )
    parser.add_argument("--steps", type=int, default=800, help="Displacement-control steps")
    parser.add_argument("--reference-divisions", type=int, default=16)
    parser.add_argument(
        "--skip-convergence",
        action="store_true",
        help="Skip the additional 4/8/16 mesh and step-size study",
    )
    parser.add_argument(
        "--skip-actual-validation",
        action="store_true",
        help="Skip minimum/median/maximum actual L125x8 member validation",
    )
    parser.add_argument("--maximum-strain", type=float, default=0.03)
    arguments = parser.parse_args()
    summary = run_experiment(
        arguments.output,
        imperfection_ratio=arguments.imperfection_ratio,
        length=arguments.length,
        maximum_strain=arguments.maximum_strain,
        steps=arguments.steps,
        reference_divisions=arguments.reference_divisions,
        run_convergence=not arguments.skip_convergence,
        run_actual_validation=not arguments.skip_actual_validation,
    )
    print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
