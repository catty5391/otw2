"""Read-only static equilibrium from global element resisting forces.

``nodeUnbalance`` is deliberately not used: in OpenSees it is not a general
assembled residual. The caller owns a complete applied *nodal* force ledger and
the set of independent SP constrained DOFs. For element loads, use their element resisting
force convention consistently; do not add equivalent nodal loads a second time.
Dynamic checks require explicit, complete inertia and damping force ledgers;
general MP constraint transformations are not implemented here. This check never
rolls back an already committed analysis.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Iterable
from typing import Any

Dof = tuple[int, int]  # (node tag, 1-based global DOF)


class CommittedStateRejected(RuntimeError):
    """A committed state failed a post-check; stop or rebuild/replay explicitly."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("Committed state failed equilibrium; automatic retry/rollback is forbidden")


def static_equilibrium(
    ops: Any,
    applied_nodal_loads: Mapping[Dof, float],
    *,
    constrained_dofs: Iterable[Dof],
    rotational_dofs: Iterable[Dof] = (),
    force_scale: float = 1.0,
    moment_scale: float = 1.0,
    force_absolute_tolerance: float = 1e-6,
    moment_absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Assemble ``P - sum(element global resisting force)`` on free DOFs.

    Translation and rotation residuals have separate units/scales (N and N m).
    DOFs are never inferred from equation IDs: eliminated SP DOFs must be
    explicitly supplied by the builder. General MP constraints require a force
    transformation adapter and are rejected when the engine exposes them.
    The force ledger must include
    every applied nodal load pattern at its current factor. Omitted DOFs mean
    exactly zero applied load, not an unknown value.
    """
    scales = (force_scale, moment_scale)
    tolerances = (force_absolute_tolerance, moment_absolute_tolerance, relative_tolerance)
    if any(not math.isfinite(v) or v <= 0 for v in scales):
        raise ValueError("force_scale and moment_scale must be finite and positive")
    if any(not math.isfinite(v) or v < 0 for v in tolerances):
        raise ValueError("equilibrium tolerances must be finite and nonnegative")
    if hasattr(ops, "getRetainedNodes") and ops.getRetainedNodes():
        raise NotImplementedError("MP constraints require a retained/slave force transformation adapter")
    nodes = tuple(int(node) for node in ops.getNodeTags())
    ndofs = {node: len(ops.nodeDisp(node)) for node in nodes}
    dofs = {(node, dof) for node in nodes for dof in range(1, ndofs[node] + 1)}
    constrained, rotations = set(constrained_dofs), set(rotational_dofs)
    if not constrained <= dofs or not rotations <= dofs or not set(applied_nodal_loads) <= dofs:
        raise ValueError("force/constraint/rotation ledger references an unknown node DOF")
    applied = {dof: float(applied_nodal_loads.get(dof, 0.0)) for dof in dofs}
    if not all(math.isfinite(value) for value in applied.values()):
        raise ValueError("applied load ledger contains nonfinite forces")
    contributions: dict[Dof, list[float]] = {dof: [] for dof in dofs}
    for element in ops.getEleTags():
        element_nodes = tuple(int(node) for node in ops.eleNodes(element))
        forces = tuple(float(value) for value in ops.eleForce(element))
        expected = sum(ndofs[node] for node in element_nodes)
        if len(forces) != expected:
            raise ValueError(f"element {element}: force layout {len(forces)} != {expected}; adapter required")
        if not all(math.isfinite(value) for value in forces):
            raise ValueError(f"element {element}: nonfinite resisting force")
        offset = 0
        for node in element_nodes:
            for dof in range(1, ndofs[node] + 1):
                contributions[node, dof].append(forces[offset])
                offset += 1
    residual = {dof: applied[dof] - math.fsum(contributions[dof]) for dof in dofs - constrained}

    def group(keys: set[Dof], scale: float, atol: float, unit: str) -> dict[str, Any]:
        values = [residual[key] for key in sorted(keys)]
        maximum = max((abs(value) for value in values), default=0.0)
        return {"unit": unit, "count": len(keys), "maximum_absolute": maximum,
                "l2": math.sqrt(math.fsum(value * value for value in values)),
                "scale": scale, "scaled_maximum": maximum / scale,
                "threshold": atol + relative_tolerance * scale,
                "passed": maximum <= atol + relative_tolerance * scale}

    translation = group(set(residual) - rotations, force_scale, force_absolute_tolerance, "N")
    rotation = group(set(residual) & rotations, moment_scale, moment_absolute_tolerance, "N m")
    return {"schema": "otw2.static_equilibrium.v1", "analysis": "static",
            "passed": translation["passed"] and rotation["passed"],
            "translation": translation, "rotation": rotation,
            "free_dof_residuals": [{"node": node, "dof": dof, "residual": value,
                                     "unit": "N m" if (node, dof) in rotations else "N"}
                                    for (node, dof), value in sorted(residual.items())],
            "excluded_constrained_dofs": len(constrained),
            "source": "explicit_nodal_load_ledger_minus_assembled_eleForce",
            "requires_complete_load_ledger": True,
            "dynamic_terms_included": False}


def require_equilibrium(report: dict[str, Any]) -> None:
    """Reject a committed state without pretending OpenSees can undo commit."""
    if report.get("passed") is not True:
        raise CommittedStateRejected(report)


def dynamic_equilibrium(
    ops: Any,
    applied_nodal_loads: Mapping[Dof, float],
    *,
    inertial_nodal_forces: Mapping[Dof, float] | None = None,
    damping_nodal_forces: Mapping[Dof, float] | None = None,
    mass_model: str | None = None,
    force_provenance: Mapping[str, str] | None = None,
    **static_check_settings: Any,
) -> dict[str, Any]:
    """Check ``P - I - D - R_static`` without guessing dynamic terms.

    Both dynamic ledgers must include every node DOF, including explicit zero
    entries at fixed or massless DOFs. ``nodal_diagonal_only`` means the caller
    has excluded element mass and formed I=m*a at each node DOF. An independently
    assembled known consistent mass/C*v ledger may declare
    ``externally_assembled_nodal_forces``. Unknown element consistent mass,
    unknown damping, and missing provenance fail closed. Rayleigh damping is
    never inferred from an assumed C or from ``nodeUnbalance``.
    """
    if inertial_nodal_forces is None or damping_nodal_forces is None:
        raise ValueError("complete explicit inertia and damping ledgers are required")
    if mass_model not in {"nodal_diagonal_only", "externally_assembled_nodal_forces"}:
        raise ValueError("declare a supported, known mass model; unknown element mass is unsupported")
    if not force_provenance or any(not isinstance(force_provenance.get(key), str) or
                                   not force_provenance[key].strip() for key in ("inertia", "damping")):
        raise ValueError("inertia and damping force provenance are required")
    dofs = {(int(node), dof) for node in ops.getNodeTags()
            for dof in range(1, len(ops.nodeDisp(node)) + 1)}
    if set(inertial_nodal_forces) != dofs or set(damping_nodal_forces) != dofs:
        raise ValueError("dynamic ledgers must explicitly cover every node DOF, including zeros")
    if not set(applied_nodal_loads) <= dofs:
        raise ValueError("applied load ledger references an unknown node DOF")
    inertia = {key: float(inertial_nodal_forces[key]) for key in dofs}
    damping = {key: float(damping_nodal_forces[key]) for key in dofs}
    if not all(math.isfinite(value) for value in (*inertia.values(), *damping.values())):
        raise ValueError("nonfinite dynamic force ledger")
    effective = {key: float(applied_nodal_loads.get(key, 0.)) - inertia[key] - damping[key] for key in dofs}
    report = static_equilibrium(ops, effective, **static_check_settings)
    report.update(schema="otw2.dynamic_equilibrium.v1", analysis="transient",
                  dynamic_terms_included=True, mass_model=mass_model,
                  force_provenance=dict(force_provenance),
                  source="explicit_nodal_P_minus_I_minus_D_minus_assembled_static_eleForce")
    return report
