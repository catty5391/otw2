"""Conjugate external work for every explicitly identified loaded DOF.

The signed trapezoidal sum is path ordered. It is not automatically dissipated
energy, even when measured endpoint forces/displacements happen to close.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping
from typing import Any


def conjugate_external_work(
    records: Iterable[Mapping[str, Any]],
    *,
    all_applied_dofs_included: bool = False,
    constraint_work_included: bool = False,
    endpoint_absolute_tolerance: float = 1e-10,
    endpoint_relative_tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Integrate sum(F_i du_i), including moments/rotations when supplied.

    Every record contains ``displacements`` and ``external_forces`` mappings
    with the same constant DOF keys. Give gravity loads too; a moving support's
    work-conjugate constraint force is a separate channel if applicable. This
    function cannot discover an omitted load. ``all_applied_dofs_included`` is
    the caller's explicit ledger completeness declaration, not a test result.
    """
    points = tuple(records)
    if len(points) < 2:
        raise ValueError("external work requires at least two committed states")
    for value in (endpoint_absolute_tolerance, endpoint_relative_tolerance):
        if not math.isfinite(value) or value < 0:
            raise ValueError("endpoint tolerances must be finite and nonnegative")
    channels = set(points[0]["displacements"])
    if not channels:
        raise ValueError("no conjugate DOF channels supplied")
    clean: list[tuple[dict[Hashable, float], dict[Hashable, float]]] = []
    for index, point in enumerate(points):
        if (point.get("accepted", True) is not True or point.get("committed", True) is not True or
                point.get("state", "committed") != "committed"):
            raise ValueError(f"state {index} is not an accepted committed state")
        displacements, forces = point["displacements"], point["external_forces"]
        if set(displacements) != channels or set(forces) != channels:
            raise ValueError("every state must contain the same complete force/displacement channels")
        u = {key: float(displacements[key]) for key in channels}
        f = {key: float(forces[key]) for key in channels}
        if not all(math.isfinite(value) for value in (*u.values(), *f.values())):
            raise ValueError("nonfinite work-conjugate data")
        clean.append((u, f))
    by_dof = {key: math.fsum((f0[key] + f1[key]) * .5 * (u1[key] - u0[key])
                             for (u0, f0), (u1, f1) in zip(clean, clean[1:]))
              for key in channels}
    closed = all(math.isclose(clean[0][column][key], clean[-1][column][key],
                              rel_tol=endpoint_relative_tolerance,
                              abs_tol=endpoint_absolute_tolerance)
                 for key in channels for column in (0, 1))
    return {"schema": "otw2.conjugate_work.v1", "unit": "J", "signed_external_work": math.fsum(by_dof.values()),
            "work_by_dof": [{"dof": str(key), "work": by_dof[key]}
                            for key in sorted(channels, key=str)],
            "endpoint_force_displacement_closed": closed,
            "internal_state_closure_verified": False,
            "interpretation": "signed_external_work_not_automatically_dissipation",
            "all_applied_dofs_included": bool(all_applied_dofs_included),
            "constraint_work_included": bool(constraint_work_included),
            "states": len(clean)}
