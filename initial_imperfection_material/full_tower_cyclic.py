"""Quasi-static full-tower cyclic validation for equivalent imperfection laws."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import openseespy.opensees as ops

from model import (
    OpenSeesModelWithBuckling,
    OpenSeesModelWithEquivalentImperfection,
)
from util import (
    GravityLoadApplier,
    PushoverWindLoadApplier,
    TowerInternalForceHistory,
    TowerInternalForceRecorder,
)
from util.analysis import AdaptiveStepper, Algorithm, RunManifest, cyclic_targets
from util.postprocess.response_metrics import path_work
from util.processing.member_state_recorder import MemberStateRecorder
from util.analysis.result_quality import ResultQuality, MemberDomainRange


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "Source" / "Z30103A6.s2k"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results" / "full_tower_cyclic"
BASE_NODE_TAGS = (2510, 2511, 2512, 2513)


@dataclass(frozen=True)
class TowerCyclicPoint:
    step: int
    stage: str
    target_displacement: float
    control_displacement: float
    relative_displacement: float
    drift_ratio: float
    base_shear: float
    wind_load_factor: float


@dataclass(frozen=True)
class TowerCyclicResult:
    model_name: str
    history: list[TowerCyclicPoint]
    converged: bool
    completed_targets: int
    requested_targets: int
    failed_target: float | None
    runtime_seconds: float
    gravity_control_displacement: float
    control_height: float
    internal_force_database: str
    element_count: int
    calibration_summary: dict[str, Any]


def default_protocol() -> tuple[float, ...]:
    """Symmetric control-point drift history ending at the gravity position."""

    return cyclic_targets((0.001, 0.003, 0.006, 0.010))


def _configure_static(increment: float, control_node: int, control_dof: int) -> None:
    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("UmfPack")
    ops.test("NormDispIncr", 1e-6, 120, 0)
    ops.algorithm("Newton")
    ops.integrator("DisplacementControl", control_node, control_dof, increment)
    ops.analysis("Static")


def _apply_gravity(model: Any, steps: int = 10, on_step=None) -> Any:
    gravity = GravityLoadApplier(tag_manager=model.tag_manager)
    gravity_result = gravity.apply_from_model(model)
    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("UmfPack")
    ops.test("NormDispIncr", 1e-7, 120, 0)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0 / steps)
    ops.analysis("Static")
    for step in range(steps):
        if ops.analyze(1) != 0:
            raise RuntimeError(f"重力分析在第 {step + 1}/{steps} 步未收敛。")
        if on_step is not None:
            on_step(step + 1, steps, gravity_result)
    ops.loadConst("-time", 0.0)
    return gravity_result


def _base_shear(base_nodes: Sequence[int], dof: int) -> float:
    ops.reactions()
    return -sum(float(ops.nodeReaction(int(node), dof)) for node in base_nodes)


def _calibration_summary(model: Any) -> dict[str, Any]:
    records = list(getattr(model, "calibration_records", {}).values())
    methods: dict[str, int] = {}
    for record in records:
        method = str(record.get("method", "unknown"))
        methods[method] = methods.get(method, 0) + 1
    return {
        "group_count": len(records),
        "methods": methods,
        "reference_groups_fully_converged": sum(
            bool(record.get("converged")) for record in records
        ),
        "reference_runtime_seconds": sum(
            float(record.get("runtime_seconds", 0.0)) for record in records
        ),
        "cache": getattr(model,"calibration_cache_info",{}),
    }


def _build_model(
    model_name: str,
    *,
    source: Path,
    output_dir: Path,
    calibration_cache: Path,
    imperfection_ratio: float,
    reference_divisions: int,
    allow_legacy_calibration_cache: bool = False,
    calibration_fallback_policy: str = "error",
) -> Any:
    ops.wipe()
    if model_name == "equivalent":
        model = OpenSeesModelWithEquivalentImperfection(
            source,
            output_dir=output_dir / "model_data",
            imperfection_ratio=imperfection_ratio,
            calibration_method="reference",
            calibration_length_bin=0.01,
            calibration_steps=120,
            calibration_divisions=16,
            calibration_cache=calibration_cache,
            allow_legacy_calibration_cache=allow_legacy_calibration_cache,
            calibration_fallback_policy=calibration_fallback_policy,
        )
    elif model_name == "segmented_reference":
        model = OpenSeesModelWithBuckling(
            source,
            output_dir=output_dir / "model_data",
            random_disp_ratio=imperfection_ratio,
            member_divisions=reference_divisions,
            imperfection_seed=30103,
        )
    else:
        raise ValueError(f"未知全塔模型: {model_name}")
    model.model_tower()
    return model


def run_tower_cyclic(
    model_name: str,
    *,
    source: Path = DEFAULT_SOURCE,
    output_root: Path = DEFAULT_OUTPUT,
    target_drift_ratios: Sequence[float] | None = None,
    control_node: int = 350,
    control_dof: int = 2,
    maximum_increment: float = 0.005,
    minimum_increment: float = 0.0003125,
    imperfection_ratio: float = 1.0 / 1000.0,
    reference_divisions: int = 4,
    calibration_cache: Path | None = None,
    allow_legacy_calibration_cache: bool = False,
    calibration_fallback_policy: str = "error",
    local_members: Sequence[int] = (),
    record_fibers: bool = True,
    equilibrium_every: int = 0,
    solver_options: dict[str, Any] | None = None,
    probe_stages: Sequence[str] = (),
) -> TowerCyclicResult:
    source, output_root = Path(source), Path(output_root)
    output_dir = output_root / model_name
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"输出目录非空，禁止覆盖旧证据: {output_dir}")
    cache_path = Path(calibration_cache) if calibration_cache else output_root / "calibration_library.json"
    if model_name not in {"equivalent", "segmented_reference"}:
        raise ValueError(f"未知全塔模型: {model_name}")
    targets = tuple(default_protocol() if target_drift_ratios is None else target_drift_ratios)
    if not targets or any(not math.isfinite(value) for value in targets):
        raise ValueError("目标漂移序列必须非空且有限。")
    if not (0 < minimum_increment <= maximum_increment < math.inf):
        raise ValueError("需要 0 < minimum_increment <= maximum_increment < inf。")
    if isinstance(equilibrium_every,bool) or int(equilibrium_every)!=equilibrium_every or equilibrium_every<0:
        raise ValueError("equilibrium_every must be a nonnegative integer")
    quality=ResultQuality(purpose="independent_validation",domain_policy="diagnostic_continue")
    quality.set_coverage(len(targets),0,unit="targets")
    solver_options=dict(solver_options or {})
    allowed_solver_options={"convergence_test","algorithm_names","maximum_attempts_per_step",
        "maximum_total_attempts","maximum_accepted_steps","timeout_seconds","recovery_policy",
        "recovery_growth_factor","recovery_successes_before_growth"}
    if set(solver_options)-allowed_solver_options:
        raise ValueError(f"Unknown tower solver options: {set(solver_options)-allowed_solver_options}")
    test=solver_options.get("convergence_test",("NormDispIncr",1e-6,60,0))
    if not isinstance(test,(list,tuple)) or len(test) not in (3,4) or not isinstance(test[0],str) or not test[0]:
        raise ValueError("convergence_test requires name, positive tolerance and iteration count")
    if not math.isfinite(float(test[1])) or float(test[1])<=0 or isinstance(test[2],bool) or int(test[2])!=test[2] or test[2]<=0:
        raise ValueError("Invalid tower convergence tolerance/iterations")
    if "algorithm_names" in solver_options:
        names=solver_options["algorithm_names"]
        if not isinstance(names,(list,tuple)) or not names or any(n not in {"Newton","KrylovNewton","NewtonLineSearch"} for n in names):
            raise ValueError("Unsupported tower algorithm list")
    with RunManifest(
        output_root / model_name,
        parameters={
            "analysis": "full_tower_cyclic", "model": model_name,
            "targets": targets, "control_node": control_node, "control_dof": control_dof,
            "maximum_increment": maximum_increment, "minimum_increment": minimum_increment,
            "imperfection_ratio": imperfection_ratio, "reference_divisions": reference_divisions,
            "allow_legacy_calibration_cache": allow_legacy_calibration_cache,
            "calibration_fallback_policy": calibration_fallback_policy,
            "local_members": list(local_members), "record_fibers": record_fibers,
            "engine_version": ops.version(), "axis_semantics": "quasi_static_protocol_not_seconds",
            "convergence_test": ["NormDispIncr", 1e-6, 60, 0],
            "algorithms": ["Newton", "KrylovNewton", "NewtonLineSearch(0.8)"],
            "equilibrium_every":equilibrium_every,
            "equilibrium_policy":"stop_after_saving_committed_state" if equilibrium_every else "disabled",
            "equilibrium_thresholds":{"relative":1e-6,"force_absolute_N":0.001,"moment_absolute_Nm":0.001},
            "solver_options":solver_options,"probe_stages":list(probe_stages),
        },
        input_files=(
            source, Path(__file__), Path(__file__).with_name("material.py"),
            Path(__file__).with_name("experiment.py"),
            PROJECT_ROOT / "model" / "tower_model.py",
            PROJECT_ROOT / "model" / "tower_model_with_buckling.py",
            PROJECT_ROOT / "model" / "tower_model_with_equivalent_imperfection.py",
            PROJECT_ROOT / "util" / "processing" / "member_state_recorder.py",
            PROJECT_ROOT / "util" / "processing" / "internal_force_recorder.py",
            PROJECT_ROOT / "util" / "postprocess" / "energy.py",
            *((cache_path,) if model_name == "equivalent" and cache_path.is_file() else ()),
        ),
        seed=30103,
        quality=quality,
    ) as run:
        try:
            result = _run_tower_cyclic(
                model_name, source=source, output_root=output_root, target_drift_ratios=targets,
                control_node=control_node, control_dof=control_dof,
                maximum_increment=maximum_increment, minimum_increment=minimum_increment,
                imperfection_ratio=imperfection_ratio, reference_divisions=reference_divisions,
                run=run,
                calibration_cache=cache_path,
                allow_legacy_calibration_cache=allow_legacy_calibration_cache,
                calibration_fallback_policy=calibration_fallback_policy,
                local_members=local_members, record_fibers=record_fibers,
                equilibrium_every=equilibrium_every,
                solver_options=solver_options,probe_stages=probe_stages,
            )
            run.update(completed_steps=len(result.history) - 1, completed_targets=result.completed_targets)
            run.add_artifact("internal_forces", result.internal_force_database)
            run.add_artifact("cyclic_history", output_root / model_name / "cyclic_history.csv")
            if local_members:
                run.add_artifact("member_states", output_dir / "member_states.jsonl")
                run.add_artifact("member_metadata", output_dir / "member_states.metadata.json")
            if model_name == "equivalent" and cache_path.is_file():
                run.add_artifact("calibration_library", cache_path)
            if equilibrium_every:
                run.add_artifact("equilibrium_checks",output_dir/"equilibrium_checks.jsonl")
            run.add_artifact("solver_attempts",output_dir/"attempts.jsonl")
            for name in ("external_work.json","external_work_states.jsonl"):
                if (output_dir/name).is_file():
                    run.add_artifact(name,output_dir/name)
            quality.set_coverage(len(targets),result.completed_targets,unit="targets")
            run.set_quality(quality)
            run.finish(converged=result.converged, failed_target=result.failed_target)
            return result
        finally:
            ops.wipe()


def _run_tower_cyclic(
    model_name: str,
    *,
    source: Path,
    output_root: Path,
    target_drift_ratios: Sequence[float],
    control_node: int,
    control_dof: int,
    maximum_increment: float,
    minimum_increment: float,
    imperfection_ratio: float,
    reference_divisions: int,
    run: RunManifest,
    calibration_cache: Path | None = None,
    allow_legacy_calibration_cache: bool = False,
    calibration_fallback_policy: str = "error",
    local_members: Sequence[int] = (),
    record_fibers: bool = True,
    equilibrium_every: int = 0,
    solver_options: dict[str, Any] | None = None,
    probe_stages: Sequence[str] = (),
) -> TowerCyclicResult:
    started = time.perf_counter()
    target_ratios = tuple(target_drift_ratios)
    output_dir = output_root / model_name
    output_dir.mkdir(parents=True, exist_ok=True)
    model = _build_model(
        model_name,
        source=source,
        output_dir=output_dir,
        calibration_cache=calibration_cache or output_root / "calibration_library.json",
        imperfection_ratio=imperfection_ratio,
        reference_divisions=reference_divisions,
        allow_legacy_calibration_cache=allow_legacy_calibration_cache,
        calibration_fallback_policy=calibration_fallback_policy,
    )
    resolved_control_node = model.resolve_node_tag(control_node)
    base_nodes = [model.resolve_node_tag(node) for node in BASE_NODE_TAGS]
    control_height = float(model.get_node_coord(control_node)[2])
    quality=run.quality
    quality.add_evidence("member_history",str(output_dir/"member_states.jsonl"),"Committed member states, if enabled")
    if model_name=="equivalent":
        quality.add_evidence("calibration",str(calibration_cache or output_root/"calibration_library.json"))
        for tag,material in model.equivalent_materials.items():
            compression=[p.strain for p in material.compression_envelope]
            tension=[p.strain for p in material.tension_envelope()]
            quality.register_domain(MemberDomainRange(member_id=tag,quantity="equivalent_strain",
                lower=min(compression),upper=max(tension),evidence_ids=("calibration",),unit="dimensionless"))
    constraints={(int(node),dof) for node,fix in model.fix_map.items()
                 for dof,name in enumerate(("ux","uy","uz","rx","ry","rz"),1) if fix[name]}
    rotations={(int(node),dof) for node in model.node_map for dof in (4,5,6)}
    gravity_loads={}

    def check_equilibrium(step,stage,gravity_factor,wind=None):
        if not equilibrium_every:
            return
        from util.analysis.equilibrium_checks import static_equilibrium,require_equilibrium
        loads={}
        for node,vector in gravity_loads.items():
            for dof,value in enumerate(vector,1):
                loads[node,dof]=gravity_factor*float(value)
        if wind is not None:
            factor=float(ops.getLoadFactor(wind.pattern_tag))
            for node,vector in wind.applied_loads.items():
                for dof,value in enumerate(vector,1):
                    loads[node,dof]=loads.get((node,dof),0.0)+factor*float(value)
        scale=max(1.0,sum(abs(v) for v in loads.values()))
        report=static_equilibrium(ops,loads,constrained_dofs=constraints,rotational_dofs=rotations,
            force_scale=scale,moment_scale=scale*control_height,
            force_absolute_tolerance=.001,moment_absolute_tolerance=.001,relative_tolerance=1e-6)
        residuals=report.pop("free_dof_residuals")
        report.update(step=step,stage_id=stage,domain_time=float(ops.getTime()),
            largest_residuals=sorted(residuals,key=lambda x:abs(x["residual"]),reverse=True)[:12])
        with (output_dir/"equilibrium_checks.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(report,ensure_ascii=False,allow_nan=False)+'\n')
        require_equilibrium(report)
    local_recorder = MemberStateRecorder(model, output_dir / "member_states.jsonl",
        members=local_members, record_fibers=record_fibers) if local_members else None
    try:
        if local_recorder:
            local_recorder.capture(stage_id="initial", step=0, progress=0.0)
        def capture_gravity(step, count, gravity):
            gravity_loads.update(gravity.node_loads)
            if local_recorder:
                local_recorder.capture(stage_id="gravity", step=step, progress=step/count,
                    direction=1, loads={"gravity_factor":float(ops.getLoadFactor(gravity.pattern_tag)),
                                        "pattern_tag":gravity.pattern_tag})
            if step==count:
                check_equilibrium(step,"gravity",float(ops.getLoadFactor(gravity.pattern_tag)))
        _apply_gravity(model, on_step=capture_gravity)
    except BaseException:
        if local_recorder:
            local_recorder.close()
        raise
    gravity_displacement = float(ops.nodeDisp(resolved_control_node, control_dof))

    wind = PushoverWindLoadApplier(tag_manager=model.tag_manager, load_dof=control_dof)
    wind_result = wind.apply_from_model(model)
    work_keys={(int(n),d) for ledger in (gravity_loads,wind_result.applied_loads)
               for n,vector in ledger.items() for d,value in enumerate(vector,1) if value!=0}
    work_states=[]
    def capture_work(step,stage):
        factor=float(ops.getLoadFactor(wind_result.pattern_tag))
        forces={f"{n}:{d}": float(gravity_loads.get(n,(0,)*6)[d-1])+
                factor*float(wind_result.applied_loads.get(n,(0,)*6)[d-1]) for n,d in work_keys}
        row={"source_step":step,"stage_id":stage,"state":"committed",
             "displacements":{f"{n}:{d}":float(ops.nodeDisp(n,d)) for n,d in work_keys},
             "external_forces":forces}
        work_states.append(row)
        with (output_dir/"external_work_states.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(row,allow_nan=False)+'\n')
    capture_work(0,"gravity_end")
    database_path = output_dir / "tower_internal_forces.sqlite"
    history: list[TowerCyclicPoint] = []
    with ExitStack() as stack:
        if local_recorder:
            stack.callback(local_recorder.close)
        recorder = TowerInternalForceRecorder(
            model, database_path, overwrite=False, record_every=1, commit_every=20)
        stack.callback(recorder.close)
        recorder.capture(step=0, time=0.0)
        history.append(
            TowerCyclicPoint(
                step=0, stage="gravity", target_displacement=0.0,
                control_displacement=gravity_displacement,
                relative_displacement=0.0, drift_ratio=0.0,
                base_shear=_base_shear(base_nodes, control_dof),
                wind_load_factor=float(ops.getLoadFactor(wind_result.pattern_tag)),
            )
        )
        _configure_static(maximum_increment, resolved_control_node, control_dof)
        attempts_stream=stack.enter_context((output_dir/"attempts.jsonl").open("x",encoding="utf-8"))
        context={"stage_id":"initial","source_step":0}
        def record_attempt(event):
            row={**context,**event,"state":"committed" if event["return_code"]==0 else "trial_failed"}
            attempts_stream.write(json.dumps(row,allow_nan=False)+'\n')
            attempts_stream.flush()
        options=dict(solver_options or {})
        if "algorithm_names" in options:
            names=options.pop("algorithm_names")
            if not names or any(name not in {"Newton","KrylovNewton","NewtonLineSearch"} for name in names):
                raise ValueError("Unsupported tower algorithm list")
            options["algorithms"]=tuple(Algorithm(name,(.8,) if name=="NewtonLineSearch" else ()) for name in names)
        stepper = AdaptiveStepper(
            ops,
            progress=lambda: float(ops.nodeDisp(resolved_control_node, control_dof)),
            configure_increment=lambda increment: ops.integrator(
                "DisplacementControl", resolved_control_node, control_dof, increment
            ),
            minimum_increment=minimum_increment,
            on_attempt=record_attempt,**options,
        )
        run.update(solver_settings=stepper.settings())
        def committed(step,stage,is_endpoint):
            context.update(source_step=step)
            capture_work(step,stage)
            if model_name=="equivalent":
                for tag in model.equivalent_materials:
                    strain=float(ops.eleResponse(tag,"section",1,"deformation")[0])
                    quality.observe_member_state(tag,"equivalent_strain",strain,accepted_step=step,
                        stage_id=stage,evidence_ids=("calibration",))
            if equilibrium_every and (step%equilibrium_every==0 or is_endpoint):
                check_equilibrium(step,stage,1.0,wind_result)
            if is_endpoint and stage in probe_stages:
                from .diagnostic_probe import probe_tangent
                report=probe_tangent(ops,output_dir/f"probe_{step:06d}",event_id=stage,modes=3)
                if report["status"]!="completed":
                    raise RuntimeError(f"Requested stiffness probe failed: {report['status']}; see saved probe.json")
        completed_targets, failed_target = _run_cyclic_targets(
            target_ratios, control_height, gravity_displacement, resolved_control_node,
            control_dof, maximum_increment, stepper, recorder, history, base_nodes,
            wind_result.pattern_tag, run,
            local_recorder=local_recorder,
            on_committed=committed,
            on_stage_begin=lambda stage:context.update(stage_id=stage),
        )
    converged = failed_target is None
    result = TowerCyclicResult(
        model_name=model_name, history=history, converged=converged,
        completed_targets=completed_targets, requested_targets=len(target_ratios),
        failed_target=failed_target, runtime_seconds=time.perf_counter() - started,
        gravity_control_displacement=gravity_displacement, control_height=control_height,
        internal_force_database=str(database_path.resolve()), element_count=len(model.element_map),
        calibration_summary=_calibration_summary(model),
    )
    _write_model_outputs(output_dir, result)
    if len(work_states)>=2:
        from util.postprocess.energy import conjugate_external_work
        work=conjugate_external_work(work_states,all_applied_dofs_included=True,
                                    constraint_work_included=True)
        work.update(scope="cyclic_protocol_starting_at_completed_gravity",
                    gravity_preload_work_included=False,
                    constraints="stationary fixed supports; displacement control adjusts load factor, no moving SP")
        (output_dir/"external_work.json").write_text(json.dumps(work,indent=2,allow_nan=False)+'\n',encoding="utf-8")
    return result


def _run_cyclic_targets(
    target_ratios: Sequence[float], control_height: float, gravity_displacement: float,
    resolved_control_node: int, control_dof: int, maximum_increment: float,
    stepper: AdaptiveStepper, recorder: TowerInternalForceRecorder,
    history: list[TowerCyclicPoint], base_nodes: Sequence[int], wind_pattern: int,
    run: RunManifest,
    local_recorder: MemberStateRecorder | None = None,
    on_committed=None,
    on_stage_begin=None,
) -> tuple[int, float | None]:
    completed_targets = 0
    global_step = 0
    for target_index, target_ratio in enumerate(target_ratios, start=1):
        target_relative = float(target_ratio) * control_height
        absolute_target = gravity_displacement + target_relative
        stage = f"target_{target_index}_{target_ratio:+.6f}"
        if on_stage_begin:
            on_stage_begin(stage)
        stage_start = float(ops.nodeDisp(resolved_control_node, control_dof))
        stage_delta = absolute_target-stage_start
        direction = 1 if stage_delta > 0 else -1 if stage_delta < 0 else 0
        if local_recorder:
            local_recorder.capture(stage_id=stage,step=global_step,progress=0.0,
                direction=direction,cycle_id=(target_index+1)//2,
                loads={"wind_factor":float(ops.getLoadFactor(wind_pattern))})
        next_limit=maximum_increment
        recovery_successes=0
        while True:
            current = float(ops.nodeDisp(resolved_control_node, control_dof))
            remaining = absolute_target - current
            if abs(remaining) <= 1e-9:
                completed_targets = target_index
                break
            trial = math.copysign(min(abs(remaining), next_limit), remaining)
            step_result=stepper.step(trial)
            if not step_result.converged:
                run.update(completed_steps=global_step, completed_targets=completed_targets,
                           failed_target=target_ratio, solver=stepper.diagnostics(),
                           stop_reason=step_result.stop_reason)
                return completed_targets, target_ratio
            if stepper.recovery_policy!="legacy":
                if abs(step_result.accepted_increment)<abs(step_result.requested_increment):
                    next_limit=min(maximum_increment,abs(step_result.accepted_increment))
                    recovery_successes=0
                elif stepper.recovery_policy=="gradual":
                    recovery_successes+=1
                    if recovery_successes>=stepper.recovery_successes_before_growth:
                        next_limit=min(maximum_increment,next_limit*stepper.recovery_growth_factor)
                        recovery_successes=0
            global_step += 1
            displacement = float(ops.nodeDisp(resolved_control_node, control_dof))
            relative = displacement - gravity_displacement
            recorder.capture(step=global_step, time=float(global_step))
            if local_recorder:
                local_recorder.capture(stage_id=stage,step=global_step,
                    progress=(displacement-stage_start)/stage_delta if stage_delta else 1.0,
                    direction=direction,cycle_id=(target_index+1)//2,
                    loads={"wind_factor":float(ops.getLoadFactor(wind_pattern))})
            history.append(
                TowerCyclicPoint(
                    step=global_step,
                    stage=stage,
                    target_displacement=target_relative,
                    control_displacement=displacement,
                    relative_displacement=relative,
                    drift_ratio=relative / control_height,
                    base_shear=_base_shear(base_nodes, control_dof),
                    wind_load_factor=float(ops.getLoadFactor(wind_pattern)),
                )
            )
            if on_committed:
                on_committed(global_step,stage,abs(absolute_target-displacement)<=1e-9)
            if global_step % 20 == 0:
                run.update(completed_steps=global_step, completed_targets=completed_targets,
                           solver=stepper.diagnostics())
        run.update(completed_steps=global_step, completed_targets=completed_targets,
                   failed_target=None, solver=stepper.diagnostics())
    return completed_targets, None


def _write_model_outputs(output_dir: Path, result: TowerCyclicResult) -> None:
    with (output_dir / "cyclic_history.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(asdict(result.history[0])))
        writer.writeheader()
        writer.writerows(asdict(point) for point in result.history)
    force_history = TowerInternalForceHistory(result.internal_force_database)
    force_history.export_envelope_csv(output_dir / "internal_force_envelope.csv")


def _loop_energy(history: Sequence[TowerCyclicPoint]) -> float:
    if len(history) < 2:
        return 0.0
    return abs(path_work((point.relative_displacement, point.base_shear) for point in history))


def _result_summary(result: TowerCyclicResult) -> dict[str, Any]:
    final = result.history[-1]
    return {
        "model_name": result.model_name,
        "converged": result.converged,
        "completed_targets": result.completed_targets,
        "requested_targets": result.requested_targets,
        "failed_target_drift_ratio": result.failed_target,
        "runtime_seconds": result.runtime_seconds,
        "element_count": result.element_count,
        "control_height": result.control_height,
        "gravity_control_displacement": result.gravity_control_displacement,
        "maximum_positive_base_shear": max(point.base_shear for point in result.history),
        "minimum_negative_base_shear": min(point.base_shear for point in result.history),
        "maximum_absolute_drift_ratio": max(
            abs(point.drift_ratio) for point in result.history
        ),
        "final_relative_displacement": final.relative_displacement,
        "final_base_shear": final.base_shear,
        "signed_path_work_absolute": _loop_energy(result.history),
        "base_shear_top_displacement_area_absolute_Nm": _loop_energy(result.history),
        "area_interpretation": "Vbase-utop chart area; not total conjugate external work or dissipation",
        "history_steps": len(result.history) - 1,
        "internal_force_database": result.internal_force_database,
        "calibration": result.calibration_summary,
    }


def create_comparison_outputs(
    output_root: Path,
    results: Sequence[TowerCyclicResult],
    protocol: Sequence[float],
) -> dict[str, Any]:
    summaries = {result.model_name: _result_summary(result) for result in results}
    payload: dict[str, Any] = {
        "protocol": {
            "type": "quasi-static displacement-controlled cyclic",
            "target_drift_ratios": list(protocol),
            "control_node": 350,
            "control_dof": 2,
            "base_nodes": list(BASE_NODE_TAGS),
            "imperfection_ratio": 1.0 / 1000.0,
        },
        "models": summaries,
    }
    result_map = {result.model_name: result for result in results}
    if {"equivalent", "segmented_reference"} <= set(result_map):
        payload["comparison"] = _write_comparison_tables(
            output_root,
            result_map["equivalent"],
            result_map["segmented_reference"],
        )
    (output_root / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    figure, axis = plt.subplots(figsize=(9.0, 6.0))
    labels = {
        "equivalent": "Equivalent axial law + elastic beam stiffness",
        "segmented_reference": "Segmented geometric-imperfection reference",
    }
    for result in results:
        axis.plot(
            [point.relative_displacement * 1000.0 for point in result.history],
            [point.base_shear / 1000.0 for point in result.history],
            linewidth=1.4,
            label=labels.get(result.model_name, result.model_name),
        )
        if not result.converged:
            last = result.history[-1]
            axis.scatter(
                [last.relative_displacement * 1000.0],
                [last.base_shear / 1000.0],
                marker="x",
                s=90,
                linewidths=2.0,
                color="crimson",
                zorder=5,
                label=f"{result.model_name} stopped",
            )
    axis.axhline(0.0, color="0.5", linewidth=0.8)
    axis.axvline(0.0, color="0.5", linewidth=0.8)
    axis.set_xlabel("Control-point displacement relative to gravity state (mm)")
    axis.set_ylabel("Base shear (kN)")
    axis.set_title("Z30103A6 full-tower cyclic response")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_root / "base_shear_displacement.png", dpi=180)
    plt.close(figure)
    return payload


def _stage_endpoints(result: TowerCyclicResult) -> dict[str, TowerCyclicPoint]:
    endpoints: dict[str, TowerCyclicPoint] = {}
    for point in result.history:
        endpoints[point.stage] = point
    return endpoints


def _physical_axial_envelope(
    database_path: str,
    *,
    end_step: int | None = None,
) -> dict[int, float]:
    where = "" if end_step is None else "WHERE h.step <= ?"
    query = """
        SELECT COALESCE(e.original_element_tag, e.element_tag) AS physical_tag,
               MAX(MAX(ABS(h.p_i), ABS(h.p_j))) AS axial_abs_max
        FROM force_history h JOIN elements e USING(element_tag)
        {where}
        GROUP BY physical_tag ORDER BY physical_tag
    """.format(where=where)
    with sqlite3.connect(database_path) as connection:
        parameters = () if end_step is None else (int(end_step),)
        return {
            int(tag): float(value)
            for tag, value in connection.execute(query, parameters)
        }


def _write_comparison_tables(
    output_root: Path,
    equivalent: TowerCyclicResult,
    reference: TowerCyclicResult,
) -> dict[str, Any]:
    equivalent_targets = _stage_endpoints(equivalent)
    reference_targets = _stage_endpoints(reference)
    common_stages = [
        stage
        for stage in reference_targets
        if stage != "gravity" and stage in equivalent_targets
    ]
    completed_common_targets = min(
        equivalent.completed_targets,
        reference.completed_targets,
    )
    common_stages = common_stages[:completed_common_targets]
    target_rows = []
    for stage in common_stages:
        eq_point = equivalent_targets[stage]
        ref_point = reference_targets[stage]
        denominator = max(abs(ref_point.base_shear), 1e-12)
        target_rows.append(
            {
                "stage": stage,
                "target_displacement_m": ref_point.target_displacement,
                "equivalent_base_shear_n": eq_point.base_shear,
                "reference_base_shear_n": ref_point.base_shear,
                "error_percent": 100.0
                * (eq_point.base_shear - ref_point.base_shear)
                / denominator,
            }
        )
    with (output_root / "target_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=["stage", "target_displacement_m",
            "equivalent_base_shear_n", "reference_base_shear_n", "error_percent"])
        writer.writeheader()
        writer.writerows(target_rows)

    if not common_stages:
        return {"common_target_count":0,"comparison_end_stage":None,
                "coverage":0.0,"reason":"No jointly completed protocol target; no extrapolation"}

    equivalent_end_step = equivalent_targets[common_stages[-1]].step
    reference_end_step = reference_targets[common_stages[-1]].step
    equivalent_envelope = _physical_axial_envelope(
        equivalent.internal_force_database,
        end_step=equivalent_end_step,
    )
    reference_envelope = _physical_axial_envelope(
        reference.internal_force_database,
        end_step=reference_end_step,
    )
    common_elements = sorted(equivalent_envelope.keys() & reference_envelope.keys())
    if not common_elements:
        return {"common_target_count":len(common_stages),"physical_member_count":0,
                "reason":"No common physical member force records"}
    envelope_rows = [
        {
            "original_element_tag": tag,
            "equivalent_axial_abs_max_n": equivalent_envelope[tag],
            "reference_axial_abs_max_n": reference_envelope[tag],
            "error_percent": 100.0
            * (equivalent_envelope[tag] - reference_envelope[tag])
            / max(reference_envelope[tag], 1e-12),
        }
        for tag in common_elements
    ]
    with (output_root / "axial_force_envelope_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=list(envelope_rows[0]))
        writer.writeheader()
        writer.writerows(envelope_rows)

    x = [reference_envelope[tag] for tag in common_elements]
    y = [equivalent_envelope[tag] for tag in common_elements]
    maximum_reference = max(x)
    rmse = math.sqrt(sum((eq - ref) ** 2 for eq, ref in zip(y, x)) / len(x))
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    covariance = sum((ref - mean_x) * (eq - mean_y) for ref, eq in zip(x, y))
    variance = math.sqrt(
        sum((ref - mean_x) ** 2 for ref in x)
        * sum((eq - mean_y) ** 2 for eq in y)
    )
    correlation = covariance / variance if variance else 1.0

    figure, axis = plt.subplots(figsize=(7.2, 6.4))
    axis.scatter(
        [value / 1000.0 for value in x],
        [value / 1000.0 for value in y],
        s=10,
        alpha=0.45,
    )
    limit = 1.03 * max(max(x), max(y)) / 1000.0
    axis.plot([0.0, limit], [0.0, limit], "k--", linewidth=1.0, label="1:1")
    axis.set_xlim(0.0, limit)
    axis.set_ylim(0.0, limit)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Segmented-reference axial-force envelope (kN)")
    axis.set_ylabel("Equivalent-model axial-force envelope (kN)")
    axis.set_title("Physical-member axial-force envelope comparison")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_root / "axial_force_envelope_comparison.png", dpi=180)
    plt.close(figure)

    return {
        "common_target_count": len(target_rows),
        "comparison_end_stage": common_stages[-1],
        "comparison_end_steps": {
            "equivalent": equivalent_end_step,
            "segmented_reference": reference_end_step,
        },
        "maximum_target_base_shear_error_percent": max(
            abs(row["error_percent"]) for row in target_rows
        ),
        "physical_member_count": len(common_elements),
        "axial_envelope_correlation": correlation,
        "axial_envelope_nrmse_percent_of_reference_max": 100.0
        * rmse
        / maximum_reference,
        "equivalent_to_reference_runtime_ratio": equivalent.runtime_seconds
        / reference.runtime_seconds,
    }


def load_saved_result(output_root: Path, model_name: str) -> TowerCyclicResult | None:
    """Reload one completed run so separate CLI invocations can be compared."""

    history_path = output_root / model_name / "cyclic_history.csv"
    summary_path = output_root / "summary.json"
    if not history_path.exists() or not summary_path.exists():
        return None
    previous = json.loads(summary_path.read_text(encoding="utf-8"))
    model_summary = previous.get("models", {}).get(model_name)
    if model_summary is None:
        return None
    with history_path.open("r", encoding="utf-8", newline="") as file:
        history = [
            TowerCyclicPoint(
                step=int(row["step"]),
                stage=row["stage"],
                target_displacement=float(row["target_displacement"]),
                control_displacement=float(row["control_displacement"]),
                relative_displacement=float(row["relative_displacement"]),
                drift_ratio=float(row["drift_ratio"]),
                base_shear=float(row["base_shear"]),
                wind_load_factor=float(row["wind_load_factor"]),
            )
            for row in csv.DictReader(file)
        ]
    return TowerCyclicResult(
        model_name=model_name,
        history=history,
        converged=bool(model_summary["converged"]),
        completed_targets=int(model_summary["completed_targets"]),
        requested_targets=int(model_summary["requested_targets"]),
        failed_target=model_summary.get("failed_target_drift_ratio"),
        runtime_seconds=float(model_summary["runtime_seconds"]),
        gravity_control_displacement=float(model_summary["gravity_control_displacement"]),
        control_height=float(model_summary["control_height"]),
        internal_force_database=str(model_summary["internal_force_database"]),
        element_count=int(model_summary["element_count"]),
        calibration_summary=dict(model_summary.get("calibration", {})),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Z30103A6 全塔准静力往复试验。")
    parser.add_argument(
        "--model",
        action="append",
        choices=("equivalent", "segmented_reference"),
        help="可重复指定；默认依次计算两个模型。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--maximum-increment", type=float, default=0.005)
    parser.add_argument("--minimum-increment", type=float, default=0.0003125)
    parser.add_argument("--reference-divisions", type=int, default=4)
    parser.add_argument("--calibration-cache",type=Path)
    parser.add_argument("--allow-legacy-calibration-cache",action="store_true")
    parser.add_argument("--calibration-fallback-policy",choices=("error","perry_exploratory"),default="error")
    parser.add_argument("--local-members",nargs="*",type=int,default=[])
    parser.add_argument("--no-local-fibers",action="store_true")
    parser.add_argument("--equilibrium-every",type=int,default=0)
    parser.add_argument("--tolerance",type=float,default=1e-6)
    parser.add_argument("--iterations",type=int,default=60)
    parser.add_argument("--algorithms",nargs="+",choices=("Newton","KrylovNewton","NewtonLineSearch"),
                        default=["Newton","KrylovNewton","NewtonLineSearch"])
    parser.add_argument("--recovery-policy",choices=("legacy","last_success","gradual"),default="legacy")
    parser.add_argument("--maximum-accepted-steps",type=int)
    parser.add_argument("--maximum-total-attempts",type=int)
    parser.add_argument("--timeout-seconds",type=float)
    parser.add_argument("--probe-stages",nargs="*",default=[])
    parser.add_argument("--target-drifts",nargs="+",type=float)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    models = args.model or ["equivalent", "segmented_reference"]
    protocol = tuple(args.target_drifts) if args.target_drifts is not None else default_protocol()
    results = []
    for model_name in models:
        print(f"开始全塔往复试验: {model_name}", flush=True)
        result = run_tower_cyclic(
            model_name,
            source=args.source,
            output_root=args.output,
            target_drift_ratios=protocol,
            maximum_increment=args.maximum_increment,
            minimum_increment=args.minimum_increment,
            reference_divisions=args.reference_divisions,
            calibration_cache=args.calibration_cache,
            allow_legacy_calibration_cache=args.allow_legacy_calibration_cache,
            calibration_fallback_policy=args.calibration_fallback_policy,
            local_members=args.local_members,record_fibers=not args.no_local_fibers,
            equilibrium_every=args.equilibrium_every,
            solver_options={"convergence_test":["NormDispIncr",args.tolerance,args.iterations,0],
                "algorithm_names":args.algorithms,"recovery_policy":args.recovery_policy,
                "maximum_accepted_steps":args.maximum_accepted_steps,
                "maximum_total_attempts":args.maximum_total_attempts,"timeout_seconds":args.timeout_seconds},
            probe_stages=args.probe_stages,
        )
        results.append(result)
        print(
            f"完成 {model_name}: targets={result.completed_targets}/"
            f"{result.requested_targets}, steps={len(result.history) - 1}, "
            f"runtime={result.runtime_seconds:.1f}s",
            flush=True,
        )
    for model_name in ("equivalent", "segmented_reference"):
        if model_name in models:
            continue
        saved = load_saved_result(args.output, model_name)
        if saved is not None:
            results.append(saved)
    create_comparison_outputs(args.output, results, protocol)


if __name__ == "__main__":
    main()
