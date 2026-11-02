"""Analytical curved envelopes inspired by Liu et al., TWS183:110335 (2023).

NOT an exact reproduction of the authors' VUMAT. Compression sign convention,
H/I closure, small reversals and the meaning of equivalent plastic strain need
independent verification. All constitutive stresses/tangents are evaluated from
equations; no plotting spline or interpolated polygon is used by OpenSees.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from math import exp, isfinite, pi, sqrt
from copy import deepcopy

import numpy as np


class PHMDomainError(ValueError):
    """A trial is beyond the declared range; no extrapolated failure claim."""


@dataclass(frozen=True)
class AnglePHMParameters:
    elastic_modulus: float
    yield_stress: float
    lambda_n: float
    phi: float
    sigma_a: float
    eta1: float
    eta2: float
    hardening_ratio: float
    unloading_exponent: float
    reload_stress_fraction: float
    reload_span_yield_strains: float
    reload_linear_ratio: float
    max_abs_strain: float
    degradation_coefficient: float = 69.896
    degradation_power: float = 1.566
    provenance: str = "conditional curve prototype; no tower qualification"

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "provenance":
                continue
            if not isfinite(value):
                raise ValueError(f"Nonfinite {name}")
        for name in ("elastic_modulus", "yield_stress", "lambda_n", "eta1",
                     "unloading_exponent", "reload_span_yield_strains", "reload_linear_ratio",
                     "max_abs_strain", "degradation_coefficient", "degradation_power"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.phi <= 1 or not 0 <= self.hardening_ratio < 1:
            raise ValueError("Invalid peak/hardening ratio")
        if not -self.phi*self.yield_stress < self.sigma_a <= 0:
            raise ValueError("Compression asymptote must lie between peak and zero")
        if not 0 < self.reload_stress_fraction < 1:
            raise ValueError("H stress fraction must be in (0,1)")
        if self.eta1 + 1.5*self.eta2*sqrt(2*self.max_abs_strain) <= 0:
            raise ValueError("Postbuckling regression reverses tangent inside declared range")

    @property
    def yield_strain(self):
        return self.yield_stress/self.elastic_modulus

    @property
    def first_buckling_stress(self):
        return -self.phi*self.yield_stress

    @property
    def xi1(self):
        # Paper Eq12 overlaps at 1.7; explicitly assign equality to middle arm.
        a = 1.1 if self.lambda_n <= .6 else (1.718*self.lambda_n+.075 if self.lambda_n <= 1.7 else 3.)
        return 1/(a*self.elastic_modulus)

    def degradation(self, plastic_max):
        if plastic_max < 0:
            raise ValueError("Negative historical tensile plastic strain")
        return (1+self.degradation_coefficient*self.lambda_n*plastic_max)**(-self.degradation_power)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_regression(cls, *, elastic_modulus, yield_stress, slenderness, **closures):
        """Paper Eqs6/7: sigma_a is interpreted in MPa, compression negative.

        Hardening, H/I closure and range are deliberately required inputs.
        unloading_exponent=3 reproduces printed Eq8; another value is a fit.
        """
        n = slenderness/pi*sqrt(yield_stress/elastic_modulus)
        a = 1.028+.196*n+n*n
        return cls(elastic_modulus, yield_stress, n,
                   2/(a+sqrt(a*a-4*n*n)),
                   (0.805-37.902*exp(-.887*n))*1e6,
                   -180.877+532.191*exp(-.240*n),
                   63.913-683.403*exp(-.455*n), **closures)


def compression_response(p, strain, peak_strain, peak_stress):
    """Signed softening interpretation of Eq4, with exact analytical tangent."""
    d = peak_strain-strain
    if d < 0:
        return peak_stress+p.elastic_modulus*(strain-peak_strain), p.elastic_modulus
    if not peak_stress < p.sigma_a <= 0:
        raise PHMDomainError("Degraded peak reached fixed asymptote: outside calibrated law")
    rate = p.eta1+1.5*p.eta2*sqrt(d)
    if rate <= 0:
        raise PHMDomainError("Postbuckling curve leaves monotone softening domain")
    decay = exp(-(p.eta1+p.eta2*sqrt(d))*d)
    return p.sigma_a+(peak_stress-p.sigma_a)*decay, (peak_stress-p.sigma_a)*decay*rate


def reload_response(strain, e_g, e_h, sigma_h, xi1):
    """Exact integral of Eq11 GH; Eq13 makes sigma(G)=0, sigma(H)=sigmaH."""
    if e_h <= e_g or sigma_h <= 0 or xi1 <= 0:
        raise ValueError("Invalid GH endpoints")
    d = e_h-strain
    xi2 = 1/sigma_h-xi1/(e_h-e_g)
    denominator = xi1+xi2*d
    if denominator <= 0:
        raise PHMDomainError("Reloading rational curve pole")
    return sigma_h-d/denominator, xi1/(denominator*denominator)


@dataclass(frozen=True)
class _Curve:
    kind: str
    parameters: AnglePHMParameters
    identifier: int
    knots: tuple[float, ...]
    peak_strain: float | None = None
    peak_stress: float | None = None
    origin: float | None = None
    origin_stress: float = 0.
    forward: int = 0
    parent: _Curve | None = None
    unloading_stiffness: float = 0.

    def response(self, e, direction):
        p = self.parameters
        if self.kind in ("initial", "compression"):
            if self.kind == "initial" and (e > p.yield_strain or (e == p.yield_strain and direction > 0)):
                return p.yield_stress+p.hardening_ratio*p.elastic_modulus*(e-p.yield_strain), p.hardening_ratio*p.elastic_modulus, "tension_hardening"
            if e < self.peak_strain or (e == self.peak_strain and direction < 0):
                s, k = compression_response(p,e,self.peak_strain,self.peak_stress)
                return s,k,"compression_curve"
            return self.peak_stress+p.elastic_modulus*(e-self.peak_strain),p.elastic_modulus,"elastic"
        eg,eh,ei = self.knots
        sh = p.reload_stress_fraction*p.yield_stress
        if e < eg or (e == eg and direction < 0):
            return self.origin_stress+self.unloading_stiffness*(e-self.origin),self.unloading_stiffness,"compression_unloading"
        if e < eh or (e == eh and direction < 0):
            s,k=reload_response(e,eg,eh,sh,p.xi1)
            return s,k,"curved_tension_reloading"
        if e < ei or (e == ei and direction < 0):
            return sh+p.reload_linear_ratio*p.elastic_modulus*(e-eh),p.reload_linear_ratio*p.elastic_modulus,"tension_restoring"
        return p.yield_stress+p.hardening_ratio*p.elastic_modulus*(e-ei),p.hardening_ratio*p.elastic_modulus,"tension_hardening"


@dataclass
class _State:
    strain: float
    stress: float
    tangent: float
    stage: str
    curve: _Curve
    direction: int = 0
    plastic_max: float = 0.
    work_density: float = 0.
    next_identifier: int = 1
    buckled_curves: set = field(default_factory=set)
    events: list = field(default_factory=list)

    def clone(self):
        return replace(self,buckled_curves=set(self.buckled_curves),events=deepcopy(self.events))


_GX,_GW = np.polynomial.legendre.leggauss(16)


class LiuAnglePHM:
    """Curved member law with immutable branch tree and trial/commit separation.

    H uses a fitted or assumed stress fraction and G-H strain span. I follows
    a separately supplied chi. A minimum I location preserves historic tensile
    plastic extension. Minor reversals retrace a branch to its origin. These
    explicit closures are not established by the original paper's equations.
    No fracture is guessed: exceeding max_abs_strain raises PHMDomainError.
    """
    model_status = "conditional_liu_curved_angle_prototype_not_validated"

    def __init__(self, parameters):
        self.parameters=parameters
        self.revert_to_start()

    def _compression_curve(self,s):
        p=self.parameters
        peak=p.first_buckling_stress*p.degradation(s.plastic_max)
        ec=s.strain+(peak-s.stress)/p.elastic_modulus
        curve=_Curve("compression",p,s.next_identifier,(ec,),ec,peak,
                     s.strain,s.stress,-1,s.curve)
        s.next_identifier+=1
        return curve

    def _reload_curve(self,s):
        p=self.parameters
        sft=-p.yield_stress+p.hardening_ratio*p.elastic_modulus*(s.strain-p.yield_strain)
        ratio=s.stress/sft
        if not 0 < ratio <= 1:
            raise PHMDomainError("Unloading stress ratio outside (0,1]")
        ku=p.elastic_modulus*ratio**p.unloading_exponent
        eg=s.strain-s.stress/ku
        sh=p.reload_stress_fraction*p.yield_stress
        hi=(p.yield_stress-sh)/(p.reload_linear_ratio*p.elastic_modulus)
        eh=max(eg+p.reload_span_yield_strains*p.yield_strain, s.plastic_max+p.yield_strain-hi)
        curve=_Curve("reload",p,s.next_identifier,(eg,eh,eh+hi),origin=s.strain,
                     origin_stress=s.stress,forward=1,parent=s.curve,unloading_stiffness=ku)
        s.next_identifier+=1
        return curve

    def set_trial_strain(self,strain,strain_rate=0.):
        e=float(strain)
        if not isfinite(e) or not isfinite(strain_rate):
            raise ValueError("Nonfinite trial")
        if abs(e)>self.parameters.max_abs_strain:
            raise PHMDomainError("Trial exceeds declared strain range; no fracture model")
        s=self._committed.clone();s.events=[]
        if e==s.strain:
            self._trial=s;return 0
        direction=1 if e>s.strain else -1
        if s.direction and direction!=s.direction:
            s.events.append(dict(event="reversal",strain=s.strain,stress=s.stress))
            if s.direction>0 and s.stage=="tension_hardening":
                s.curve=self._compression_curve(s)
            elif s.direction<0 and s.stage=="compression_curve" and s.curve.identifier in s.buckled_curves:
                s.curve=self._reload_curve(s)
        s.direction=direction
        for _ in range(10000):
            if s.strain==e:break
            c=s.curve
            if c.origin is not None and direction==-c.forward and direction*(s.strain-c.origin)>=0:
                s.curve=c.parent
                s.events.append(dict(event="minor_return",strain=s.strain,stress=s.stress))
                continue
            candidates=[e]
            for k in c.knots+((c.origin,) if c.origin is not None else ()):
                if direction*(k-s.strain)>0 and direction*(e-k)>=0:
                    candidates.append(k)
            endpoint=min(candidates,key=lambda k:abs(k-s.strain))
            previous=s.strain
            # Constitutive response/tangent are analytic; quadrature only records work.
            half=(endpoint-previous)/2;mid=(endpoint+previous)/2
            s.work_density+=half*sum(w*c.response(mid+half*x,direction)[0] for x,w in zip(_GX,_GW))
            stress,tangent,stage=c.response(endpoint,direction)
            s.strain,s.stress,s.tangent,s.stage=endpoint,stress,tangent,stage
            if c.peak_strain is not None and direction<0 and previous>=c.peak_strain>endpoint and c.identifier not in s.buckled_curves:
                s.buckled_curves.add(c.identifier)
                s.events.append(dict(event="buckling",strain=c.peak_strain,stress=c.peak_stress,plastic_max=s.plastic_max))
            if direction>0 and stage=="tension_hardening":
                s.plastic_max=max(s.plastic_max,endpoint-stress/self.parameters.elastic_modulus,0.)
            if endpoint in c.knots:
                s.events.append(dict(event="corner",strain=endpoint,stress=stress,stage=stage))
        else:
            raise RuntimeError("Branch event iteration failed")
        self._trial=s;return 0

    def commit_state(self):
        self._committed=self._trial.clone();return 0

    def revert_to_last_commit(self):
        self._trial=self._committed.clone();return 0

    def revert_to_start(self):
        p=self.parameters;ec=p.first_buckling_stress/p.elastic_modulus
        c=_Curve("initial",p,0,(ec,p.yield_strain),ec,p.first_buckling_stress)
        self._committed=_State(0.,0.,p.elastic_modulus,"elastic",c)
        self._trial=self._committed.clone();return 0

    def get_copy(self):
        out=type(self)(self.parameters)
        out._committed=self._committed.clone();out._trial=self._trial.clone();return out

    def get_strain(self):return self._trial.strain
    def get_stress(self):return self._trial.stress
    def get_tangent(self):return self._trial.tangent
    def get_initial_tangent(self):return self.parameters.elastic_modulus

    def get_state(self):
        s=self._trial
        return dict(strain=s.strain,stress=s.stress,tangent=s.tangent,stage=s.stage,
                    plastic_max=s.plastic_max,buckling_count=len(s.buckled_curves),
                    external_work_density=s.work_density,events=deepcopy(s.events))
