"""Single-tower directional load integration; no neighbouring tower is built.

The bundled configuration is a deliberately uncalibrated verification example,
not a code-compliant wind-speed/capacity assessment. Existing result files and
legacy +Y load semantics are untouched.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from util.processing.directional_wind import coordinates, merge_nodal_loads, nodal_resultant
from util.processing.tower_directional_wind import (
    PROXY_AREA_BASIS, TowerWindCoefficients, geometry_from_model, build_tower_wind_load)
from util.processing.conductor_directional_wind import conductor_loads_from_model, combine_conductor_loads

HEIGHT_EDGES = (0., 3.2, 6.8, 9., 13.2, 17.4, 21.6, 24., 27., 30., 33., 36.4, 39.6)


def verification_config(angle_deg, *, mode="single_tower", wind_speed_m_s=20., line_segments=20):
    """Explicit assumptions for a reproducible smoke experiment, NOT calibration."""
    return {"schema_version": 1, "mode": mode, "wind_angle_deg": float(angle_deg),
            "angle_convention": "degrees; +X transverse=0; +Y longitudinal=90; flow TOWARDS",
            "wind_speed_m_s": float(wind_speed_m_s), "air_density": 1.225,
            "tower_coefficient_x": 1., "tower_coefficient_y": 1., "yaw_gain": .2,
            "coefficient_provenance": "EXPLICIT UNCALIBRATED verification choices: Cx=Cy=1; yaw_gain=0.2 from Cai2021 angular functional form only; NOT a panel-code calibration",
            "area_basis": PROXY_AREA_BASIS,
            "area_provenance": "All original physical rods: equal-angle leg-width proxy, no shielding or confirmed section orientation; not one-face IEC area",
            "height_edges_m": list(HEIGHT_EDGES), "height_factors": [1.] * (len(HEIGHT_EDGES)-1),
            "height_factor_provenance": "Uniform-flow verification field, all factors 1; NOT a terrain wind profile or gust factor",
            "conductor_drag_coefficient": 1., "line_segments": line_segments,
            "conductor_coefficient_provenance": "Cd=1 explicit verification assumption; bundle shielding/lift/relative-velocity damping omitted",
            "validated_for_design": False}


def validate_config(config):
    c = deepcopy(config)
    if c.get("schema_version") != 1 or c.get("mode") not in {"single_tower", "tower_line_explicit"}:
        raise ValueError("directional config: schema 1, single_tower or tower_line_explicit required")
    for key in ("wind_angle_deg", "wind_speed_m_s", "air_density", "tower_coefficient_x",
                "tower_coefficient_y", "yaw_gain", "conductor_drag_coefficient"):
        c[key] = float(c[key])
        if not math.isfinite(c[key]):
            raise ValueError(f"finite {key} required")
    if c["wind_speed_m_s"] <= 0 or c["air_density"] <= 0 or c["conductor_drag_coefficient"] <= 0:
        raise ValueError("positive reference wind speed, density and conductor Cd required")
    TowerWindCoefficients(c["tower_coefficient_x"],c["tower_coefficient_y"],c["yaw_gain"],c["coefficient_provenance"])
    edges=tuple(map(float,c["height_edges_m"]))
    factors=tuple(map(float,c["height_factors"]))
    if (len(edges)<2 or len(factors)!=len(edges)-1 or not all(math.isfinite(v) for v in edges+factors)
            or any(b<=a for a,b in zip(edges,edges[1:])) or any(v<0 for v in factors)):
        raise ValueError("finite increasing height edges and nonnegative band factors required")
    n = c["line_segments"]
    if isinstance(n,bool) or int(n) != n or not 2 <= n <= 1000:
        raise ValueError("line_segments must be an integer in [2,1000]")
    c["line_segments"] = int(n)
    for key in ("coefficient_provenance", "area_provenance", "height_factor_provenance",
                "conductor_coefficient_provenance"):
        if not isinstance(c.get(key),str) or not c[key].strip():
            raise ValueError(f"nonempty {key} required")
    return c


def attach_explicit_lines(tower, output, config):
    """Reuse existing V strings/cable properties, with one tower and fixed ends.

    Two existing V strings each support a conductor with a 300 m span to each
    side (four spans total). Far-end positions are held fixed, not other towers.
    Existing cable gravity patterns are removed before the caller applies ONE
    global mass-derived gravity pattern. Mass and initial force remain intact.
    """
    import numpy as np
    from model.tower_line_system_model import TowerLineSystemModel
    system = TowerLineSystemModel(output_dir=output, wipe=False)
    source = deepcopy(system.config)
    system.tag_manager = tower.tag_manager
    system.towers = {"tower_1": tower}
    system._merge_tower_maps(tower)
    insulators = {k:v for k,v in source["insulators"].items() if v["tower_id"] == "tower_1"}
    system.config = {"towers": {}, "insulators": insulators, "transmission_lines": {}}
    system.build_insulators()
    template = deepcopy(next(iter(source["transmission_lines"].values())))
    template.pop("formfinding", None)
    template["n_seg"] = config["line_segments"]
    anchors = []
    for name, insulator in system.insulator_map.items():
        for side in (-1, 1):
            coord = np.array(insulator["lower_coord"], dtype=float)
            coord[1] += side*300.
            anchor = system._create_node(coord, {"component": "fixed_remote_anchor"}, fix_rotations=False)
            system.ops.fix(anchor, 1, 1, 1, 1, 1, 1)
            system.fix_map[anchor] = {"node_tag": anchor, **{k:1 for k in ("ux","uy","uz","rx","ry","rz")}}
            anchors.append(anchor)
            line = deepcopy(template)
            line["node_to_hang"] = [int(insulator["lower_node_tag"]), anchor]
            system.config["transmission_lines"][f"{name}_{'negative_y' if side < 0 else 'positive_y'}"] = line
    system.build_transmission_lines()
    for filename,data in (("source_configuration.json",source),("effective_configuration.json",system.config)):
        (Path(output)/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    removed = []
    for record in system.transmission_line_map.values():
        if record["pattern_tag"] is not None:
            system.ops.remove("loadPattern", record["pattern_tag"])
            system.ops.remove("timeSeries", record["time_series_tag"])
            removed.append(record["pattern_tag"])
        record["gravity_applied_by"] = "single_global_mass_derived_pattern"
    # Tower element_map stays tower-only for the 12-component force recorder.
    tower.node_map = system.node_map
    tower.fix_map = system.fix_map
    tower.mass_map = system.mass_map
    system._write_outputs()
    metadata = {"towers": 1, "spans": len(system.transmission_line_map), "fixed_anchor_nodes": anchors,
                "span_m": 300., "initial_sag_m": template["initial_sag"],
                "initial_force_N": template["material"]["initial_force"], "segments_per_span": template["n_seg"],
                "conductor_model": template["conductor"], "source_configuration": str(system.config_path),
                "source_configuration_sha256": hashlib.sha256(system.config_path.read_bytes()).hexdigest(),
                "removed_duplicate_gravity_patterns": removed,
                "limitations": ["Remote supports fixed; not a multiple-tower system",
                    "Two conductors only, one subconductor each; no ground wires/complete phase bundle",
                    "Initial parabolic sag and prestress inherited from existing example; gravity is equilibrated, target sag is NOT fitted",
                    "Insulator drag omitted; elastic V strings inherited, not tension-only",
                    "Static geometry-frozen drag, no cable motion-dependent aerodynamic damping"]}
    return system, metadata


def build_load_plan(model, config, system=None):
    c = validate_config(config)
    if (c["mode"] == "tower_line_explicit") != (system is not None):
        raise ValueError("explicit tower-line mode must have exactly one explicit cable system")
    geometry = geometry_from_model(model, area_basis=c["area_basis"], area_provenance=c["area_provenance"])
    tower_load = build_tower_wind_load(geometry, wind_angle_deg=c["wind_angle_deg"],
        reference_pressure_pa=.5*c["air_density"]*c["wind_speed_m_s"]**2,
        height_edges_m=c["height_edges_m"], height_factors=c["height_factors"],
        height_factor_provenance=c["height_factor_provenance"],
        coefficients=TowerWindCoefficients(c["tower_coefficient_x"],c["tower_coefficient_y"],
                                         c["yaw_gain"],c["coefficient_provenance"]))
    lines = []
    if system is not None:
        # Freeze cable orientation at the gravity-equilibrated shape, without
        # changing the FE geometry, mass, stiffness, initial force or constraints.
        from types import SimpleNamespace
        nodes = {tag: {**record, **dict(zip("xyz", (x+d for x,d in zip(coordinates(record),model.ops.nodeDisp(tag)[:3]))))}
                 for tag,record in system.node_map.items()}
        view = SimpleNamespace(node_map=nodes, transmission_line_map=system.transmission_line_map)
        for line_id in system.transmission_line_map:
            lines.append(conductor_loads_from_model(view,line_id,wind_speed_m_s=c["wind_speed_m_s"],
                wind_angle_deg=c["wind_angle_deg"], drag_coefficient=c["conductor_drag_coefficient"],air_density=c["air_density"]))
        combined = combine_conductor_loads(*lines)
        line_forces = combined.nodal_forces
    else:
        line_forces = {}
    loads = merge_nodal_loads(tower_load.applied_loads, line_forces)
    gravity_coordinates={tag:tuple(x+d for x,d in zip(coordinates(record),model.ops.nodeDisp(tag)[:3]))
                         for tag,record in model.node_map.items()}
    return loads, {"configuration": c, "tower": asdict(tower_load),
                   "conductors": [line.to_dict() for line in lines],
                   "combined_initial_coordinate_resultant": nodal_resultant(model.node_map,loads,origin=model.origin),
                   "gravity_coordinate_resultants": {
                       "tower":nodal_resultant(gravity_coordinates,tower_load.applied_loads,origin=model.origin),
                       "conductors":nodal_resultant(gravity_coordinates,line_forces,origin=model.origin) if line_forces else None,
                       "combined":nodal_resultant(gravity_coordinates,loads,origin=model.origin)},
                   "normalization": "none; dimensional reference forces in N; multiplier=1 is the configured verification field",
                   "geometry_note": "Tower loads reference initial geometry; cable drag frozen after gravity; solver loads are non-follower nodal loads",
                   "validated_for_design": False}
