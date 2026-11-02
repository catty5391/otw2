"""Physics/sign and incomplete-history tests; no OpenSees analysis required."""
import math
import unittest

from initial_imperfection_material.tower_material_pushover.evidence import (
    curve_evidence, drift_metrics, section_groups,
)


def nodes_and_states(rotation=(0., 0., 0.), shear=0., angle=0.):
    """Offset floor centers exercise all components of theta cross gap."""
    nodes = {}
    current, gravity = {}, {}
    direction = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    for level in range(3):
        for corner, (x, y) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
            tag = 10 * level + corner + 1
            x, y, z = x + .2 * level, y - .3 * level, 2. * level
            nodes[tag] = dict(x=x, y=y, z=z)
            rx, ry, rz = rotation
            rigid = (ry*z-rz*y, rz*x-rx*z, rx*y-ry*x)
            gravity[tag] = [tag*.00001, -.002, -.001, .0004, -.0003, .0002]
            incremental = [rigid[0] + shear*z*direction[0] + .001,
                           rigid[1] + shear*z*direction[1] - .002,
                           rigid[2] + .003, rx, ry, rz]
            current[tag] = [a+b for a, b in zip(gravity[tag], incremental)]
    return nodes, current, gravity


def point(step, u, force, **kwargs):
    result = dict(step=step, relative_control_displacement_m=u,
                  along_wind_displacement_m=u, base_shear_along_N=force,
                  fiber_ever_yielded_members=None, tmq_buckled_members=None,
                  tmq_tension_yield_members=None)
    result.update(kwargs)
    return result


class DriftEvidenceTests(unittest.TestCase):
    def test_rigid_body_rotation_is_removed_for_all_wind_directions(self):
        for angle in (0., 30., 45., 90., 135.):
            with self.subTest(angle=angle):
                nodes, current, gravity = nodes_and_states((.001, -.003, .002), angle=angle)
                groups = section_groups(nodes)
                result = drift_metrics(groups, current, gravity, angle)
                self.assertLess(result['max_abs_corrected_along_drift'], 1e-14)
                self.assertGreater(result['max_abs_raw_along_drift'], .0001)
                self.assertEqual(len(result['rows']), 2)

    def test_known_shear_is_recovered_despite_rigid_rotation_and_gravity(self):
        for angle in (0., 45., 90.):
            with self.subTest(angle=angle):
                nodes, current, gravity = nodes_and_states((.001, -.002, .003), .004, angle)
                result = drift_metrics(section_groups(nodes), current, gravity, angle)
                self.assertAlmostEqual(result['max_abs_corrected_along_drift'], .004)
                for row in result['rows']:
                    self.assertAlmostEqual(row['corrected_along_drift'], .004)

    def test_translation_and_nonuniform_gravity_do_not_create_drift(self):
        nodes, current, gravity = nodes_and_states()
        result = drift_metrics(section_groups(nodes), current, gravity, 45)
        self.assertLess(result['max_abs_raw_along_drift'], 1e-14)

    def test_groups_and_missing_rotation_are_checked(self):
        nodes, current, gravity = nodes_and_states()
        groups = section_groups(nodes, reference_nodes={'base': [1, 2, 3, 4], 'top': [21, 22, 23, 24]})
        self.assertEqual(groups['method'], 'explicit_reference_nodes')
        self.assertEqual(groups['groups'][1]['height_m'], 4.)
        current[1] = [0., 0., 0.]
        with self.assertRaises(ValueError):
            drift_metrics(groups, current, gravity, 0)
        with self.assertRaises(ValueError):
            section_groups(nodes, reference_nodes={'invalid': [1, 11], 'top': [21]})


class CurveEvidenceTests(unittest.TestCase):
    def test_elastic_prefix_stiffness_and_none_events(self):
        history = [point(i, i*.002, 500 + 120000*i*.002) for i in range(8)]
        result = curve_evidence(history, 36.4)
        self.assertAlmostEqual(result['initial_stiffness_along_N_per_m'], 120000.)
        self.assertAlmostEqual(result['secant_stiffness_history'][-1]['along_N_per_m'], 120000.)
        self.assertAlmostEqual(result['secant_stiffness_history'][-1]['along_to_initial_ratio'], 1.)
        self.assertTrue(result['peak_is_last'])
        self.assertFalse(result['observed_descending_branch'])
        self.assertFalse(result['ultimate_capacity_established'])
        for event in result['events'].values():
            self.assertFalse(event['available'])
            self.assertFalse(event['observed'])

    def test_first_material_event_uses_known_observation_bracket(self):
        history = [point(0, 0, 0, fiber_ever_yielded_members=0),
                   point(1, .1, 10),
                   point(2, .2, 20, fiber_ever_yielded_members=2),
                   point(3, .3, 21, fiber_ever_yielded_members=3)]
        event = curve_evidence(history, 10)['events']['first_fiber_nominal_yield_observed']
        self.assertEqual(event['previous']['step'], 0)
        self.assertEqual(event['current']['step'], 2)
        self.assertFalse(event['left_censored'])
        history[0]['tmq_buckled_members'] = 1
        event = curve_evidence(history, 10)['events']['first_tmq_buckling_observed']
        self.assertTrue(event['left_censored'])
        self.assertIsNone(event['previous'])

    def test_postpeak_interpolation_and_no_damage_grade(self):
        history = [point(i, .1*i, f) for i, f in enumerate((0, 10, 20, 18, 15))]
        result = curve_evidence(history, 10)
        self.assertEqual(result['sampled_peak']['step'], 2)
        self.assertFalse(result['peak_is_last'])
        self.assertTrue(result['observed_descending_branch'])
        marker = result['postpeak_80pct_candidate']
        self.assertEqual((marker['previous']['step'], marker['current']['step']), (3, 4))
        self.assertAlmostEqual(marker['sample_fraction'], 2/3)
        self.assertAlmostEqual(marker['interpolated']['base_shear_along_N'], 16.)
        self.assertAlmostEqual(marker['interpolated']['relative_control_displacement_m'], 11/30)
        self.assertFalse(result['damage_grades_assigned'])

    def test_first_postpeak_sample_is_observed_decline(self):
        result = curve_evidence([point(0, 0, 0), point(1, .1, 20), point(2, .2, 15)], 10)
        self.assertTrue(result['observed_descending_branch'])
        self.assertIsNotNone(result['postpeak_80pct_candidate'])

    def test_invalid_point_ends_prefix_without_using_later_values(self):
        history = [point(0, 0, 0), point(1, .1, 10),
                   point(2, .2, 100, equilibrium_passed=False), point(3, .3, 200)]
        result = curve_evidence(history, 10)
        self.assertEqual(result['valid_prefix_points'], 2)
        self.assertEqual(result['excluded_suffix_points'], 2)
        self.assertEqual(result['sampled_peak']['base_shear_along_N'], 10)
        self.assertTrue(result['peak_is_last'])
        self.assertIsNone(result['postpeak_80pct_candidate'])

    def test_negative_push_uses_signed_force_increment(self):
        result = curve_evidence([point(0, 0, 100), point(1, -.1, 80), point(2, -.2, 85)], 10)
        self.assertEqual(result['control_push_sign'], -1.)
        self.assertEqual(result['maximum_force_increment_in_push_direction_N'], 20.)
        self.assertAlmostEqual(result['postpeak_80pct_candidate']['interpolated']['base_shear_along_N'], 84.)

    def test_empty_one_point_and_nonzero_start_are_not_extrapolated(self):
        empty = curve_evidence([], 10)
        self.assertEqual(empty['valid_prefix_points'], 0)
        self.assertIsNone(empty['sampled_peak'])
        one = curve_evidence([point(0, 0, 0)], 10)
        self.assertIsNone(one['initial_stiffness_along_N_per_m'])
        offset = curve_evidence([point(1, .1, 10), point(2, .2, 20)], 10)
        self.assertIsNone(offset['initial_stiffness_along_N_per_m'])
        self.assertAlmostEqual(offset['prefix_stiffness_along_N_per_m'], 100.)

    def test_reversal_never_gets_monotonic_capacity_marker(self):
        result = curve_evidence([point(0, 0, 0), point(1, .2, 20), point(2, .1, 10)], 10)
        self.assertFalse(result['monotonic_control'])
        self.assertIsNone(result['postpeak_80pct_candidate'])

    def test_invalid_history_is_rejected(self):
        for history in ([point(0, 0, 0), point(0, .1, 10)],
                        [point(.5, 0, 0)], [point(True, 0, 0)],
                        [point(0, 0, float('nan'))],
                        [point(0, 0, 0, tmq_buckled_members=-1)]):
            with self.subTest(history=history), self.assertRaises(ValueError):
                curve_evidence(history, 10)


if __name__ == '__main__':
    unittest.main()
