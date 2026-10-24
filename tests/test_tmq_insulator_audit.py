import math
import unittest

from initial_imperfection_material.tian_ma_qu.insulator_audit import elastic_axial_force


class InsulatorForceReconstructionTests(unittest.TestCase):
    def test_extension_compression_and_rigid_translation(self):
        p, q, zero = (0., 0., 0.), (0., 0., 2.), (0., 0., 0.)
        self.assertAlmostEqual(elastic_axial_force(p, q, zero, (0., 0., .02), 1000), 10)
        self.assertAlmostEqual(elastic_axial_force(p, q, zero, (0., 0., -.02), 1000), -10)
        self.assertAlmostEqual(elastic_axial_force(p, q, (3., 4., 5.), (3., 4., 5.), 1000), 0)

    def test_large_rigid_rotation_does_not_create_axial_force(self):
        force = elastic_axial_force((0., 0., 0.), (2., 0., 0.), (0., 0., 0.), (-2., 2., 0.), 1e8)
        self.assertAlmostEqual(force, 0)

    def test_degenerate_geometry_and_nonfinite_data_are_rejected(self):
        zero = (0., 0., 0.)
        with self.assertRaises(ValueError): elastic_axial_force(zero, zero, zero, zero, 1)
        with self.assertRaises(ValueError): elastic_axial_force(zero, (1., 0., 0.), zero, zero, -1)
        with self.assertRaises(ValueError): elastic_axial_force(zero, (1., 0., 0.), zero, (math.nan, 0., 0.), 1)
