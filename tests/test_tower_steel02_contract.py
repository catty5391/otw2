"""Production/reference material parity and explicit imperfection controls."""
import csv
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import openseespy.opensees as ops

from model.mechanical_profile import Steel02Parameters as CompatibilityParameters
from model.steel02_parameters import Steel02Parameters
from model.tower_model_with_buckling import OpenSeesModelWithBuckling


ROOT = Path(__file__).resolve().parents[1]


class TowerSteel02ContractTests(unittest.TestCase):
    def tearDown(self):
        ops.wipe()

    def test_registered_material_and_csv_match_complete_reference_parameters(self):
        self.assertIs(CompatibilityParameters, Steel02Parameters)
        with tempfile.TemporaryDirectory() as folder:
            model = OpenSeesModelWithBuckling(ROOT / 'Source/Z30103A6.s2k', output_dir=folder)
            model.material()
            with (Path(folder) / 'materials.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue({'Q235', 'Q345', 'Q420'} <= {row['material_name'] for row in rows})
            reader = OpenSeesModelWithBuckling(ROOT / 'Source/Z30103A6.s2k', output_dir=folder)
            for row in rows:
                steel = Steel02Parameters.legacy_tower(E0=float(row['e0']), fy=float(row['fy']), b=float(row['b']))
                for key, value in steel.as_dict().items():
                    self.assertEqual(float(row['e0' if key == 'E0' else key]), value)
                    self.assertEqual(reader.get_material_record(material_name=row['material_name'])[
                        'e0' if key == 'E0' else key], value)
                ops.testUniaxialMaterial(int(row['mat_tag']))
                ops.setStrain(-1e-5)
                self.assertAlmostEqual(ops.getStress(), -1e-5 * steel.E0, delta=1e-3)

    def test_common_factory_preserves_previous_tower_cyclic_stress(self):
        strain = np.concatenate([np.linspace(a, b, 31)[1:] for a, b in
                                 zip([0, -.003, .002, -.006, .006], [-.003, .002, -.006, .006, 0])])
        outputs = []
        for arguments in [('Steel02', 1, 345e6, 210e9, .03, 20, .925, .15, .0005, .01, .0005, .01),
                          Steel02Parameters.legacy_tower(E0=210e9, fy=345e6).opensees_arguments(1)]:
            ops.wipe()
            ops.uniaxialMaterial(*arguments)
            ops.testUniaxialMaterial(1)
            stress = []
            for value in strain:
                ops.setStrain(float(value))
                stress.append(ops.getStress())
            outputs.append(stress)
        np.testing.assert_allclose(outputs[0], outputs[1], rtol=1e-13, atol=1e-5)

    def test_default_bow_and_repeatable_amplitude_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            source = ROOT / 'Source/Z30103A6.s2k'
            base = OpenSeesModelWithBuckling(source, output_dir=folder, imperfection_seed=30103)
            doubled = OpenSeesModelWithBuckling(source, output_dir=folder, imperfection_seed=30103,
                                              random_disp_ratio=.002)
            self.assertEqual(base.random_disp_ratio, .001)
            for endpoints in [(0, 0, 0, 1, 2, 3), (0, 0, 0, 0, 0, 4)]:
                a = np.array(base._add_rand_disp(0, 0, 0, *endpoints))
                b = np.array(doubled._add_rand_disp(0, 0, 0, *endpoints))
                np.testing.assert_allclose(b, 2*a, rtol=1e-14, atol=1e-16)
                chord = np.array(endpoints[3:]) - endpoints[:3]
                self.assertAlmostEqual(np.dot(a, chord), 0, delta=1e-14)
                self.assertAlmostEqual(np.linalg.norm(a), .001 * np.linalg.norm(chord))

    def test_invalid_mesh_and_bow_rejected_before_source_is_read(self):
        for options in ({'member_divisions': 3.5}, {'member_divisions': True},
                        {'member_divisions': math.inf}, {'member_divisions': 1},
                        {'random_disp_ratio': -.001}, {'random_disp_ratio': math.nan},
                        {'random_disp_ratio': math.inf}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                OpenSeesModelWithBuckling('not-a-source.s2k', **options)


if __name__ == '__main__':
    unittest.main()
