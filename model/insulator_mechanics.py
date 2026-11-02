"""Explicit axial assumptions for pin-ended V strings; no calibrated failure law.

Elastic(E, eta=0, Eneg) provides a reversible unilateral law when Eneg=0.
A positive small Eneg is a numerical sensitivity case, not compressive capacity.
"""
from __future__ import annotations

import math


BEHAVIORS = ("elastic", "tension_only", "regularized_tension_only")


def axial_contract(material):
    behavior = material.get("axial_behavior", "elastic")
    if behavior not in BEHAVIORS:
        raise ValueError(f"Unknown insulator axial_behavior: {behavior}")
    default = {"elastic": 1., "tension_only": 0.}.get(behavior)
    ratio = material.get("compression_stiffness_ratio", default)
    if isinstance(ratio, bool) or ratio is None:
        raise ValueError("An explicit compression_stiffness_ratio is required for regularization")
    ratio = float(ratio)
    if not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise ValueError("compression_stiffness_ratio must be finite in [0,1]")
    if behavior == "elastic" and ratio != 1 or behavior == "tension_only" and ratio != 0:
        raise ValueError("compression stiffness contradicts axial_behavior")
    if behavior == "regularized_tension_only" and not 0 < ratio < 1:
        raise ValueError("regularized compression stiffness ratio must be in (0,1)")
    return {"axial_behavior": behavior, "compression_stiffness_ratio": ratio,
            "constitutive_law": "N=EA*strain in tension; N=ratio*EA*strain in compression",
            "calibrated_for_actual_insulator": False}


def v_geometry(upper_coordinates, lower_coordinate):
    points = [tuple(map(float, p)) for p in [*upper_coordinates, lower_coordinate]]
    if len(points) != 3 or any(len(p) != 3 or not all(map(math.isfinite, p)) for p in points):
        raise ValueError("Two upper and one lower finite 3D coordinates required")
    a, b, lower = points
    lengths = [math.dist(p, lower) for p in (a, b)]
    if min(lengths) <= 0 or math.dist(a, b) <= 0:
        raise ValueError("Distinct upper nodes and positive leg lengths required")
    cosine = sum((a[i]-lower[i])*(b[i]-lower[i]) for i in range(3)) / math.prod(lengths)
    return {"initial_leg_lengths_m": lengths, "upper_separation_m": math.dist(a, b),
            "drop_from_upper_midpoint_m": (a[2]+b[2])/2-lower[2],
            "included_angle_deg": math.degrees(math.acos(max(-1., min(1., cosine))))}


def register_axial_material(ops, tag, ea, area, material):
    ea, area = float(ea), float(area)
    if not all(map(math.isfinite, (ea, area))) or min(ea, area) <= 0:
        raise ValueError("Insulator EA and area must be positive and finite")
    contract = axial_contract(material)
    if contract["axial_behavior"] == "elastic":
        ops.uniaxialMaterial("Elastic", tag, ea/area)
    else:
        ops.uniaxialMaterial("Elastic", tag, ea/area, 0., ea/area*contract["compression_stiffness_ratio"])
    return contract


def insulator_states(system):
    """Native axial response plus independent current-length reconstruction."""
    rows = []
    for identity, insulator in system.insulator_map.items():
        lower = int(insulator["lower_node_tag"])
        contract = axial_contract(insulator)
        for upper, element in zip(insulator["upper_node_tags"], insulator["element_tags"]):
            p, q = system.ops.nodeCoord(upper), system.ops.nodeCoord(lower)
            du, dl = system.ops.nodeDisp(upper)[:3], system.ops.nodeDisp(lower)[:3]
            length = math.dist(p, q)
            current = math.dist([x+d for x,d in zip(p,du)], [x+d for x,d in zip(q,dl)])
            strain = current/length-1
            ratio = contract["compression_stiffness_ratio"] if strain < 0 else 1.
            force = float(system.ops.eleResponse(element, "axialForce")[0])
            predicted = float(insulator["EA"])*ratio*strain
            state = "tension" if strain > 1e-12 else "zero"
            if strain < -1e-12:
                state = {"elastic": "compression", "tension_only": "slack",
                         "regularized_tension_only": "regularized_compression"}[contract["axial_behavior"]]
            rows.append({"insulator_id": identity, "element_tag": element,
                         "upper_node_tag": upper, "lower_node_tag": lower,
                         "axial_behavior": contract["axial_behavior"], "state": state,
                         "initial_length_m": length, "current_length_m": current,
                         "axial_strain": strain, "axial_force_N": force,
                         "force_reconstruction_residual_N": force-predicted,
                         "lower_ux_m": dl[0], "lower_uy_m": dl[1], "lower_uz_m": dl[2]})
    return rows
