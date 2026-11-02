"""Shared, SI-unit wind load contracts. Angles are degrees, +X towards +Y.

Loads are global six-DOF reference vectors, not meteorological from-directions.
This module does not choose aerodynamic coefficients or alter mass/gravity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from .nodal_loads import AppliedNodalLoads, apply_nodal_loads


def wind_unit_vector(angle_deg):
    angle = float(angle_deg)
    if not math.isfinite(angle):
        raise ValueError("wind angle must be finite degrees")
    a = math.radians(angle % 360)
    return tuple(0.0 if abs(x) < 1e-14 else x for x in (math.cos(a), math.sin(a), 0.0))


def coordinates(record):
    values = tuple(float(record[k]) for k in "xyz") if isinstance(record, Mapping) else tuple(map(float, record))
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError("three finite node coordinates required")
    return values


def validate_nodal_loads(loads):
    result = {}
    for key, vector in loads.items():
        tag = int(key)
        if tag != key or isinstance(key, bool) or tag <= 0:
            raise ValueError("positive integer node tags required")
        v = tuple(map(float, vector))
        if len(v) != 6 or not all(math.isfinite(x) for x in v):
            raise ValueError(f"node {tag}: six finite global loads required")
        result[tag] = v
    if not result:
        raise ValueError("nonempty nodal loads required")
    return result


def nodal_resultant(nodes, loads, origin=(0, 0, 0)):
    origin = coordinates(origin)
    force, moment = [0.] * 3, [0.] * 3
    for tag, v in validate_nodal_loads(loads).items():
        r = tuple(x-o for x, o in zip(coordinates(nodes[tag]), origin))
        cross = (r[1]*v[2]-r[2]*v[1], r[2]*v[0]-r[0]*v[2], r[0]*v[1]-r[1]*v[0])
        for i in range(3):
            force[i] += v[i]
            moment[i] += cross[i] + v[i+3]
    return {"force_N": force, "moment_Nm": moment, "origin_m": list(origin)}


def merge_nodal_loads(*mappings):
    result = {}
    for loads in mappings:
        if not loads:
            continue
        for tag, vector in validate_nodal_loads(loads).items():
            old = result.get(tag, (0.,)*6)
            result[tag] = tuple(a+b for a, b in zip(old, vector))
    return result


# Backwards-compatible name; existing callers keep their tag/load attributes.
AppliedDirectionalWind = AppliedNodalLoads


def apply_nodal_wind_loads(loads, tag_manager, ops_module=None, *, time_series_type="Linear",
                           path_values=None, dt=None, start_time=None, hold_last=False,
                           times=None):
    """One factor drives both horizontal components; optional scalar Path history.

    Path inputs are *dimensionless* multipliers of already dimensional loads.
    Use separate patterns for spatially different processes, not independent
    X/Y processes for the same fixed wind direction. Never freezes gravity.

    This compatibility wrapper retains six-DOF validation and the historical
    permission for nonzero first Path values. New wind/rain code should use
    apply_nodal_loads or apply_nodal_load_history from nodal_loads directly.
    """
    return apply_nodal_loads(validate_nodal_loads(loads),tag_manager,ops_module,
        name="wind",time_series_type=time_series_type,path_values=path_values,dt=dt,
        times=times,start_time=start_time,hold_last=hold_last,allow_nonzero_initial=True)
