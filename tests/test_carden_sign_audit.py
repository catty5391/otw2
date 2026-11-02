"""Independent sign/coordinate and ordered-crossing checks for Carden evidence."""
import csv
import json
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.carden_ordered_experiment import manifest_from_vector
from initial_imperfection_material.tian_ma_qu.carden_sign_audit import (
    RAW, PREVIOUS, X_SCALE, F_SCALE, first_upcrossing, pdf_point_to_screen,
)
from initial_imperfection_material.tian_ma_qu.parameter_identification import ordered_data, response
from initial_imperfection_material.tian_ma_qu.material import TMQParameters


class CardenSignAuditTests(unittest.TestCase):
    def test_pdf_y_and_screen_y_have_opposite_sign_without_changing_force(self):
        origin=pdf_point_to_screen((0,0),(304.08,579.521),792)
        compression=pdf_point_to_screen((-1,-2),(304.08,579.521),792)
        tension=pdf_point_to_screen((1,2),(304.08,579.521),792)
        self.assertLess(compression[0],origin[0]);self.assertGreater(compression[1],origin[1])
        self.assertGreater(tension[0],origin[0]);self.assertLess(tension[1],origin[1])

    def test_first_crossing_keeps_history_order_and_does_not_extrapolate(self):
        self.assertEqual(first_upcrossing([0,4,1,5],[-1,3,1,4],2),3.)
        self.assertIsNone(first_upcrossing([0,1,2],[-1,0,1],2))

    def test_actual_cached_vector_signs_units_and_csv_order_agree(self):
        for key,direction in [('P',-1),('Q',1)]:
            with self.subTest(key=key):
                raw=json.loads((RAW/f'carden_{key}_vector.json').read_text())
                xy=np.array([r[:2] for r in raw['vertices']])
                rows=list(csv.DictReader((PREVIOUS/f'{key}_refined_predictions.csv').open()))
                np.testing.assert_allclose(xy[:,0]*X_SCALE*.001,[float(r['displacement_m']) for r in rows],atol=1e-15,rtol=0)
                np.testing.assert_allclose(xy[:,1]*F_SCALE,[float(r['observed_force_N']) for r in rows],atol=1e-9,rtol=0)
                self.assertEqual(np.sign(next(x for x in xy[:,0] if x!=0)),direction)
                self.assertTrue(all(int(r['sequence'])==i for i,r in enumerate(rows)))

    def test_p_and_q_origin_metadata_are_distinct_without_modifying_samples(self):
        for key,offset in [('P',.24),('Q',-.96)]:
            with self.subTest(key=key):
                raw=json.loads((RAW/f'carden_{key}_vector.json').read_text())
                generated=manifest_from_vector(raw)
                saved=json.loads((PREVIOUS/f'{key}.json').read_text())
                self.assertEqual(generated['samples'],saved['samples'])
                meta=generated['origin_uncertainty']
                self.assertEqual(meta['force_origin_offset_pdf_points'],offset)
                self.assertAlmostEqual(meta['force_origin_vs_grid_N'],offset*F_SCALE)
                self.assertEqual(meta['force_origin_exceeds_one_stroke_width'],key=='Q')

    def test_saved_candidate_replays_without_force_or_displacement_sign_reversal(self):
        params=TMQParameters(**json.loads((PREVIOUS/'summary.json').read_text())['diagnostic_parameters'])
        for key in ['P','Q']:
            with self.subTest(key=key):
                d=ordered_data(json.loads((PREVIOUS/f'{key}.json').read_text()))
                rows=list(csv.DictReader((PREVIOUS/f'{key}_refined_predictions.csv').open()))
                np.testing.assert_allclose(response(params,d['strain'])*d['area_m2'],
                    [float(r['candidate_force_N']) for r in rows],atol=1e-6,rtol=0)


if __name__=='__main__':unittest.main()
