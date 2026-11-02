"""Independent units/moments audit; no structural or site-calibrated predictions.

Run from repository root with .venv/bin/python <this file>.
Uses a truncated Marshall-Palmer number spectrum and Atlas terminal velocity.
All D integration coordinates are millimetres; drop mass uses metres.
"""
from pathlib import Path
import json
import math
import numpy as np
from scipy.integrate import quad
from scipy.special import gammainc, gamma

OUT = Path(__file__).resolve().parent
RHO_W = 1000.0
RHO_A = 1.225
D_LO, D_HI = 0.2, 5.8


def terminal(D_mm):
    return 9.65 - 10.3 * np.exp(-0.6 * np.asarray(D_mm))


def spectrum(D_mm, rain_rate_mm_h):
    if rain_rate_mm_h == 0:
        return np.zeros_like(np.asarray(D_mm), dtype=float)
    return 8000.0 * np.exp(-4.1 * rain_rate_mm_h**-0.21 * np.asarray(D_mm))


def mass(D_mm):
    return RHO_W * np.pi / 6 * (np.asarray(D_mm) * 1e-3)**3


def audit():
    rows = []
    for rain_rate in (10.0, 50.0, 100.0, 200.0):
        slope = 4.1 * rain_rate**-0.21
        concentration = quad(lambda d: float(mass(d) * spectrum(d, rain_rate)), D_LO, D_HI,
                             epsabs=1e-13, epsrel=1e-12)[0]
        analytic = (RHO_W * math.pi / 6 * 1e-9 * 8000 * gamma(4) / slope**4
                    * (gammainc(4, slope*D_HI)-gammainc(4, slope*D_LO)))
        implied_rain_rate = 3.6e6 * quad(
            lambda d: float(mass(d) / RHO_W * terminal(d) * spectrum(d, rain_rate)),
            D_LO, D_HI, epsabs=1e-13, epsrel=1e-12)[0]
        p = concentration * 30**2
        rows.append(dict(input_rain_rate_mm_h=rain_rate, raw_implied_rain_rate_mm_h=implied_rain_rate,
                         concentration_kg_m3=concentration, analytic_concentration_kg_m3=analytic,
                         analytic_relative_error=abs(concentration-analytic)/analytic,
                         mass_flux_rescale_to_input=rain_rate/implied_rain_rate,
                         raw_normal_collector_pressure_pa_at_U30=p,
                         wind_reference_pa_at_U30_CD1=0.5*RHO_A*30**2,
                         pressure_ratio_percent_CD1=100*p/(0.5*RHO_A*30**2)))
    smooth_cylinder_factor = 0.5 * quad(lambda theta: math.cos(theta)**3,
                                      -math.pi/2, math.pi/2)[0]
    result = dict(scope='independent_formula_and_units_audit_not_site_or_structural_validation',
                  diameter_range_mm=[D_LO, D_HI], rain_spectrum='original_unscaled_Marshall_Palmer',
                  terminal_velocity='Atlas_9.65_minus_10.3_exp_minus_0.6_Dmm',
                  terminal_at_D01_m_s=float(terminal(0.1)),
                  positive_terminal_diameter_threshold_mm=math.log(10.3/9.65)/0.6,
                  rows=rows,
                  cylinder_smooth_frictionless_normal_only_factor=smooth_cylinder_factor,
                  cylinder_projected_transverse_capture_factor=1.0,
                  pi_squared_over_12_to_pi_over_6_ratio=math.pi/2,
                  interpretation='Pressure is for U_r=30m/s normal to a unit collector; no shielding, wet Cd or velocity amplification.')
    assert max(x['analytic_relative_error'] for x in rows) < 1e-10
    assert abs(smooth_cylinder_factor-2/3) < 1e-12
    assert float(terminal(0.1)) < 0
    assert np.all(spectrum(np.array([0.2,1,5.8]),0)==0)
    assert all(x['raw_normal_collector_pressure_pa_at_U30']>0 for x in rows)
    (OUT/'formula_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    audit()
