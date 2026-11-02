"""SI load contracts for a deliberately limited wind-driven-rain baseline.

Diameter integration uses millimetres: N(D) has units m^-3 mm^-1.
Mass uses metres. N is an airborne concentration, NOT an impact rate.
The rain-rate-closed option rescales the truncated MP distribution explicitly.
Loads use complete capture of incident normal momentum, efficiency=1. No
water film, rebound, rivulet aerodynamics, accreted mass or follower loads.
See results/REPORT.md and the literature investigation for provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

WATER_DENSITY = 1000.0


def positive(value, name, *, zero=False):
    value = float(value)
    if not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def vector3(value, name):
    v = np.asarray(value, dtype=float)
    if v.shape != (3,) or not np.all(np.isfinite(v)):
        raise ValueError(f"{name} must have three finite components")
    return v


def unit_vector(value, name):
    v = vector3(value, name)
    return v / positive(np.linalg.norm(v), name)


def terminal_velocity(diameter_mm):
    """Atlas et al. exponential approximation; disallow tiny-drop misuse.

    This implementation intentionally supports only 0.16--6 mm. This bound
    does not establish applicability to all storms or drop breakup regimes.
    """
    d = np.asarray(diameter_mm, dtype=float)
    if not np.all(np.isfinite(d)) or np.any((d < .16) | (d > 6.)):
        raise ValueError("Atlas diameter must be in [0.16, 6] mm")
    return 9.65 - 10.3 * np.exp(-.6 * d)


@dataclass(frozen=True)
class DropSpectrum:
    diameter_mm: np.ndarray
    bin_width_mm: np.ndarray
    concentration_m3_mm: np.ndarray
    terminal_speed_m_s: np.ndarray
    requested_rain_mm_h: float
    recovered_rain_mm_h: float
    raw_recovered_rain_mm_h: float
    normalization_factor: float
    normalized: bool

    @property
    def mass_kg(self):
        return WATER_DENSITY * np.pi / 6. * (self.diameter_mm * .001) ** 3

    @property
    def number_m3(self):
        return self.concentration_m3_mm * self.bin_width_mm

    @property
    def water_content_kg_m3(self):
        return float(np.dot(self.mass_kg, self.number_m3))


def marshall_palmer(rain_mm_h, *, bins=240, minimum_mm=.2, maximum_mm=5.8,
                    normalize_rain_rate=False):
    rain = positive(rain_mm_h, "rain_mm_h", zero=True)
    if isinstance(bins, bool) or int(bins) != bins or bins < 2:
        raise ValueError("bins must be an integer >= 2")
    if not .16 <= minimum_mm < maximum_mm <= 6.:
        raise ValueError("require 0.16 <= minimum < maximum <= 6 mm")
    edges = np.linspace(minimum_mm, maximum_mm, int(bins) + 1)
    d, dd = (edges[:-1]+edges[1:])/2., np.diff(edges)
    vt = terminal_velocity(d)
    n = 8000. * np.exp(-4.1 * rain**(-.21) * d) if rain else np.zeros_like(d)
    # Volume flux m/s -> mm/h, with integration dD still in mm.
    volume = np.pi/6. * (d*.001)**3
    raw = float(3.6e6 * np.sum(volume * vt * n * dd))
    factor = rain/raw if normalize_rain_rate and rain else 1.
    n = n*factor
    recovered = float(3.6e6*np.sum(volume*vt*n*dd))
    return DropSpectrum(d, dd, n, vt, rain, recovered, raw, factor, bool(normalize_rain_rate))


def drop_velocity(spectrum, wind_vector_m_s, *, horizontal_ratio=1.):
    """Prescribed constant gamma, not the calibrated Tian et al. trajectory law."""
    wind = vector3(wind_vector_m_s, "wind_vector_m_s")
    if abs(wind[2]) > 1e-12:
        raise ValueError("baseline supports horizontal wind only")
    ratio = positive(horizontal_ratio, "horizontal_ratio", zero=True)
    v = np.tile(ratio*wind, (len(spectrum.diameter_mm), 1))
    v[:, 2] = -spectrum.terminal_speed_m_s
    return v


def plane_normal_pressure(spectrum, velocities, normal):
    """Two-sided normal capture, Pa vector, no tangential momentum transfer.

    For a vertical plate normal to flow, p = sum(m N dD v_x |v_x|).
    Impact arrival frequency is N dD |v_n|; impulse is m v_n.
    """
    n = unit_vector(normal, "normal")
    v = np.asarray(velocities, dtype=float)
    if v.shape != (len(spectrum.diameter_mm),3) or not np.all(np.isfinite(v)):
        raise ValueError("one finite velocity per diameter bin required")
    vn = v@n
    return float(np.sum(spectrum.mass_kg*spectrum.number_m3*np.abs(vn)*vn))*n


def cylinder_line_load(spectrum, velocities, axis, diameter_m, *, bundle_count=1):
    """N/m of actual cylinder length; projected collector, no end caps.

    q = b integral m N |v_perp| v_perp dD. Tangential velocity is removed
    both from the arrival flux and the transferred momentum. This is complete
    capture of transverse momentum over projected width, not integration of
    frictionless local surface-normal impacts on a curved cylinder (which
    would give 2/3 of this result). No air Cd in
    this formula, and no pi/2 empirical impact multiplier is hidden here.
    """
    axis = unit_vector(axis, "axis")
    b = positive(diameter_m, "diameter_m")
    if b > 1: raise ValueError("diameter must be metres, at most 1 m")
    if isinstance(bundle_count,bool) or int(bundle_count)!=bundle_count or bundle_count<1:
        raise ValueError("bundle_count must be a positive integer")
    v = np.asarray(velocities,dtype=float)
    if v.shape != (len(spectrum.diameter_mm),3) or not np.all(np.isfinite(v)):
        raise ValueError("one finite velocity per diameter bin required")
    vp = v-np.outer(v@axis,axis)
    mass_density = spectrum.mass_kg*spectrum.number_m3
    return b*bundle_count*np.sum((mass_density*np.linalg.norm(vp,axis=1))[:,None]*vp,axis=0)


def dry_cylinder_line_load(wind_vector_m_s, axis, diameter_m, *, drag_coefficient=1., air_density=1.225):
    v = vector3(wind_vector_m_s,"wind")
    axis = unit_vector(axis,"axis")
    vp = v-np.dot(v,axis)*axis
    factor = .5*positive(air_density,"air_density")*positive(drag_coefficient,"Cd")*positive(diameter_m,"diameter_m")
    return factor*np.linalg.norm(vp)*vp


def distribute_members(nodes, members, line_load):
    """Uniform load along straight pieces, half to each end.

    Exactly preserves global force and moment of this uniform piece load.
    This is a lumped nodal load, not a consistent beam load vector.
    members = iterable of {tag,node_i,node_j,breadth_m}.
    """
    loads, rows = {}, []
    force, moment = np.zeros(3),np.zeros(3)
    for m in members:
        ni,nj = int(m['node_i']),int(m['node_j'])
        a,b = vector3(nodes[ni],"node"),vector3(nodes[nj],"node")
        chord=b-a;length=positive(np.linalg.norm(chord),"member length")
        q=vector3(line_load(chord/length,m['breadth_m']),"line load")
        f=q*length;mid=(a+b)/2.
        force+=f;moment+=np.cross(mid,f)
        for n in (ni,nj):
            loads.setdefault(n,np.zeros(6))[:3]+=f/2.
        rows.append(dict(member_tag=int(m['tag']),node_i=ni,node_j=nj,length_m=float(length),
                         midpoint_z_m=float(mid[2]),Fx_N=float(f[0]),Fy_N=float(f[1]),Fz_N=float(f[2])))
    nf=sum((v[:3] for v in loads.values()),np.zeros(3))
    nm=sum((np.cross(nodes[n],v[:3])+v[3:] for n,v in loads.items()),np.zeros(3))
    audit=dict(force_N=force.tolist(),moment_Nm=moment.tolist(),
               force_mapping_error_N=float(np.max(np.abs(nf-force))),
               moment_mapping_error_Nm=float(np.max(np.abs(nm-moment))))
    return {n:tuple(v) for n,v in loads.items()},rows,audit


def kaimal_history(*, duration_s=600.,dt_s=.1,mean_m_s=30.,sigma_m_s=3.,length_scale_m=120.,seed=30103):
    """Single point, one-sided Kaimal spectrum, finite band random phases.

    S=4 sigma^2 L/U / (1+6 f L/U)^(5/3). Finite-duration truncation is
    reported rather than corrected by an undocumented variance rescaling.
    This is a synthetic wind input, not a measured rain-intensity spectrum.
    """
    duration_s=positive(duration_s,"duration");dt_s=positive(dt_s,"dt")
    mean_m_s=positive(mean_m_s,"mean");sigma_m_s=positive(sigma_m_s,"sigma",zero=True)
    length_scale_m=positive(length_scale_m,"length scale")
    n=int(round(duration_s/dt_s))
    if n<8 or n%2 or abs(n*dt_s-duration_s)>1e-9:
        raise ValueError("duration/dt must be an even integer >= 8")
    f=np.fft.rfftfreq(n,dt_s);df=1./duration_s
    s=4*sigma_m_s**2*length_scale_m/mean_m_s/(1+6*f*length_scale_m/mean_m_s)**(5/3)
    s[[0,-1]]=0.
    rng=np.random.default_rng(seed)
    coeff=n*np.sqrt(s*df/2)*np.exp(1j*rng.uniform(0,2*np.pi,len(f)))
    u=mean_m_s+np.fft.irfft(coeff,n)
    return np.arange(n)*dt_s,u,f,s,dict(target_infinite_band_variance=sigma_m_s**2,
        discrete_band_variance=float(np.sum(s)*df),realized_variance=float(np.var(u)),
        seed=seed,spatial_coherence='single point only; no spatial rain coherence model')


def poisson_plate_history(spectrum, speed_m_s, *, area_m2=.01,duration_s=600.,dt_s=.02,seed=772):
    """Independent Poisson drop arrivals, bin-averaged force, not impact peak.

    This is a deliberately idealized stochastic check of the flux formula.
    Rain clustering and sub-millisecond impact pulse shape are unmodelled.
    """
    speed=positive(speed_m_s,"speed",zero=True);area=positive(area_m2,"area")
    duration=positive(duration_s,"duration");dt=positive(dt_s,"dt")
    n=int(round(duration/dt))
    if n<2 or abs(n*dt-duration)>1e-9:raise ValueError("integer duration/dt >= 2 required")
    rate=spectrum.number_m3*speed*area
    impulse=spectrum.mass_kg*speed
    rng=np.random.default_rng(seed)
    # Keep working memory small for longer validation histories.
    force=np.empty(n)
    for i in range(0,n,1000):
        count=rng.poisson(rate*dt,size=(min(1000,n-i),len(rate)))
        force[i:i+len(count)]=count@impulse/dt
    mean=float(rate@impulse);var=float(rate@(impulse**2)/dt)
    return np.arange(n)*dt,force,dict(expected_mean_N=mean,observed_mean_N=float(np.mean(force)),
        expected_variance_N2=var,observed_variance_N2=float(np.var(force,ddof=1)),
        standard_error_mean_N=float(np.sqrt(var/n)),area_m2=area,dt_s=dt,duration_s=duration,seed=seed)
