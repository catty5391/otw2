"""General global nodal loads, independent of wind/rain generation.

Reference translations use N, rotations N m, and Path time seconds. Supply
the node's actual DOF layout (e.g. 3D frame: Fx,Fy,Fz,Mx,My,Mz). Loads are
already forces, never pressure, wind speed, rainfall or permanent added mass.

One shared TagManager must own all timeSeries/pattern tags in a domain.
These functions never freeze loads, reset time or change mass/analysis.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math


def _ops(ops_module):
    if ops_module is None:
        import openseespy.opensees as ops_module
    return ops_module


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean is not a physical number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: finite number required") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name}: finite number required")
    return result


def _node_tag(key):
    try:
        tag = int(key)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("positive integer node tags required") from exc
    if isinstance(key, (bool, str)) or tag != key or tag <= 0:
        raise ValueError("positive integer node tags required")
    return tag


def validate_nodal_loads(loads, *, ndf=None):
    """Validate without querying or mutating OpenSees; copy caller inputs."""
    if not isinstance(loads, Mapping) or not loads:
        raise ValueError("nonempty node -> global load vector mapping required")
    result = {}
    for key, vector in loads.items():
        tag = _node_tag(key)
        try:
            v = tuple(_finite(x, f"node {tag} load") for x in vector)
        except TypeError as exc:
            raise ValueError(f"node {tag}: load vector required") from exc
        if not v or (ndf is not None and len(v) != ndf):
            raise ValueError(f"node {tag}: {'nonempty' if ndf is None else str(ndf)+'-DOF'} load vector required")
        result[tag] = v
    return result


def merge_nodal_loads(*mappings):
    """Sum same-node vectors; do not discard rain's vertical component/moments."""
    result = {}
    for loads in mappings:
        if not loads:
            continue
        for tag, vector in validate_nodal_loads(loads).items():
            old = result.get(tag, (0.,)*len(vector))
            if len(old) != len(vector):
                raise ValueError(f"node {tag}: cannot combine different DOF layouts")
            result[tag] = tuple(_finite(a+b, "combined load") for a,b in zip(old,vector))
    return result


def _check_domain(loads, ops):
    nodes = set(ops.getNodeTags())
    for tag, vector in loads.items():
        if tag not in nodes:
            raise ValueError(f"node {tag} missing from OpenSees domain")
        count = len(ops.nodeDisp(tag))
        if len(vector) != count:
            raise ValueError(f"node {tag}: {len(vector)} loads supplied, actual ndf={count}")


@dataclass(frozen=True)
class _Series:
    kind: str
    values: tuple = ()
    dt: float | None = None
    absolute_times: tuple = ()
    start: float = 0.
    hold_last: bool = False

    def arguments(self, tag):
        if self.kind != "Path":
            return self.kind, tag
        options = ("-useLast",) if self.hold_last else ()
        if self.dt is not None:
            return ("Path", tag, "-dt", self.dt, "-startTime", self.start,
                    "-values", *self.values, *options)
        return ("Path", tag, "-time", *self.absolute_times,
                "-values", *self.values, *options)


def _series(kind, current, *, values=None, dt=None, times=None, start_time=None,
            hold_last=False, allow_nonzero_initial=False):
    current = _finite(current, "domain time")
    if kind not in {"Linear", "Constant", "Path"}:
        raise ValueError("supported time series: Linear, Constant, Path")
    if not isinstance(hold_last, bool) or not isinstance(allow_nonzero_initial, bool):
        raise ValueError("hold_last and allow_nonzero_initial must be bool")
    if kind != "Path":
        if any(x is not None for x in (values,dt,times,start_time)) or hold_last:
            raise ValueError("Path parameters only apply to Path")
        if kind == "Linear" and abs(current) > 1e-12:
            raise ValueError("Linear loads require domain time=0; explicitly freeze/reset before adding loads")
        return _Series(kind)
    if values is None:
        raise ValueError("Path values are required")
    try:
        vals = tuple(_finite(v,"Path value") for v in values)
    except TypeError as exc:
        raise ValueError("Path values must be a sequence") from exc
    if len(vals) < 2:
        raise ValueError("Path requires at least two values")
    if not allow_nonzero_initial and vals[0] != 0:
        raise ValueError("Path must start from zero; set allow_nonzero_initial=True only with an explicit initial-state treatment")
    if (dt is None) == (times is None):
        raise ValueError("supply exactly one of dt or times")
    start = current if start_time is None else _finite(start_time,"start_time")
    if dt is not None:
        dt = _finite(dt,"dt")
        if dt <= 0:raise ValueError("dt must be positive")
        end = _finite(start+(len(vals)-1)*dt,"Path end time")
        if start+dt <= start or end <= start:
            raise ValueError("time increments are below floating-point resolution")
        return _Series(kind,vals,dt,(),start,hold_last)
    relative = tuple(_finite(v,"relative time") for v in times)
    if len(relative) != len(vals) or relative[0] != 0 or any(b<=a for a,b in zip(relative,relative[1:])):
        raise ValueError("times must start at 0, strictly increase and match number of samples")
    absolute = tuple(_finite(start+t,"absolute time") for t in relative)
    if any(b<=a for a,b in zip(absolute,absolute[1:])):
        raise ValueError("time increments are below floating-point resolution")
    return _Series(kind,vals,None,absolute,start,hold_last)


@dataclass
class AppliedNodalLoads:
    """One spatial load vector and its scalar factor; reference loads are SI."""
    time_series_tag: int
    pattern_tag: int
    applied_loads: dict
    name: str = "load"
    series_type: str = "Linear"
    _removed: bool = field(default=False, repr=False)
    companions: tuple = field(default=(), repr=False)

    @property
    def pattern_tags(self):
        return tuple(item.pattern_tag for item in _parts(self))

    @property
    def time_series_tags(self):
        return tuple(item.time_series_tag for item in _parts(self))


@dataclass
class AppliedNodalHistory:
    """A nonproportional nodal history decomposed into exact scalar Patterns."""
    components: tuple[AppliedNodalLoads, ...]
    node_dofs: dict
    sample_count: int
    name: str
    _removed: bool = field(default=False, repr=False)

    @property
    def pattern_tags(self):
        return tuple(c.pattern_tag for c in _parts(self))

    @property
    def time_series_tags(self):
        return tuple(c.time_series_tag for c in _parts(self))


def _parts(receipt):
    if isinstance(receipt,AppliedNodalHistory):
        for component in receipt.components:yield from _parts(component)
    else:
        yield receipt
        for companion in receipt.companions:yield from _parts(companion)


def _install(loads, tag_manager, ops, spec, name):
    if spec.kind == "Path" and spec.dt is None and spec.hold_last and spec.values[-1] != 0.:
        # OpenSees OPS_PathSeries does not forward useLast to the explicit
        # -time/-values PathTimeSeries constructor (also reproduced in 3.8.0).
        # Exact decomposition: f(t) = [f(t)-f_last] + step(t-start)*f_last.
        # The residual ends at zero; the uniform two-value Path holds its last
        # value indefinitely. No resampling, sentinel time or invented ramp.
        last=spec.values[-1]
        residual=_Series("Path",tuple(_finite(v-last,"residual factor") for v in spec.values),
            None,spec.absolute_times,spec.start,False)
        tail=_Series("Path",(last,last),spec.absolute_times[-1]-spec.absolute_times[0],(),spec.start,True)
        primary=_install(loads,tag_manager,ops,residual,name)
        try:
            primary.companions=(_install(loads,tag_manager,ops,tail,name+":held_tail"),)
        except Exception:
            remove_nodal_loads(primary,ops)
            raise
        return primary
    ts = tag_manager.get_next_tag(namespace="timeSeries")
    pat = tag_manager.get_next_tag(namespace="pattern")
    # OpenSees does not expose timeSeries tags. Never remove a tag whose
    # creation failed; foreign timeSeries must be registered in TagManager.
    if hasattr(ops,"getPatterns") and pat in ops.getPatterns():
        raise ValueError("load pattern tag collision; share/register the domain's TagManager")
    made_ts = made_pat = False
    try:
        ops.timeSeries(*spec.arguments(ts)); made_ts = True
        ops.pattern("Plain", pat, ts); made_pat = True
        for tag, vector in sorted(loads.items()):
            ops.load(tag, *vector)
    except Exception as exc:
        failures=[]
        for kind,tag,made in (("loadPattern",pat,made_pat),("timeSeries",ts,made_ts)):
            if made:
                try:ops.remove(kind,tag)
                except Exception as cleanup:failures.append(str(cleanup))
        if failures:
            raise RuntimeError("load installation failed and rollback failed: "+"; ".join(failures)) from exc
        raise
    return AppliedNodalLoads(ts,pat,loads,name,spec.kind)


def apply_nodal_loads(loads, tag_manager, ops_module=None, *, name="load",
                      time_series_type="Linear", path_values=None, dt=None,
                      times=None, start_time=None, hold_last=False,
                      allow_nonzero_initial=False):
    """Apply wind, rain, gravity or any already computed global nodal loads.

    Path values are dimensionless multipliers of reference N / N m. All
    nodes/DOFs in THIS call share a factor. Different wind/rain histories
    require separate calls, or use apply_nodal_load_history for vector data.
    ``times`` are offsets from start_time (default: current domain time).
    Neither zero-prepending nor automatic wind/rain alignment is performed.
    Nonuniform Path + hold_last may own TWO patterns for engine compatibility;
    use receipt.pattern_tags/current_nodal_loads instead of one raw factor.
    """
    if not isinstance(name,str) or not name.strip():raise ValueError("nonempty load name required")
    ops=_ops(ops_module)
    loads=validate_nodal_loads(loads)
    spec=_series(time_series_type,ops.getTime(),values=path_values,dt=dt,times=times,
        start_time=start_time,hold_last=hold_last,allow_nonzero_initial=allow_nonzero_initial)
    _check_domain(loads,ops)
    return _install(loads,tag_manager,ops,spec,name)


def apply_nodal_load_history(histories, tag_manager, ops_module=None, *, name="history",
                             dt=None, times=None, start_time=None, hold_last=False,
                             allow_nonzero_initial=False, max_patterns=10000):
    """Apply node -> [time][DOF] ACTUAL forces/moments, not load factors.

    Every component may vary independently, including vertical rain and
    changing direction. Identical normalized histories share one Pattern;
    no approximate low-rank fitting is used. All-zero histories create no
    Pattern and return an empty, queryable receipt. Invalid data are rejected
    before changing OpenSees; partial installations are rolled back together.

    For large nonproportional fields, max_patterns explicitly limits memory/
    engine-object count. Prefer spatial groups when the physics allows them.
    """
    if not isinstance(histories,Mapping) or not histories:raise ValueError("nonempty nodal histories required")
    if not isinstance(name,str) or not name.strip():raise ValueError("nonempty load name required")
    if isinstance(max_patterns,bool) or int(max_patterns)!=max_patterns or max_patterns<1:
        raise ValueError("max_patterns must be a positive integer")
    ops=_ops(ops_module);rows_by_node={};node_dofs={};count=None
    for key,history in histories.items():
        node=_node_tag(key)
        rows=tuple(tuple(_finite(v,f"node {node} history") for v in row) for row in history)
        if len(rows)<2 or not rows[0] or any(len(r)!=len(rows[0]) for r in rows):
            raise ValueError(f"node {node}: rectangular history with >=2 samples required")
        if count is not None and len(rows)!=count:raise ValueError("all histories must share the same time axis")
        if not allow_nonzero_initial and any(v!=0. for v in rows[0]):
            raise ValueError("histories must start from zero; explicit initial-state treatment required otherwise")
        count=len(rows);node_dofs[node]=len(rows[0]);rows_by_node[node]=rows
    current=ops.getTime()
    # Validate time axis even for a completely zero rainfall history.
    base=_series("Path",current,values=(0.,)*count,dt=dt,times=times,start_time=start_time,
                 hold_last=hold_last,allow_nonzero_initial=allow_nonzero_initial)
    _check_domain({n:(0.,)*ndf for n,ndf in node_dofs.items()},ops)
    groups={}
    for node,rows in sorted(rows_by_node.items()):
        for dof in range(node_dofs[node]):
            values=tuple(r[dof] for r in rows)
            peak=max(values,key=abs)
            if peak==0.:continue
            factors=tuple(v/peak for v in values)
            loads=groups.setdefault(factors,{})
            loads.setdefault(node,[0.]*node_dofs[node])[dof]=peak
    pattern_count=sum(2 if base.dt is None and base.hold_last and factors[-1]!=0 else 1 for factors in groups)
    if pattern_count>max_patterns:
        raise ValueError(f"{pattern_count} Patterns exceed max_patterns={max_patterns}")
    components=[]
    try:
        for factors,loads in groups.items():
            spec=_Series("Path",factors,base.dt,base.absolute_times,base.start,base.hold_last)
            component=_install({n:tuple(v) for n,v in loads.items()},tag_manager,ops,spec,name)
            components.append(component)
    except Exception as exc:
        failures=[]
        for component in reversed(components):
            try:remove_nodal_loads(component,ops)
            except Exception as cleanup:failures.append(str(cleanup))
        if failures:raise RuntimeError("history rollback failed: "+"; ".join(failures)) from exc
        raise
    return AppliedNodalHistory(tuple(components),node_dofs,count,name)


def current_nodal_loads(*receipts, ops_module=None):
    """Actual engine factors times reference vectors, INCLUDING loadConst.

    Call after analyze() has applied loads. setTime() alone does not refresh
    engine load factors. This ledger contains only the supplied receipts;
    include gravity separately for whole-domain equilibrium checks.
    """
    ops=_ops(ops_module);result={};seen=set()
    for receipt in receipts:
        if receipt._removed:continue
        if isinstance(receipt,AppliedNodalHistory):
            result=merge_nodal_loads(result,{n:(0.,)*ndf for n,ndf in receipt.node_dofs.items()})
        for item in _parts(receipt):
            if item._removed:continue
            if item.pattern_tag in seen:raise ValueError("same load pattern supplied twice in ledger")
            seen.add(item.pattern_tag)
            if hasattr(ops,"getPatterns") and item.pattern_tag not in ops.getPatterns():
                raise ValueError("receipt no longer belongs to the current domain")
            factor=_finite(ops.getLoadFactor(item.pattern_tag),"engine load factor")
            result=merge_nodal_loads(result,{n:tuple(factor*v for v in values) for n,values in item.applied_loads.items()})
    return result


def remove_nodal_loads(receipt, ops_module=None):
    """Remove only this call's patterns/series; repeated removal is harmless.

    Receipts are domain-specific. Do not reuse them after wipe/rebuild, where
    numeric tags may have been reassigned to unrelated objects.
    """
    if receipt._removed:return
    ops=_ops(ops_module)
    for item in reversed(tuple(_parts(receipt))):
        if item._removed:continue
        ops.remove("loadPattern",item.pattern_tag)
        ops.remove("timeSeries",item.time_series_tag)
        item._removed=True
    receipt._removed=True
