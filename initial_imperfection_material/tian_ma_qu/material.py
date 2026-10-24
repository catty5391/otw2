"""Incremental, event-exact prototype of the Tian–Ma–Qu member law.

This is NOT a verified implementation of the original VUMAT.  The principal
branches follow Liu, Tian, Ma and Qu (2022), DOI 10.1016/j.jobe.2021.103798,
Eqs. (1)–(4), as publicly transcribed from the article.  The source transcript
requires three explicit interpretation choices: compression stresses/slopes
are negative despite positive table coefficients; GH starts at epsilon_G
(not the printed/transcribed epsilon_A); the repeated last interval in Eq. (4)
is read as the interval below epsilon_L.  No original source code is available.

Additional, unverified closure rules are deliberately exposed: an incomplete
reversal retraces its current branch until its origin; subsequent compression
peaks use eta times the FIRST peak, not eta raised to the cycle number; a
non-positive constant tail prevents extrapolated compression becoming tension.
No fracture, damage deletion, or steel-fiber plastic strain law is implemented.
The input/output strain is axial member deformation divided by original length,
and stress is axial force divided by original area.  It is not a fiber law.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class TMQParameters:
    """All dimensional inputs use Pa; coefficient inputs use positive magnitudes.

    E, rho, gamma and zeta were not located in the accessible paper tables.
    Callers must supply them explicitly and identify their provenance.  A
    positive residual_compression_ratio is a user assumption, not a published
    TMQ residual-strength rule.  Zero extends the line to zero compression.
    """

    elastic_modulus: float
    yield_stress: float
    phi: float
    rho: float
    alpha: float
    beta: float
    gamma: float
    tau: float
    mu: float
    nu: float
    zeta: float
    eta: float
    theta: float
    kappa: float
    residual_compression_ratio: float = 0.0
    provenance: str = "literature-informed prototype; unverified closure rules"

    def __post_init__(self) -> None:
        for name in (
            "elastic_modulus", "yield_stress", "phi", "alpha", "beta",
            "gamma", "tau", "mu", "nu", "zeta", "eta", "theta", "kappa",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isfinite(self.rho) or not 0 <= self.rho < 1:
            raise ValueError("rho must lie in [0, 1)")
        for name in ("phi", "eta"):
            if getattr(self, name) > 1:
                raise ValueError(f"{name} must not exceed one")
        if not 0 < self.gamma < 1 or not 0 < self.zeta < 1:
            raise ValueError("gamma and zeta must lie strictly between zero and one")
        if self.nu <= self.mu:
            raise ValueError("nu must exceed mu to represent the rising HI stiffness")
        if not isfinite(self.residual_compression_ratio) or not (
            0 <= self.residual_compression_ratio < self.gamma
        ):
            raise ValueError("residual_compression_ratio must lie in [0, gamma)")

    @property
    def yield_strain(self) -> float:
        return self.yield_stress / self.elastic_modulus

    @property
    def first_buckling_stress(self) -> float:
        return -self.phi * self.yield_stress

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Curve:
    """Continuous piecewise linear curve; knots are ordered by strain."""

    identifier: int
    knots: tuple[tuple[float, float], ...]
    slopes: tuple[float, ...]
    stages: tuple[str, ...]
    origin: float | None = None
    forward: int = 0
    parent: _Curve | None = None
    buckling_strain: float | None = None
    buckling_stress: float | None = None
    secant_modulus: float | None = None

    def response(self, strain: float, direction: int) -> tuple[float, float, str]:
        positions = tuple(point[0] for point in self.knots)
        index = (
            bisect_left(positions, strain) if direction < 0
            else bisect_right(positions, strain)
        )
        anchor = self.knots[max(0, index - 1)]
        tangent = self.slopes[index]
        return anchor[1] + tangent * (strain - anchor[0]), tangent, self.stages[index]


@dataclass
class _State:
    strain: float
    stress: float
    tangent: float
    stage: str
    direction: int
    curve: _Curve
    next_curve_identifier: int = 1
    buckled_curves: set[int] = field(default_factory=set)
    min_strain: float = 0.0
    min_strain_stress: float = 0.0
    max_strain: float = 0.0
    max_strain_stress: float = 0.0
    external_work_density: float = 0.0
    accumulated_absolute_strain: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    def clone(self):
        # Curves (including parent links) are immutable. Only history containers
        # need copying; recursively copying the curve tree at every FE iteration
        # is both unnecessary and increasingly expensive under cycling.
        return replace(self, buckled_curves=set(self.buckled_curves),
                       events=deepcopy(self.events))


class TianMaQuPrototype:
    """Pure-Python member hysteresis state machine, independent of OpenSees.

    Every trial starts from the last committed state.  A trial can cross any
    number of branch corners; all corner contributions enter work exactly.
    Multiple requested trial values therefore cannot accumulate history.
    Commit/revert/copy semantics are suitable for an eventual constitutive
    adapter, but this class itself is not an OpenSees registered material.
    """

    model_status = "literature_informed_prototype_not_experimentally_validated"
    closure_assumptions = (
        "Touching a virgin elastic limit without crossing it remains reversible.",
        "Minor reversals retrace the active branch to its origin (unverified).",
        "All later buckling peaks equal eta times the initial peak (Eq. 4 reading).",
        "Compression beyond the final zero/residual point is constant (unverified).",
        "No damage accumulation, fracture, deletion or fiber plastic strain is modeled.",
    )

    def __init__(self, parameters: TMQParameters):
        self.parameters = parameters
        self.revert_to_start()

    def _compression_knots(
        self, origin_strain: float, origin_stress: float, subsequent: bool,
    ) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], tuple[str, ...], float, float]:
        p = self.parameters
        elastic = p.elastic_modulus
        peak = p.first_buckling_stress * (p.eta if subsequent else 1.0)
        first_slope = -(p.theta if subsequent else p.alpha) * elastic
        second_slope = -(p.kappa if subsequent else p.beta) * elastic
        e_peak = origin_strain + (peak - origin_stress) / elastic
        middle = p.gamma * peak
        e_middle = e_peak + (middle - peak) / first_slope
        residual = p.residual_compression_ratio * peak
        e_residual = e_middle + (residual - middle) / second_slope
        prefix = "subsequent" if subsequent else "first"
        return (
            ((e_residual, residual), (e_middle, middle), (e_peak, peak)),
            (0.0, second_slope, first_slope, elastic),
            ("compression_tail_extension", f"{prefix}_compression_softening_2",
             f"{prefix}_compression_softening_1", "elastic"),
            e_peak, peak,
        )

    def _initial_state(self) -> _State:
        p = self.parameters
        knots, slopes, stages, peak_strain, peak_stress = self._compression_knots(0, 0, False)
        curve = _Curve(
            identifier=0, knots=knots + ((p.yield_strain, p.yield_stress),),
            slopes=slopes + (p.rho * p.elastic_modulus,),
            stages=stages + ("tension_hardening",),
            buckling_strain=peak_strain, buckling_stress=peak_stress,
        )
        return _State(0.0, 0.0, p.elastic_modulus, "elastic", 0, curve)

    def _new_compression_curve(self, state: _State) -> _Curve:
        knots, slopes, stages, peak_strain, peak_stress = self._compression_knots(
            state.strain, state.stress, bool(state.buckled_curves),
        )
        curve = _Curve(
            identifier=state.next_curve_identifier,
            knots=knots + ((state.strain, state.stress),),
            slopes=slopes + (self.parameters.elastic_modulus,),
            stages=stages[:-1] + ("compression_elastic", "compression_elastic"),
            origin=state.strain, forward=-1, parent=state.curve,
            buckling_strain=peak_strain, buckling_stress=peak_stress,
        )
        state.next_curve_identifier += 1
        return curve

    def _new_tension_curve(self, state: _State) -> _Curve:
        p = self.parameters
        span = state.max_strain - state.min_strain
        if span <= 0:
            raise ValueError("A buckled member needs distinct historical strain extrema")
        secant = (state.max_strain_stress - state.min_strain_stress) / span
        if not isfinite(secant) or secant <= 0:
            raise ValueError("Historical E_FB is non-positive; this path is outside the prototype")
        unload = p.tau * secant
        pinched = p.mu * secant
        reload = p.nu * secant
        e_g = state.strain - state.stress / unload
        e_h = e_g + p.zeta * p.yield_stress / pinched
        e_i = e_h + (1 - p.zeta) * p.yield_stress / reload
        curve = _Curve(
            identifier=state.next_curve_identifier,
            knots=((state.strain, state.stress), (e_g, 0.0),
                   (e_h, p.zeta * p.yield_stress), (e_i, p.yield_stress)),
            slopes=(unload, unload, pinched, reload, p.rho * p.elastic_modulus),
            stages=("compression_unloading", "compression_unloading",
                    "tension_pinching", "tension_reloading", "tension_hardening"),
            origin=state.strain, forward=1, parent=state.curve,
            secant_modulus=secant,
        )
        state.next_curve_identifier += 1
        return curve

    @staticmethod
    def _update_extrema(state: _State) -> None:
        if state.strain < state.min_strain:
            state.min_strain = state.strain
            state.min_strain_stress = state.stress
        if state.strain > state.max_strain:
            state.max_strain = state.strain
            state.max_strain_stress = state.stress

    def set_trial_strain(self, strain: float, strain_rate: float = 0.0) -> int:
        """Set a rate-independent trial from committed history; return zero.

        The rate argument is accepted for adapter compatibility and does not
        alter this quasi-static law.  Invalid trials leave the old trial intact.
        """
        strain = float(strain)
        if not isfinite(strain) or not isfinite(float(strain_rate)):
            raise ValueError("strain and strain_rate must be finite")
        state = self._committed.clone()
        state.events = []
        difference = strain - state.strain
        if difference == 0:
            self._trial = state
            return 0
        direction = 1 if difference > 0 else -1
        if state.direction and direction != state.direction:
            state.events.append({"event": "reversal", "strain": state.strain,
                                 "stress": state.stress, "from_stage": state.stage})
            if state.direction > 0 and state.stage == "tension_hardening":
                state.curve = self._new_compression_curve(state)
            elif state.direction < 0 and (
                "compression_softening" in state.stage or state.stage == "compression_tail_extension"
            ) and not (
                state.curve.buckling_strain == state.strain
                and state.curve.identifier not in state.buckled_curves
            ):
                # Merely touching the compression limit does not traverse a
                # softening segment.  Reversal there remains elastic; otherwise
                # tau*E_FB would create spurious residual strain at first touch.
                state.curve = self._new_tension_curve(state)
        state.direction = direction
        # Events are geometrical branch corners; no artificial fixed substep is
        # needed, and an arbitrarily large trial can traverse all of them.
        for _ in range(10000):
            if state.strain == strain:
                break
            curve = state.curve
            if curve.origin is not None and direction == -curve.forward:
                beyond_origin = direction * (state.strain - curve.origin) >= 0
                if beyond_origin:
                    if curve.parent is None:
                        raise RuntimeError("Missing parent at a retraced branch origin")
                    state.curve = curve.parent
                    state.events.append({"event": "minor_return", "strain": state.strain,
                                         "stress": state.stress})
                    continue
            candidates = [strain]
            for position, _ in curve.knots:
                if direction * (position - state.strain) > 0 and direction * (strain - position) >= 0:
                    candidates.append(position)
            endpoint = min(candidates, key=lambda item: abs(item - state.strain))
            previous_strain, previous_stress = state.strain, state.stress
            stress, tangent, stage = curve.response(endpoint, direction)
            delta = endpoint - previous_strain
            state.external_work_density += 0.5 * (previous_stress + stress) * delta
            state.accumulated_absolute_strain += abs(delta)
            state.strain, state.stress = endpoint, stress
            state.tangent, state.stage = tangent, stage
            self._update_extrema(state)
            if (
                direction < 0 and curve.buckling_strain is not None
                and previous_strain >= curve.buckling_strain > endpoint
                and curve.identifier not in state.buckled_curves
            ):
                state.buckled_curves.add(curve.identifier)
                state.events.append({"event": "buckling", "strain": curve.buckling_strain,
                                     "stress": curve.buckling_stress,
                                     "buckling_count": len(state.buckled_curves)})
            if endpoint != strain:
                state.events.append({"event": "corner", "strain": endpoint,
                                     "stress": stress, "to_stage": stage})
        else:
            raise RuntimeError("Too many branch events in a single trial")
        self._trial = state
        return 0

    def get_strain(self) -> float:
        return self._trial.strain

    def get_stress(self) -> float:
        return self._trial.stress

    def get_tangent(self) -> float:
        return self._trial.tangent

    def get_initial_tangent(self) -> float:
        return self.parameters.elastic_modulus

    def commit_state(self) -> int:
        self._committed = self._trial.clone()
        return 0

    def revert_to_last_commit(self) -> int:
        self._trial = self._committed.clone()
        return 0

    def revert_to_start(self) -> int:
        self._committed = self._initial_state()
        self._trial = self._committed.clone()
        return 0

    def get_copy(self) -> TianMaQuPrototype:
        result = object.__new__(type(self))
        result.parameters = self.parameters
        result._committed = self._committed.clone()
        result._trial = self._trial.clone()
        return result

    def get_state(self) -> dict[str, Any]:
        """Return a detached snapshot; buckling_count counts entered softening paths."""
        state = self._trial
        return {
            "strain": state.strain, "stress": state.stress, "tangent": state.tangent,
            "stage": state.stage, "direction": state.direction,
            "buckling_count": len(state.buckled_curves),
            "min_strain": state.min_strain, "stress_at_min_strain": state.min_strain_stress,
            "max_strain": state.max_strain, "stress_at_max_strain": state.max_strain_stress,
            "external_work_density": state.external_work_density,
            "accumulated_absolute_strain": state.accumulated_absolute_strain,
            "active_secant_modulus": state.curve.secant_modulus,
            "events": deepcopy(state.events), "model_status": self.model_status,
            "damage_model_enabled": False, "fracture_or_deletion_enabled": False,
        }

    # Friendly aliases; the snake_case methods above are the canonical API.
    commit = commit_state
    revert = revert_to_last_commit
    reset = revert_to_start
    copy = get_copy

