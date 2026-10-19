from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FormFindingTrial:
    initial_force: float
    sag: float
    error: float
    success: bool
    final_coords: np.ndarray
    axial_forces: np.ndarray


@dataclass(frozen=True)
class FormFindingResult:
    target_sag: float
    achieved_sag: float
    error: float
    initial_force: float
    iterations: int
    force_lower: float
    force_upper: float
    tolerance: float
    conductor_length: float
    final_coords: np.ndarray
    axial_forces: np.ndarray
    history: tuple[dict[str, Any], ...]

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("final_coords")
        data.pop("axial_forces")
        data.pop("history")
        return data


class TransmissionLineFormFinder:
    """Find the initial cable force that gives a target gravity sag.

    Every trial is an isolated OpenSees model. ``initial_force`` is the
    generalized axial force supplied to ``InitStressMaterial`` because the
    base elastic material stiffness is EA rather than E.
    """

    def __init__(
        self,
        *,
        horizontal_span: float,
        start_elevation: float,
        end_elevation: float,
        axial_stiffness: float,
        mass_per_length: float,
        gravity: float = 9.81,
        n_seg: int = 60,
        initial_sag: float = 0.2,
        nonaxial_stiffness_ratio: float = 1.0e-8,
        load_steps: int = 100,
    ) -> None:
        self.horizontal_span = self._positive(horizontal_span, "horizontal_span")
        self.start_elevation = self._finite(start_elevation, "start_elevation")
        self.end_elevation = self._finite(end_elevation, "end_elevation")
        self.axial_stiffness = self._positive(axial_stiffness, "axial_stiffness")
        self.mass_per_length = self._positive(mass_per_length, "mass_per_length")
        self.gravity = self._positive(gravity, "gravity")
        self.n_seg = self._positive_int(n_seg, "n_seg")
        self.initial_sag = self._positive(initial_sag, "initial_sag")
        self.nonaxial_stiffness_ratio = self._positive(
            nonaxial_stiffness_ratio, "nonaxial_stiffness_ratio"
        )
        self.load_steps = self._positive_int(load_steps, "load_steps")

    @staticmethod
    def _finite(value: Any, name: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} 必须是有限数值。")
        return number

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        number = cls._finite(value, name)
        if number <= 0.0:
            raise ValueError(f"{name} 必须大于 0。")
        return number

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        number = int(value)
        if number < 1 or float(value) != number:
            raise ValueError(f"{name} 必须是正整数。")
        return number

    @staticmethod
    def calculate_sag(coords: np.ndarray, start_z: float, end_z: float, span: float) -> float:
        x = coords[:, 0]
        chord_z = start_z + (end_z - start_z) * x / span
        return float(np.max(chord_z - coords[:, 2]))

    def run_trial(self, initial_force: float) -> FormFindingTrial:
        import openseespy.opensees as ops

        force = self._positive(initial_force, "initial_force")
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)

        element_length = self.horizontal_span / self.n_seg
        nonaxial = max(
            self.nonaxial_stiffness_ratio * self.axial_stiffness * element_length**2,
            1.0e-12,
        )
        ops.uniaxialMaterial("Elastic", 1, self.axial_stiffness)
        ops.uniaxialMaterial("Elastic", 2, nonaxial)
        ops.uniaxialMaterial("Elastic", 3, nonaxial)
        ops.uniaxialMaterial("Elastic", 4, nonaxial)
        ops.uniaxialMaterial("InitStressMaterial", 5, 1, force)
        ops.section("Aggregator", 1, 5, "P", 2, "Mz", 3, "My", 4, "T")

        coords: list[tuple[float, float, float]] = []
        for index in range(self.n_seg + 1):
            ratio = index / self.n_seg
            x = self.horizontal_span * ratio
            chord_z = self.start_elevation + (self.end_elevation - self.start_elevation) * ratio
            z = chord_z - 4.0 * self.initial_sag * ratio * (1.0 - ratio)
            coord = (x, 0.0, z)
            coords.append(coord)
            ops.node(index + 1, *coord)
            if index in (0, self.n_seg):
                ops.fix(index + 1, 1, 1, 1, 1, 1, 1)
            else:
                ops.fix(index + 1, 0, 0, 0, 1, 1, 1)

        segment_lengths = [math.dist(first, second) for first, second in zip(coords, coords[1:])]
        tributary_lengths = [0.0] * (self.n_seg + 1)
        tributary_lengths[0] = 0.5 * segment_lengths[0]
        tributary_lengths[-1] = 0.5 * segment_lengths[-1]
        for index in range(1, self.n_seg):
            tributary_lengths[index] = 0.5 * (
                segment_lengths[index - 1] + segment_lengths[index]
            )

        for index, tributary_length in enumerate(tributary_lengths, start=1):
            mass = self.mass_per_length * tributary_length
            ops.mass(index, mass, mass, mass, 0.0, 0.0, 0.0)
        for index in range(self.n_seg):
            ops.element("corotTrussSection", index + 1, index + 1, index + 2, 1)

        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        weight_per_length = self.mass_per_length * self.gravity
        for index, tributary_length in enumerate(tributary_lengths, start=1):
            ops.load(index, 0.0, 0.0, -weight_per_length * tributary_length, 0.0, 0.0, 0.0)

        ops.constraints("Plain")
        ops.numberer("RCM")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1.0e-8, 60)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0 / self.load_steps)
        ops.analysis("Static")

        success = True
        for _ in range(self.load_steps):
            if ops.analyze(1) == 0:
                continue
            ops.test("NormDispIncr", 1.0e-7, 100)
            ops.algorithm("KrylovNewton")
            ops.integrator("LoadControl", 0.1 / self.load_steps)
            if ops.analyze(10) != 0:
                success = False
                break
            ops.algorithm("Newton")
            ops.integrator("LoadControl", 1.0 / self.load_steps)

        final_coords = []
        for node_tag in range(1, self.n_seg + 2):
            coord = np.asarray(ops.nodeCoord(node_tag), dtype=float)
            displacement = np.asarray(ops.nodeDisp(node_tag), dtype=float)
            final_coords.append(coord + displacement[:3])
        final_coords_array = np.asarray(final_coords, dtype=float)
        sag = self.calculate_sag(
            final_coords_array,
            self.start_elevation,
            self.end_elevation,
            self.horizontal_span,
        )
        axial_forces = []
        for element_tag in range(1, self.n_seg + 1):
            response = ops.eleResponse(element_tag, "axialForce")
            axial_forces.append(float(response[0]) if response else math.nan)

        return FormFindingTrial(
            initial_force=force,
            sag=sag,
            error=math.nan,
            success=success,
            final_coords=final_coords_array,
            axial_forces=np.asarray(axial_forces, dtype=float),
        )

    def solve(
        self,
        *,
        target_sag: float,
        force_lower: float,
        force_upper: float,
        tolerance: float = 1.0e-3,
        max_iterations: int = 40,
    ) -> FormFindingResult:
        target = self._positive(target_sag, "target_sag")
        lower = self._positive(force_lower, "force_lower")
        upper = self._positive(force_upper, "force_upper")
        tolerance_value = self._positive(tolerance, "tolerance")
        max_iter = self._positive_int(max_iterations, "max_iterations")
        if lower >= upper:
            raise ValueError("force_lower 必须小于 force_upper。")

        lower_trial = self.run_trial(lower)
        upper_trial = self.run_trial(upper)
        if not lower_trial.success or not upper_trial.success:
            raise RuntimeError("找形边界对应的静力分析未收敛，请调整初始力边界。")
        if not (lower_trial.sag >= target >= upper_trial.sag):
            raise ValueError(
                "初始力边界没有包络目标弧垂："
                f"force_lower={lower:.6g} N → {lower_trial.sag:.6g} m，"
                f"force_upper={upper:.6g} N → {upper_trial.sag:.6g} m，"
                f"target={target:.6g} m。"
            )

        history: list[dict[str, Any]] = [
            {"iteration": 0, "boundary": "lower", "initial_force": lower, "sag": lower_trial.sag, "error": lower_trial.sag - target},
            {"iteration": 0, "boundary": "upper", "initial_force": upper, "sag": upper_trial.sag, "error": upper_trial.sag - target},
        ]
        best: FormFindingTrial | None = None
        for iteration in range(1, max_iter + 1):
            force = 0.5 * (lower + upper)
            trial = self.run_trial(force)
            if not trial.success:
                raise RuntimeError(f"找形在第 {iteration} 次迭代时未收敛。")
            error = trial.sag - target
            history.append(
                {"iteration": iteration, "boundary": "trial", "initial_force": force, "sag": trial.sag, "error": error}
            )
            best = FormFindingTrial(
                initial_force=trial.initial_force,
                sag=trial.sag,
                error=error,
                success=True,
                final_coords=trial.final_coords,
                axial_forces=trial.axial_forces,
            )
            if abs(error) <= tolerance_value:
                break
            if error > 0.0:
                lower = force
            else:
                upper = force
        if best is None:
            raise RuntimeError("找形没有产生有效结果。")

        return FormFindingResult(
            target_sag=target,
            achieved_sag=best.sag,
            error=best.error,
            initial_force=best.initial_force,
            iterations=len(history) - 2,
            force_lower=float(force_lower),
            force_upper=float(force_upper),
            tolerance=tolerance_value,
            conductor_length=float(
                sum(math.dist(first, second) for first, second in zip(best.final_coords, best.final_coords[1:]))
            ),
            final_coords=best.final_coords,
            axial_forces=best.axial_forces,
            history=tuple(history),
        )
