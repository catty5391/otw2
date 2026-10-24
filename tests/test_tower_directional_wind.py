from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from util.processing.tower_directional_wind import (
    PROXY_AREA_BASIS,
    PROVIDED_AREA_BASIS,
    TowerWindCoefficients,
    TowerWindGeometry,
    TowerWindMember,
    build_tower_wind_load,
    geometry_from_model,
)


class TowerDirectionalWindTests(unittest.TestCase):
    def geometry(self, *, shift=(0.0, 0.0, 0.0)):
        nodes = {1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 4.0)}
        nodes = {tag: tuple(x[k] + shift[k] for k in range(3)) for tag, x in nodes.items()}
        return TowerWindGeometry(nodes, (TowerWindMember(10, 1, 2, 2.0, 4.0),), shift,
                                 PROVIDED_AREA_BASIS, "analytic fixture member areas")

    def load(self, geometry=None, angle=0, **changes):
        options = dict(wind_angle_deg=angle, reference_pressure_pa=100.0,
                       height_edges_m=(0.0, 4.0), height_factors=(1.0,),
                       coefficients=TowerWindCoefficients(2.0, 3.0, 0.2, "analytic fixture"),
                       height_factor_provenance="analytic constant profile")
        options.update(changes)
        return build_tower_wind_load(geometry or self.geometry(), **options)

    def assert_vector_close(self, actual, expected, tolerance=1e-10):
        self.assertEqual(len(actual), len(expected))
        for value, target in zip(actual, expected):
            self.assertAlmostEqual(value, target, delta=tolerance)

    def test_analytic_angles_recompute_magnitude_and_direction(self):
        for angle, magnitude in ((0, 400), (30, 690), (45, 960), (90, 1200),
                                 (180, 400), (270, 1200), (-90, 1200), (390, 690)):
            with self.subTest(angle=angle):
                result = self.load(angle=angle)
                direction = math.cos(math.radians(angle)), math.sin(math.radians(angle)), 0
                self.assertAlmostEqual(result.summary["force_magnitude_N"], magnitude, places=9)
                self.assert_vector_close(result.summary["force_N"], tuple(magnitude * x for x in direction))
                self.assert_vector_close(result.summary["force_residual_N"], (0, 0, 0))
                self.assert_vector_close(result.summary["moment_residual_Nm"], (0, 0, 0))

    def test_no_pressure_normalization_and_exact_cardinal_components(self):
        x, y = self.load(angle=0), self.load(angle=90)
        self.assertEqual(x.summary["force_N"][1], 0)
        self.assertEqual(y.summary["force_N"][0], 0)
        doubled = self.load(reference_pressure_pa=200)
        self.assertEqual(doubled.summary["force_N"][0], 800)
        self.assertEqual(x.nodal_forces, x.applied_loads)
        self.assertEqual(x.applied_loads[1], (200, 0, 0, 0, 0, 0))

    def test_height_clipping_uses_linear_endpoint_weights_and_preserves_moment(self):
        result = self.load(height_edges_m=(0, 1, 4), height_factors=(1, 2))
        self.assertEqual(len(result.segments), 2)
        self.assertAlmostEqual(result.summary["force_N"][0], 700)
        self.assertAlmostEqual(result.applied_loads[1][0], 312.5)
        self.assertAlmostEqual(result.applied_loads[2][0], 387.5)
        self.assert_vector_close(result.summary["moment_Nm"], (0, 1550, 0))
        self.assert_vector_close(result.summary["moment_residual_Nm"], (0, 0, 0))
        self.assertAlmostEqual(sum(piece["area_x_m2"] for piece in result.segments), 2)
        self.assertAlmostEqual(sum(piece["area_y_m2"] for piece in result.segments), 4)

    def test_member_end_reversal_does_not_change_loads(self):
        geometry = self.geometry()
        reversed_geometry = TowerWindGeometry(geometry.nodes, (TowerWindMember(10, 2, 1, 2, 4),),
                                              geometry.origin, geometry.area_basis, geometry.area_provenance)
        options = dict(height_edges_m=(0, 1, 4), height_factors=(1, 2), angle=30)
        first, reverse = self.load(geometry, **options), self.load(reversed_geometry, **options)
        for tag in first.applied_loads:
            self.assert_vector_close(first.applied_loads[tag], reverse.applied_loads[tag])

    def test_translation_does_not_change_local_bands_forces_or_moments(self):
        first = self.load(angle=45, height_edges_m=(0, 1, 4), height_factors=(1, 2))
        shift = (500.0, -700.0, 29.0)
        shifted = self.load(self.geometry(shift=shift), angle=45,
                            height_edges_m=(0, 1, 4), height_factors=(1, 2))
        self.assertEqual(first.applied_loads, shifted.applied_loads)
        self.assert_vector_close(first.summary["moment_Nm"], shifted.summary["moment_Nm"])
        self.assert_vector_close(tuple(shifted.summary["force_centroid_global_m"][k]
                                       - first.summary["force_centroid_global_m"][k] for k in range(3)), shift)

    def test_crossarm_local_forces_are_not_smeared_over_a_floor(self):
        geometry = TowerWindGeometry(
            {1: (0, 0, 0), 2: (0, 0, 4), 3: (5, 0, 2), 4: (7, 0, 2)},
            (TowerWindMember(10, 1, 2, 2, 4, "body"), TowerWindMember(11, 3, 4, 0, 1, "arm")),
            (0, 0, 0), PROVIDED_AREA_BASIS, "analytic asymmetric crossarm fixture")
        coefficients = {"body": TowerWindCoefficients(1, 1, 0, "body fixture"),
                        "arm": TowerWindCoefficients(2, 2, 0, "arm fixture")}
        result = self.load(geometry, angle=90, coefficients=coefficients)
        self.assertEqual(result.applied_loads[3][1], 100)
        self.assertEqual(result.applied_loads[4][1], 100)
        self.assertEqual(result.applied_loads[1][1], 200)
        self.assert_vector_close(result.summary["force_N"], (0, 600, 0))
        self.assert_vector_close(result.summary["moment_Nm"], (-1200, 0, 1200))
        self.assert_vector_close(result.summary["moment_residual_Nm"], (0, 0, 0))
        self.assertEqual({p["region"] for p in result.panels}, {"body", "arm"})

    def test_symmetric_members_do_not_acquire_spurious_vertical_axis_torque(self):
        nodes = {1: (-1, -1, 0), 2: (-1, -1, 4), 3: (-1, 1, 0), 4: (-1, 1, 4),
                 5: (1, -1, 0), 6: (1, -1, 4), 7: (1, 1, 0), 8: (1, 1, 4)}
        members = tuple(TowerWindMember(k, 2 * k - 1, 2 * k, 1, 1) for k in range(1, 5))
        geometry = TowerWindGeometry(nodes, members, (0, 0, 0), PROVIDED_AREA_BASIS, "four symmetric legs")
        for angle in (0, 30, 45, 90, 180):
            self.assertAlmostEqual(self.load(geometry, angle=angle).summary["moment_Nm"][2], 0)

    def test_horizontal_boundary_members_have_single_deterministic_band(self):
        geometry = TowerWindGeometry({1: (0, 0, 1), 2: (1, 0, 1), 3: (0, 0, 4), 4: (1, 0, 4)},
                                     (TowerWindMember(10, 1, 2, 1, 1), TowerWindMember(11, 3, 4, 1, 1)),
                                     (0, 0, 0), PROVIDED_AREA_BASIS, "boundary fixture")
        result = self.load(geometry, height_edges_m=(0, 1, 4), height_factors=(1, 2))
        self.assertEqual([row["band_index"] for row in result.segments], [1, 1])
        self.assertEqual(result.summary["total_area_x_m2"], 2)

    def test_zero_pressure_has_zero_load_and_no_undefined_centroid(self):
        result = self.load(reference_pressure_pa=0)
        self.assertIsNone(result.summary["force_centroid_global_m"])
        self.assert_vector_close(result.summary["force_N"], (0, 0, 0))
        self.assert_vector_close(result.summary["moment_Nm"], (0, 0, 0))

    def test_invalid_or_implicit_parameters_are_rejected(self):
        cases = (
            {"wind_angle_deg": math.nan}, {"reference_pressure_pa": -1},
            {"height_edges_m": (0, 0, 4)}, {"height_edges_m": (0, 3)},
            {"height_factors": ()}, {"height_factors": (math.inf,)},
            {"height_factor_provenance": ""}, {"coefficients": {}},
        )
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.load(**options)
        for arguments in ((-1, 1, 0, "test"), (1, math.nan, 0, "test"), (1, 1, -1, "test"), (1, 1, 0, "")):
            with self.assertRaises(ValueError):
                TowerWindCoefficients(*arguments)

    def test_missing_nodes_duplicate_tags_and_zero_length_are_rejected(self):
        first = self.geometry()
        geometries = (
            TowerWindGeometry({1: (0, 0, 0)}, first.members, (0, 0, 0), PROVIDED_AREA_BASIS, "test"),
            TowerWindGeometry(first.nodes, first.members * 2, (0, 0, 0), PROVIDED_AREA_BASIS, "test"),
            TowerWindGeometry({1: (0, 0, 0), 2: (0, 0, 0)}, first.members, (0, 0, 0), PROVIDED_AREA_BASIS, "test"),
        )
        for geometry in geometries:
            with self.assertRaises(ValueError):
                self.load(geometry)

    def fake_model(self):
        return SimpleNamespace(
            origin=(0, 0, 0),
            _parse_node_coordinates=lambda: {1: {"x": 0, "y": 0, "z": 0}, 2: {"x": 3, "y": 4, "z": 12}},
            _parse_element_connectivity=lambda: {17: {"node_i": 1, "node_j": 2}},
            _element_section_assignments=lambda: {17: {"section_name": "L100x8Q345"}},
            _l_section_dimensions=lambda name: (0.1, 0.008),
            element_map={999: "subdivision must not be read"},
        )

    def test_model_adapter_requires_explicit_proxy_and_preserves_original_tags(self):
        geometry = geometry_from_model(self.fake_model(), area_basis=PROXY_AREA_BASIS,
                                       area_provenance="uncalibrated geometry fixture")
        self.assertEqual(len(geometry.members), 1)
        self.assertEqual(geometry.members[0].tag, 17)
        self.assertAlmostEqual(geometry.members[0].area_x_m2, 0.1 * math.sqrt(160))
        self.assertAlmostEqual(geometry.members[0].area_y_m2, 0.1 * math.sqrt(153))
        result = self.load(geometry, height_edges_m=(0, 12))
        self.assertTrue(result.summary["proxy_uncalibrated"])
        self.assertTrue(any("shielding" in text for text in result.summary["warnings"]))
        self.assertEqual(result.summary["engineering_validation"], "not_established_by_this_module")
        with self.assertRaises(ValueError):
            geometry_from_model(self.fake_model(), area_basis="automatic", area_provenance="test")

    def test_supplied_member_areas_cannot_be_incomplete_or_mixed_with_proxy(self):
        geometry = geometry_from_model(self.fake_model(), area_basis=PROVIDED_AREA_BASIS,
                                       area_provenance="external explicit fixture",
                                       member_projected_areas={17: (5, 7)}, member_regions={17: "arm"})
        self.assertEqual((geometry.members[0].area_x_m2, geometry.members[0].area_y_m2), (5, 7))
        self.assertEqual(geometry.members[0].region, "arm")
        for arguments in (
            dict(area_basis=PROVIDED_AREA_BASIS),
            dict(area_basis=PROVIDED_AREA_BASIS, member_projected_areas={18: (5, 7)}),
            dict(area_basis=PROXY_AREA_BASIS, member_projected_areas={17: (5, 7)}),
            dict(area_basis=PROXY_AREA_BASIS, member_regions={18: "arm"}),
        ):
            with self.assertRaises(ValueError):
                geometry_from_model(self.fake_model(), area_provenance="test", **arguments)

    def test_actual_s2k_adapter_has_1528_physical_rods_and_is_translation_invariant(self):
        from model.tower_model import OpenSeesModel
        source = Path(__file__).resolve().parents[1] / "Source" / "Z30103A6.s2k"
        with tempfile.TemporaryDirectory() as temporary:
            results = []
            for index, origin in enumerate(((0, 0, 0), (123, -321, 50))):
                model = OpenSeesModel(source, output_dir=Path(temporary) / str(index), origin=origin)
                geometry = geometry_from_model(model, area_basis=PROXY_AREA_BASIS,
                                               area_provenance="explicit uncalibrated geometry test")
                self.assertEqual(len(geometry.members), 1528)
                self.assertEqual(len(geometry.nodes), 621)
                result = self.load(geometry, angle=30, height_edges_m=(0, 3.2, 6.8, 9, 13.2,
                                  17.4, 21.6, 24, 27, 30, 33, 36.4, 39.6), height_factors=(1,) * 12)
                self.assert_vector_close(result.summary["force_residual_N"], (0, 0, 0), 1e-8)
                self.assert_vector_close(result.summary["moment_residual_Nm"], (0, 0, 0), 1e-7)
                results.append(result)
            self.assert_vector_close(results[0].summary["force_N"], results[1].summary["force_N"], 1e-8)
            self.assert_vector_close(results[0].summary["moment_Nm"], results[1].summary["moment_Nm"], 1e-7)
            for tag in results[0].applied_loads:
                self.assert_vector_close(results[0].applied_loads[tag], results[1].applied_loads[tag], 1e-8)


if __name__ == "__main__":
    unittest.main()
