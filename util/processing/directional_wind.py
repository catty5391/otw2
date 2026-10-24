"""Shared, SI-unit wind load contracts. Angles are degrees, +X towards +Y.

Loads are global six-DOF reference vectors, not meteorological from-directions.
This module does not choose aerodynamic coefficients or alter mass/gravity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Mapping


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


@dataclass(frozen=True)
class AppliedDirectionalWind:
    time_series_tag: int
    pattern_tag: int
    applied_loads: dict


def apply_nodal_wind_loads(loads, tag_manager, ops_module=None, *, time_series_type="Linear",
                           path_values=None, dt=None, start_time=None, hold_last=False):
    """One factor drives both horizontal components; optional scalar Path history.

    Path inputs are *dimensionless* multipliers of already dimensional loads.
    Use separate patterns for spatially different processes, not independent
    X/Y processes for the same fixed wind direction. Never freezes gravity.
    """
    if ops_module is None:
        import openseespy.opensees as ops_module
    loads = validate_nodal_loads(loads)
    if time_series_type not in {"Linear", "Constant", "Path"}:
        raise ValueError("supported time series: Linear, Constant, Path")
    current_time = float(ops_module.getTime())
    if time_series_type == "Linear" and abs(current_time) > 1e-12:
        raise ValueError("Linear loading requires domain time=0; freeze/reset gravity explicitly first")
    if time_series_type == "Path":
        if dt is None or not math.isfinite(float(dt)) or float(dt) <= 0:
            raise ValueError("positive finite Path dt required")
        values = tuple(map(float, path_values)) if path_values is not None else ()
        if len(values) < 2 or not all(math.isfinite(x) for x in values):
            raise ValueError("Path requires at least two finite multipliers")
        start = current_time if start_time is None else float(start_time)
        if not math.isfinite(start):
            raise ValueError("finite start_time required")
    elif path_values is not None or dt is not None or start_time is not None or hold_last:
        raise ValueError("Path parameters only apply to Path")
    present = set(ops_module.getNodeTags())
    for tag in loads:
        if tag not in present or len(ops_module.nodeDisp(tag)) != 6:
            raise ValueError(f"node {tag} missing or not six-DOF")
    ts = tag_manager.get_next_tag(namespace="timeSeries")
    pat = tag_manager.get_next_tag(namespace="pattern")
    made_ts = made_pat = False
    try:
        if time_series_type == "Path":
            options = ("-useLast",) if hold_last else ()
            ops_module.timeSeries("Path", ts, "-dt", float(dt), "-startTime", start, "-values", *values, *options)
        else:
            ops_module.timeSeries(time_series_type, ts)
        made_ts = True
        ops_module.pattern("Plain", pat, ts)
        made_pat = True
        for tag, vector in sorted(loads.items()):
            ops_module.load(tag, *vector)
    except Exception:
        if made_pat:
            ops_module.remove("loadPattern", pat)
        if made_ts:
            ops_module.remove("timeSeries", ts)
        raise
    return AppliedDirectionalWind(ts, pat, loads)
