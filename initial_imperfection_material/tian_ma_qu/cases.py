"""Traceable literature parameters; missing values are explicit assumptions."""
from dataclasses import asdict, dataclass
from math import pi

from .material import TMQParameters

PAPER_DOI = "https://doi.org/10.1016/j.jobe.2021.103798"
BLACK_REPORT = "https://nehrpsearch.nist.gov/static/files/NSF/PB81154312.pdf"
ASSUMPTIONS = {
    "elastic_modulus": "206 GPa: illustrative input, NOT measured E for this specimen",
    "rho": "0.01: assumed tensile hardening ratio; not found in accessible table",
    "gamma": "0.5: assumed compression-branch transition fraction",
    "zeta": "0.1: assumed tensile pinching transition fraction",
    "protocol": "New displacement-controlled demonstration, NOT digitized test history",
    "nominal_geometry": "Nominal standard-pipe OD/t; not measured specimen dimensions",
    "validation": "No experimental error statistic: no digitized experimental data",
}


@dataclass(frozen=True)
class MemberCase:
    key: str
    label: str
    length: float
    outside_diameter: float
    thickness: float
    end_condition: str
    parameters: TMQParameters

    @property
    def area(self):
        return pi * self.thickness * (self.outside_diameter - self.thickness)

    def to_dict(self):
        return {**asdict(self), "area_m2": self.area, "sources": [PAPER_DOI, BLACK_REPORT],
                "assumptions": dict(ASSUMPTIONS)}


def literature_cases():
    # Table 2 prints two identically named P102 rows. Keep BOTH, unambiguously.
    # P102/P89 are nominal pipe names, NOT OD = 102/89 mm (Black 1980 Table 1).
    rows = (
        ("p102_row_a", "P102 x 6.02 / PP / table row A", 3.07, .1143, .00602, "PP", 327.28e6,
         (.506, .020, .797, 1.449, .474, 1.549, .544, .020, .0044)),
        ("p102_row_b", "P102 x 6.02 / PP / table row B", 3.07, .1143, .00602, "PP", 327.28e6,
         (.418, .015, .699, 1.342, .493, 1.342, .444, .014, .0041)),
        ("p89_pf", "P89 x 5.74 / PF", 3.89, .1016, .00574, "PF", 319.01e6,
         (.804, .025, .694, 1.298, .551, 1.196, .488, .027, .0090)),
    )
    cases = []
    for key, label, length, diameter, thickness, ends, fy, values in rows:
        coefficients = dict(zip(("alpha", "beta", "phi", "tau", "mu", "nu", "eta", "theta", "kappa"), values))
        params = TMQParameters(elastic_modulus=206e9, yield_stress=fy, rho=.01,
                               gamma=.5, zeta=.1, **coefficients,
                               provenance="Liu et al. 2022 Tables 1/2; E,rho,gamma,zeta assumed; " + key)
        cases.append(MemberCase(key, label, length, diameter, thickness, ends, params))
    return cases
