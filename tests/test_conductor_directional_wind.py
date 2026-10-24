"""Analytical checks for conductor loads; no FE model or global domain needed."""

from __future__ import annotations

import copy
import json
import math
import unittest
from types import SimpleNamespace

from model.conductor_properties import resolve_conductor_mass
from util.processing.conductor_directional_wind import (
    ConductorAerodynamics,
    combine_conductor_loads,
    conductor_loads_from_model,
    equivalent_attachment_loads,
    explicit_conductor_loads,
    horizontal_wind_direction,
    wind_span_from_adjacent,
)


def rotate_z(vector, angle):
    cosine = math.cos(math.radians(angle))
    sine = math.sin(math.radians(angle))
    return (cosine * vector[0] - sine * vector[1], sine * vector[0] + cosine * vector[1], vector[2])


class ConductorDirectionalWindTests(unittest.TestCase):
    def setUp(self):
        self.aero = ConductorAerodynamics(
            diameter_m=0.0276, drag_coefficient=1.1, air_density=1.225,
        )
        self.coords = [(2.0, 0.0, 30.0), (2.0, 150.0, 30.0), (2.0, 300.0, 30.0)]
        self.reference_force = 0.5 * 1.225 * 30.0**2 * 1.1 * 0.0276 * 300.0

    def assertVectorClose(self, actual, expected, delta=1.0e-9):
        self.assertEqual(len(actual), len(expected))
        for got, wanted in zip(actual, expected):
            self.assertAlmostEqual(got, wanted, delta=delta)

    def explicit(self, angle=0.0, **overrides):
        settings = dict(
            line_id="span-a", node_tags=[1, 2, 3], coordinates=self.coords,
            wind_speed_m_s=30.0, wind_angle_deg=angle, aerodynamics=self.aero,
        )
        settings.update(overrides)
        return explicit_conductor_loads(**settings)

    def equivalent(self, angle=0.0, **overrides):
        settings = dict(
            span_id="span-a", node_tag=1, coordinate=self.coords[0],
            wind_span_m=300.0, wind_speed_m_s=30.0,
            wind_angle_deg=angle, aerodynamics=self.aero,
        )
        settings.update(overrides)
        return equivalent_attachment_loads(**settings)

    def test_cardinal_angle_convention_is_degrees_and_flow_towards(self):
        for angle, expected in [(0, (1, 0, 0)), (90, (0, 1, 0)),
                                (180, (-1, 0, 0)), (270, (0, -1, 0)),
                                (-90, (0, -1, 0)), (360, (1, 0, 0))]:
            with self.subTest(angle=angle):
                self.assertEqual(horizontal_wind_direction(angle), expected)

    def test_straight_line_angle_law_and_reversal_for_both_representations(self):
        for angle, ratio in [(0, 1), (30, 0.75), (45, 0.5), (90, 0), (180, -1), (225, -0.5)]:
            for factory in (self.explicit, self.equivalent):
                with self.subTest(angle=angle, representation=factory.__name__):
                    plan = factory(angle)
                    self.assertVectorClose(plan.total_force, (self.reference_force * ratio, 0, 0))

    def test_no_second_wind_direction_projection_on_equivalent_line_load(self):
        plan = self.equivalent(45)
        self.assertAlmostEqual(plan.total_force[0], self.reference_force * 0.5)
        self.assertEqual(plan.total_force[1], 0.0)
        self.assertNotAlmostEqual(plan.total_force[0], self.reference_force * 0.5 / math.sqrt(2))

    def test_nodal_six_components_and_equal_endpoint_distribution(self):
        plan = self.explicit()
        for tag, ratio in [(1, 0.25), (2, 0.5), (3, 0.25)]:
            self.assertVectorClose(plan.nodal_forces[tag], (self.reference_force * ratio, 0, 0, 0, 0, 0))

    def test_zero_speed_exactly_zero(self):
        for factory in (self.explicit, self.equivalent):
            plan = factory(wind_speed_m_s=0)
            self.assertEqual(plan.total_force, (0.0, 0.0, 0.0))
            self.assertEqual(plan.total_moment, (0.0, 0.0, 0.0))

    def test_speed_squared_diameter_linear_and_bundle_linear(self):
        double_speed = self.explicit(wind_speed_m_s=60)
        four_bundle = self.explicit(aerodynamics=ConductorAerodynamics(0.0276, 1.1, 1.225, 4))
        double_diameter = self.explicit(aerodynamics=ConductorAerodynamics(0.0552, 1.1, 1.225))
        self.assertAlmostEqual(double_speed.total_force[0], 4 * self.reference_force)
        self.assertAlmostEqual(four_bundle.total_force[0], 4 * self.reference_force)
        self.assertAlmostEqual(double_diameter.total_force[0], 2 * self.reference_force)

    def test_segment_speeds_allow_explicit_height_profile(self):
        plan = self.explicit(wind_speed_m_s=[30, 60])
        self.assertAlmostEqual(plan.total_force[0], self.reference_force * 2.5)
        self.assertAlmostEqual(plan.segments[1].force_n[0] / plan.segments[0].force_n[0], 4)

    def test_force_and_moment_agree_with_midpoint_resultants(self):
        plan = self.explicit(30)
        force = 0.75 * self.reference_force
        self.assertVectorClose(plan.total_moment, (0, 30 * force, -150 * force), delta=1e-8)
        audit = plan.audit()
        self.assertVectorClose(audit["force_residual_n"], (0, 0, 0))
        self.assertVectorClose(audit["moment_residual_nm"], (0, 0, 0))

    def test_fixed_sagged_geometry_uses_actual_lengths_and_normal_directions(self):
        sagged = [(2, 0, 30), (2, 150, 10), (2, 300, 30)]
        plan = self.explicit(90, coordinates=sagged)
        # Parallel to the chord is not parallel to the inclined segments.
        self.assertGreater(plan.total_force[1], 0)
        self.assertEqual(plan.total_force[0], 0)
        self.assertAlmostEqual(plan.total_force[2], 0)
        self.assertGreater(plan.segments[0].force_n[2], 0)
        self.assertLess(plan.segments[1].force_n[2], 0)
        self.assertGreater(plan.metadata["actual_conductor_length_m"], 300)
        for segment in plan.segments:
            self.assertAlmostEqual(sum(t * f for t, f in zip(segment.tangent, segment.force_n)), 0, delta=1e-10)
        self.assertVectorClose(plan.audit()["moment_residual_nm"], (0, 0, 0), delta=1e-8)
        self.assertFalse(plan.metadata["structural_relative_velocity_included"])
        self.assertFalse(plan.metadata["follower_force_update_included"])

    def test_horizontal_crosswind_on_sagged_line_uses_actual_not_chord_length(self):
        sagged = [(0, 0, 40), (0, 3, 36), (0, 6, 40)]
        plan = self.explicit(0, coordinates=sagged)
        self.assertEqual(plan.metadata["actual_conductor_length_m"], 10.0)
        self.assertAlmostEqual(plan.total_force[0], self.aero.force_factor * 30**2 * 10)

    def test_reversing_segment_order_does_not_reverse_drag(self):
        original = self.explicit(37, coordinates=[(2, 0, 30), (3, 150, 12), (2, 300, 30)])
        reverse = self.explicit(37, node_tags=[3, 2, 1], coordinates=[(2, 300, 30), (3, 150, 12), (2, 0, 30)])
        for tag in (1, 2, 3):
            self.assertVectorClose(original.nodal_forces[tag], reverse.nodal_forces[tag])

    def test_polyline_rotation_covariance_for_force_moment_and_nodal_loads(self):
        coords = [(2, 0, 30), (3, 150, 12), (2, 300, 35)]
        angle = 27.3
        original = self.explicit(18, coordinates=coords)
        rotated = self.explicit(18 + angle, coordinates=[rotate_z(p, angle) for p in coords])
        self.assertVectorClose(rotated.total_force, rotate_z(original.total_force, angle))
        self.assertVectorClose(rotated.total_moment, rotate_z(original.total_moment, angle), delta=1e-7)
        for tag in (1, 2, 3):
            self.assertVectorClose(rotated.nodal_forces[tag][:3], rotate_z(original.nodal_forces[tag][:3], angle))

    def test_equivalent_line_azimuth_rotation_covariance(self):
        original = self.equivalent(30)
        angle = 39.4
        rotated = self.equivalent(30 + angle, line_azimuth_deg=90 + angle,
                                  coordinate=rotate_z(self.coords[0], angle))
        self.assertVectorClose(rotated.total_force, rotate_z(original.total_force, angle))
        self.assertVectorClose(rotated.total_moment, rotate_z(original.total_moment, angle), delta=1e-8)

    def test_line_parallel_to_x_receives_y_not_x_normal_load(self):
        self.assertEqual(self.equivalent(0, line_azimuth_deg=0).total_force, (0, 0, 0))
        self.assertVectorClose(self.equivalent(90, line_azimuth_deg=0).total_force, (0, self.reference_force, 0))

    def test_translation_and_matching_reference_origin_leave_resultants_invariant(self):
        origin = (500, -200, 70)
        original = self.explicit(45)
        shifted = self.explicit(45, coordinates=[tuple(x + d for x, d in zip(p, origin)) for p in self.coords],
                                reference_origin=origin)
        self.assertVectorClose(shifted.total_force, original.total_force)
        self.assertVectorClose(shifted.total_moment, original.total_moment, delta=1e-8)

    def test_straight_line_subdivision_preserves_resultants(self):
        fine = self.explicit(45, node_tags=list(range(1, 102)),
                             coordinates=[(2, index * 3, 30) for index in range(101)])
        coarse = self.explicit(45, node_tags=[1, 3], coordinates=[self.coords[0], self.coords[2]])
        self.assertVectorClose(fine.total_force, coarse.total_force)
        self.assertVectorClose(fine.total_moment, coarse.total_moment, delta=1e-7)

    def test_wind_span_is_two_adjacent_half_spans(self):
        self.assertEqual(wind_span_from_adjacent(300, 400), 350)
        self.assertEqual(wind_span_from_adjacent(0, 300), 150)
        plan = self.equivalent(wind_span_m=wind_span_from_adjacent(0, 300))
        self.assertAlmostEqual(plan.total_force[0], self.reference_force / 2)
        for left, right in [(0, 0), (-1, 300), (300, float("nan"))]:
            with self.assertRaises(ValueError):
                wind_span_from_adjacent(left, right)

    def test_adapter_uses_catalog_outside_diameter_and_bundle_without_mutation(self):
        mass = resolve_conductor_mass({"conductor": {"model": "JL/G1A-400/50", "bundle_count": 4}})
        model = SimpleNamespace(
            transmission_line_map={"span-a": {"node_tags": [1, 2, 3], "conductor": mass.to_dict(),
                                              "material": {"area": 1, "initial_force": 30000}, "q_g": mass.weight_per_length}},
            node_map={tag: dict(zip(("x", "y", "z"), coord)) for tag, coord in zip([1, 2, 3], self.coords)},
            mass_map={1: {"mx": 12.3}},
        )
        before = copy.deepcopy(model.__dict__)
        plan = conductor_loads_from_model(model, "span-a", wind_speed_m_s=30, wind_angle_deg=0,
                                          drag_coefficient=1.1, air_density=1.225)
        self.assertAlmostEqual(plan.total_force[0], self.reference_force * 4)
        self.assertAlmostEqual(plan.metadata["aerodynamics"]["diameter_m"], 0.0276)
        self.assertEqual(model.__dict__, before)

    def test_adapter_missing_diameter_is_error_not_inferred_from_area_or_mass(self):
        model = SimpleNamespace(transmission_line_map={"a": {"node_tags": [1, 2], "conductor": {"mass_per_length": 1.5},
                                                               "material": {"area": 0.000451}}},
                                node_map={1: {"x": 0, "y": 0, "z": 30}, 2: {"x": 0, "y": 300, "z": 30}})
        kwargs = dict(wind_speed_m_s=30, wind_angle_deg=0, drag_coefficient=1.1, air_density=1.225)
        with self.assertRaisesRegex(ValueError, "diameter_m is missing"):
            conductor_loads_from_model(model, "a", **kwargs)
        override = conductor_loads_from_model(model, "a", diameter_m=0.0276, bundle_count=1, **kwargs)
        self.assertAlmostEqual(override.total_force[0], self.reference_force)
        self.assertEqual(override.metadata["model_adapter"]["diameter_source"], "explicit override")

    def test_same_span_cannot_receive_both_explicit_and_attachment_wind(self):
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            combine_conductor_loads(self.explicit(), self.equivalent())

    def test_duplicate_same_mode_also_rejected(self):
        for factory in (self.explicit, self.equivalent):
            with self.assertRaisesRegex(ValueError, "duplicate physical span"):
                combine_conductor_loads(factory(), factory())

    def test_equivalent_two_half_spans_protects_both_physical_ids(self):
        equivalent = self.equivalent(span_id="tower-attachment", source_span_ids=["left", "right"])
        for span in ("left", "right"):
            with self.assertRaisesRegex(ValueError, span):
                combine_conductor_loads(equivalent, self.explicit(line_id=span))

    def test_shared_endpoint_for_distinct_spans_accumulates_force(self):
        first = self.explicit()
        second = self.explicit(line_id="span-b", node_tags=[3, 4, 5],
                               coordinates=[self.coords[-1], (2, 450, 30), (2, 600, 30)],
                               reference_origin=(20, 30, 40))
        combined = combine_conductor_loads(first, second, reference_origin=(0, 300, 30))
        self.assertAlmostEqual(combined.total_force[0], 2 * self.reference_force)
        self.assertAlmostEqual(combined.nodal_forces[3][0], self.reference_force / 2)
        self.assertVectorClose(combined.total_moment, (0, 0, 0), delta=1e-8)
        self.assertVectorClose(combined.audit()["moment_residual_nm"], (0, 0, 0), delta=1e-8)

    def test_combining_different_wind_angles_or_conflicting_node_coordinates_fails(self):
        with self.assertRaisesRegex(ValueError, "same wind_angle_deg"):
            combine_conductor_loads(self.explicit(), self.equivalent(30, span_id="b"))
        with self.assertRaisesRegex(ValueError, "inconsistent coordinates"):
            combine_conductor_loads(self.explicit(), self.equivalent(span_id="b", coordinate=(3, 0, 30)))

    def test_plans_are_strict_json_serializable(self):
        for plan in [self.explicit(30), self.equivalent(45), combine_conductor_loads(self.explicit())]:
            encoded = json.dumps(plan.to_dict(), allow_nan=False)
            self.assertIn("wind_angle_deg", encoded)
            self.assertFalse(plan.metadata["mass_gravity_initial_tension_changed"])

    def test_aerodynamic_parameters_validate_units_and_finite_positive_values(self):
        for name, value in [("diameter_m", 27.6), ("diameter_m", 0), ("diameter_m", -1),
                            ("drag_coefficient", 0), ("drag_coefficient", float("nan")),
                            ("air_density", -1), ("air_density", float("inf")),
                            ("bundle_count", 1.5), ("bundle_count", 0), ("bundle_count", True)]:
            kwargs = dict(diameter_m=0.0276, drag_coefficient=1.1, air_density=1.225, bundle_count=1)
            kwargs[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                ConductorAerodynamics(**kwargs)

    def test_invalid_geometry_speed_and_angle_rejected(self):
        invalid = [
            dict(node_tags=[1], coordinates=[(0, 0, 0)]),
            dict(node_tags=[1, 2]),
            dict(node_tags=[1, 1, 2]),
            dict(node_tags=[1, 2, 0]),
            dict(node_tags=[1, 2, 3.5]),
            dict(coordinates=[(0, 0, 0), (0, 0, 0), (0, 1, 0)]),
            dict(coordinates=[(0, 0, 0), (0, 1, float("nan")), (0, 2, 0)]),
            dict(coordinates=[(0, 0, 0), (0, 1), (0, 2, 0)]),
            dict(wind_speed_m_s=-1), dict(wind_speed_m_s=[30]),
            dict(wind_speed_m_s=[30, float("inf")]),
            dict(wind_angle_deg=float("nan")), dict(line_id=""),
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.explicit(**overrides)

    def test_equivalent_rejects_zero_wind_span_and_invalid_source_ids(self):
        for overrides in [dict(wind_span_m=0), dict(wind_span_m=-1),
                          dict(source_span_ids=[]), dict(source_span_ids=["a", "a"]),
                          dict(source_span_ids=[""]), dict(line_azimuth_deg=float("inf"))]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.equivalent(**overrides)


if __name__ == "__main__":
    unittest.main()
