"""Read-only response evidence for monotonic tower pushover curves.

These are response markers, not calibrated damage-state definitions.  A stopped
curve remains a committed prefix; no peak, yield point or collapse is invented.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FLOOR_CONFIG = ROOT / 'pushover/.config/node_to_record_floor_disp.json'
COUNT_EVENTS = {
    'fiber_ever_yielded_members': 'first_fiber_nominal_yield_observed',
    'tmq_buckled_members': 'first_tmq_buckling_observed',
    'tmq_tension_yield_members': 'first_tmq_tension_yield_observed',
}


def _finite(value: Any, name: str) -> float:
    answer = float(value)
    if not math.isfinite(answer):
        raise ValueError(f'{name} must be finite')
    return answer


def _vector(values: Any, name: str) -> tuple[float, ...]:
    if isinstance(values, Mapping):
        values = [values[k] for k in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')]
    if len(values) != 6:
        raise ValueError(f'{name} must contain six global displacement/rotation components')
    return tuple(_finite(v, name) for v in values)


def section_groups(nodes: Mapping[int, Mapping[str, float]], *,
                   reference_nodes: Mapping[str, Sequence[int]] | None = None,
                   height_tolerance: float = 1e-6) -> dict[str, Any]:
    """Use the project's four-node panel references and actual highest section.

    Generic small models without those node IDs fall back to equal-height
    groups.  These groups are observers only; no rigid-diaphragm constraint is
    introduced.  A supplied reference_nodes mapping is checked strictly.
    """
    tolerance = _finite(height_tolerance, 'height_tolerance')
    if tolerance <= 0 or not nodes:
        raise ValueError('Positive height tolerance and nonempty node coordinates required')
    coordinates = {int(tag): tuple(_finite(row[k], f'node {tag} {k}') for k in 'xyz')
                   for tag, row in nodes.items()}
    if len(coordinates) != len(nodes):
        raise ValueError('Node IDs must remain unique after integer conversion')
    configured = json.loads(FLOOR_CONFIG.read_text(encoding='utf-8'))
    required = {int(n) for group in configured.values() for n in group}
    if reference_nodes is not None:
        groups = {str(key): list(map(int, values)) for key, values in reference_nodes.items()}
        method = 'explicit_reference_nodes'
    elif required <= coordinates.keys():
        groups = {key: list(values) for key, values in configured.items()}
        method = 'project_four_node_panel_references_plus_highest_section'
        highest = max(point[2] for point in coordinates.values())
        referenced_top = max(coordinates[n][2] for n in required)
        if highest - referenced_top > tolerance:
            groups['tower_top'] = sorted(n for n, p in coordinates.items() if abs(p[2]-highest) <= tolerance)
    else:
        groups = {}
        level, index = None, -1
        for tag, point in sorted(coordinates.items(), key=lambda item: (item[1][2], item[0])):
            if level is None or abs(point[2]-level) > tolerance:
                index += 1
                level = point[2]
                groups[f'height_{index:03d}'] = []
            groups[f'height_{index:03d}'].append(tag)
        method = 'equal_height_groups_fallback'
    records = []
    for name, tags in groups.items():
        if not tags or len(set(tags)) != len(tags) or not set(tags) <= coordinates.keys():
            raise ValueError(f'Invalid or missing section nodes for {name}')
        points = [coordinates[n] for n in tags]
        if max(p[2] for p in points)-min(p[2] for p in points) > tolerance:
            raise ValueError(f'Section {name} is not at a common elevation')
        center = tuple(fmean(p[d] for p in points) for d in range(3))
        records.append({'id': name, 'height_m': center[2], 'centroid_xyz_m': list(center),
                        'node_tags': sorted(tags), 'node_count': len(tags)})
    records.sort(key=lambda row: (row['height_m'], row['id']))
    if len(records) < 2 or any(b['height_m']-a['height_m'] <= tolerance for a, b in zip(records, records[1:])):
        raise ValueError('At least two distinct ordered section elevations required')
    return {'schema': 'otw2.tower_section_observers.v1', 'method': method, 'groups': records,
            'height_tolerance_m': tolerance,
            'limitations': [
                'Reference-node averages are response observers, not rigid cross sections.',
                'Cross-arm/local deformation and torsion are not represented by one section average.',
                'The final interval to the tower tip may span a different structural region.',
                'Rotation-corrected drift is a small-rotation diagnostic, not a damage criterion.']}


def drift_metrics(groups: Mapping[str, Any], current_disps: Mapping[int, Sequence[float]],
                  gravity_disps: Mapping[int, Sequence[float]], angle_deg: float) -> dict[str, Any]:
    """Average six DOFs after subtracting each node's gravity displacement.

    Corrected drift subtracts (theta_lower cross centroid_gap) dot wind / dh.
    For vertically aligned centroids this is raw - theta_y*cos(a) + theta_x*sin(a).
    The centroid-gap form also removes rigid yaw when section centers differ.
    """
    angle = math.radians(_finite(angle_deg, 'angle_deg'))
    wind = (math.cos(angle), math.sin(angle), 0.)
    records = groups['groups']
    if len(records) < 2:
        raise ValueError('At least two sections required')
    means = {}
    for group in records:
        values = []
        for tag in group['node_tags']:
            if tag not in current_disps or tag not in gravity_disps:
                raise ValueError(f'Missing current or gravity six-DOF response at node {tag}')
            current = _vector(current_disps[tag], f'current node {tag}')
            gravity = _vector(gravity_disps[tag], f'gravity node {tag}')
            values.append(tuple(a-b for a, b in zip(current, gravity)))
        means[group['id']] = tuple(fmean(v[d] for v in values) for d in range(6))
    rows = []
    for lower, upper in zip(records, records[1:]):
        height = upper['height_m']-lower['height_m']
        if height <= 0:
            raise ValueError('Section elevations must be strictly increasing')
        lo, hi = means[lower['id']], means[upper['id']]
        gap = tuple(b-a for a, b in zip(lower['centroid_xyz_m'], upper['centroid_xyz_m']))
        theta = lo[3:]
        rigid = (theta[1]*gap[2]-theta[2]*gap[1],
                 theta[2]*gap[0]-theta[0]*gap[2], theta[0]*gap[1]-theta[1]*gap[0])
        relative = sum((hi[d]-lo[d])*wind[d] for d in range(3))
        rotation = sum(rigid[d]*wind[d] for d in range(3))
        rows.append({'panel': f"{lower['id']}->{upper['id']}", 'lower_section': lower['id'],
                     'upper_section': upper['id'], 'lower_height_m': lower['height_m'],
                     'upper_height_m': upper['height_m'], 'height_m': height,
                     'relative_along_displacement_m': relative,
                     'rigid_rotation_along_displacement_m': rotation,
                     'raw_along_drift': relative/height,
                     'rotation_correction_along': rotation/height,
                     'corrected_along_drift': (relative-rotation)/height,
                     'lower_mean_incremental_rotation_rad': list(theta)})
    raw = max(rows, key=lambda row: abs(row['raw_along_drift']))
    corrected = max(rows, key=lambda row: abs(row['corrected_along_drift']))
    return {'max_abs_raw_along_drift': abs(raw['raw_along_drift']),
            'raw_control_panel': raw['panel'], 'raw_control_signed_drift': raw['raw_along_drift'],
            'max_abs_corrected_along_drift': abs(corrected['corrected_along_drift']),
            'corrected_control_panel': corrected['panel'],
            'corrected_control_signed_drift': corrected['corrected_along_drift'],
            'top_section_id': records[-1]['id'],
            'top_mean_along_displacement_m': sum(means[records[-1]['id']][d]*wind[d] for d in range(3)),
            'section_mean_incremental_six_dof': {key: list(value) for key, value in means.items()},
            'reference': 'each node current minus its own gravity-equilibrated state',
            'rotation_definition': 'raw - dot(theta_lower cross centroid_gap,wind)/height; small-rotation diagnostic',
            'rows': rows}


def _point(row: Mapping[str, Any], height: float) -> dict[str, Any]:
    step = row['step']
    if isinstance(step, bool) or not math.isfinite(float(step)) or int(step) != float(step):
        raise ValueError('step must be a finite integer')
    result = {'step': int(step)}
    for key in ('relative_control_displacement_m', 'along_wind_displacement_m', 'base_shear_along_N'):
        result[key] = _finite(row[key], key)
    result['control_drift_ratio'] = result['relative_control_displacement_m']/height
    for key in COUNT_EVENTS:
        value = row.get(key)
        if value in (None, ''):
            result[key] = None
        elif isinstance(value, bool) or not math.isfinite(float(value)) or int(value) != float(value) or float(value) < 0:
            raise ValueError(f'{key} must be a nonnegative integer or None')
        else:
            result[key] = int(value)
    return result


def _slope(points: Sequence[Mapping[str, float]], coordinate: str) -> float | None:
    if len(points) < 2:
        return None
    xs = [point[coordinate] for point in points]
    ys = [point['base_shear_along_N'] for point in points]
    xm, ym = fmean(xs), fmean(ys)
    denominator = sum((x-xm)**2 for x in xs)
    return sum((x-xm)*(y-ym) for x, y in zip(xs, ys))/denominator if denominator > 1e-24 else None


def curve_evidence(history: Sequence[Mapping[str, Any]], control_height: float) -> dict[str, Any]:
    """Describe only the contiguous valid committed prefix, without extrapolation.

    Non-applicable material-event counts must be None, not artificial zeros.
    First-positive observations at the first point are explicitly left-censored.
    The 80%-of-peak marker is an interpolated research candidate, never a grade.
    """
    height = _finite(control_height, 'control_height')
    if height <= 0:
        raise ValueError('Positive control height required')
    points = []
    for row in history:
        if row.get('committed', True) is not True or row.get('equilibrium_passed', True) is not True:
            break
        point = _point(row, height)
        if points and point['step'] <= points[-1]['step']:
            raise ValueError('History must preserve strictly increasing accepted step order')
        points.append(point)
    result = {'schema': 'otw2.tower_pushover_curve_evidence.v1', 'input_points': len(history),
              'valid_prefix_points': len(points), 'excluded_suffix_points': len(history)-len(points),
              'scope': 'contiguous valid committed prefix only; not proof of a completed loading protocol',
              'damage_grades_assigned': False, 'ultimate_capacity_established': False,
              'first_point': points[0] if points else None, 'last_point': points[-1] if points else None,
              'sampled_peak': None, 'peak_is_last': None, 'observed_descending_branch': False,
              'monotonic_control': None, 'control_push_sign': None, 'peak_index': None,
              'starts_at_zero_control_displacement': None,
              'maximum_observed_postpeak_drop_ratio': None, 'last_to_sampled_peak_force_ratio': None,
              'maximum_force_increment_in_push_direction_N': None,
              'postpeak_80pct_candidate': None, 'events': {}, 'secant_stiffness_history': [],
              'initial_stiffness_along_N_per_m': None, 'initial_stiffness_control_N_per_m': None,
              'initial_stiffness_definition': 'OLS through first up to six accepted points; only called initial when control displacement starts at zero'}
    for field, event in COUNT_EVENTS.items():
        observed = [point for point in points if point[field] is not None]
        first = next((i for i, point in enumerate(observed) if point[field] > 0), None)
        result['events'][event] = {'field': field, 'available': bool(observed), 'observed': first is not None,
                                  'previous': observed[first-1] if first is not None and first > 0 else None,
                                  'current': observed[first] if first is not None else None,
                                  'left_censored': first == 0 if first is not None else False,
                                  'interpretation': 'first saved positive count; crossing lies within the observation bracket, not a calibrated damage level'}
    if not points:
        return result
    first = points[0]
    increments = [b['relative_control_displacement_m']-a['relative_control_displacement_m'] for a, b in zip(points, points[1:])]
    direction = next((math.copysign(1., value) for value in increments if abs(value) > 1e-12), 1.)
    monotonic = all(direction*value >= -1e-12 for value in increments)
    result['monotonic_control'] = monotonic
    result['control_push_sign'] = direction
    starts_zero = abs(first['relative_control_displacement_m']) <= 1e-10
    result['starts_at_zero_control_displacement'] = starts_zero
    sample = points[:6]
    along = _slope(sample, 'along_wind_displacement_m')
    control = _slope(sample, 'relative_control_displacement_m')
    result.update(initial_prefix_fit_first_step=sample[0]['step'], initial_prefix_fit_last_step=sample[-1]['step'],
                  prefix_stiffness_along_N_per_m=along, prefix_stiffness_control_N_per_m=control)
    if starts_zero:
        result.update(initial_stiffness_along_N_per_m=along, initial_stiffness_control_N_per_m=control)
    for point in points:
        du = point['along_wind_displacement_m']-first['along_wind_displacement_m']
        dc = point['relative_control_displacement_m']-first['relative_control_displacement_m']
        dv = point['base_shear_along_N']-first['base_shear_along_N']
        k = dv/du if abs(du) > 1e-12 else None
        result['secant_stiffness_history'].append({'step': point['step'], 'along_N_per_m': k,
            'control_N_per_m': dv/dc if abs(dc) > 1e-12 else None,
            'along_to_initial_ratio': k/along if k is not None and along is not None and abs(along)>1e-12 and starts_zero else None})
    forces = [direction*(point['base_shear_along_N']-first['base_shear_along_N']) for point in points]
    peak_index = max(range(len(points)), key=lambda i: forces[i])
    peak_force = forces[peak_index]
    result.update(sampled_peak=points[peak_index], peak_index=peak_index,
                  peak_is_last=peak_index == len(points)-1,
                  maximum_force_increment_in_push_direction_N=peak_force,
                  peak_interpretation='maximum saved force within this prefix; an endpoint maximum is not an identified limit point')
    if not monotonic or peak_force <= 0:
        result['postpeak_note'] = 'Postpeak marker unavailable for a reversed protocol or nonpositive force increment'
        return result
    postpeak_min = min(forces[peak_index:])
    result['maximum_observed_postpeak_drop_ratio'] = (peak_force-postpeak_min)/peak_force
    result['last_to_sampled_peak_force_ratio'] = forces[-1]/peak_force
    # One accepted declining interval already is an observed loss; this is not
    # a claim that a smooth/physical limit point or collapse has been resolved.
    result['observed_descending_branch'] = len(points)-peak_index-1 >= 1 and postpeak_min < .99*peak_force
    threshold = .8*peak_force
    for index in range(peak_index+1, len(points)):
        a, b = forces[index-1], forces[index]
        if a > threshold >= b:
            fraction = (a-threshold)/(a-b)
            previous, current = points[index-1], points[index]
            interpolation = {key: previous[key]+fraction*(current[key]-previous[key]) for key in
                             ('relative_control_displacement_m', 'along_wind_displacement_m', 'control_drift_ratio', 'base_shear_along_N')}
            result['postpeak_80pct_candidate'] = {'previous': previous, 'current': current,
                'sample_fraction': fraction, 'interpolated': interpolation,
                'threshold_base_shear_along_N': first['base_shear_along_N']+direction*threshold,
                'interpretation': 'linear interpolation between adjacent accepted samples; not a separately solved state or assigned damage grade'}
            break
    return result
