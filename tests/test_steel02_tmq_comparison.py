"""Mechanical invariants and failure/coverage accounting for the new experiment."""
import unittest
from unittest.mock import patch

import numpy as np

from initial_imperfection_material.material import MemberProperties
from initial_imperfection_material.steel02_tmq_comparison.experiment import (
    initial_coordinates, protocol, parameters, run_case, compare, members)


class SegmentedComparisonTests(unittest.TestCase):
    def test_mesh_refinement_keeps_same_initial_shape_and_peak(self):
        coarse=initial_coordinates(3.,4,.001)
        fine=initial_coordinates(3.,16,.001)
        np.testing.assert_allclose(coarse,fine[::4],atol=1e-15)
        self.assertAlmostEqual(coarse[2,0],.003)
        self.assertEqual(coarse[0,0],0.);self.assertEqual(coarse[-1,0],0.)
        self.assertGreater(coarse[1,0],0.)
        self.assertEqual(initial_coordinates(3.,4,.001,'legacy_midpoint_only')[1,0],0.)
        with self.assertRaises(ValueError):initial_coordinates(3.,8,.001,'legacy_midpoint_only')

    def test_source_member_matches_original_tower(self):
        cases,source=members()
        self.assertEqual(source['selected_original_frame'],349)
        self.assertEqual(source['count'],112)
        self.assertAlmostEqual(cases['tower_median'].length,1.6023792916784707)
        self.assertEqual(cases['long_demo'].elastic_modulus,cases['tower_median'].elastic_modulus)

    def test_tmq_mapping_keeps_steel_and_changes_member_capacity(self):
        short=MemberProperties.z30103a6_l125x8(length=1.6)
        long=MemberProperties.z30103a6_l125x8(length=3.)
        a,b=parameters(short),parameters(long)
        self.assertEqual(a.elastic_modulus,short.elastic_modulus)
        self.assertEqual(a.rho,short.steel_hardening_ratio)
        self.assertLess(b.phi,a.phi)
        self.assertEqual(a.alpha,b.alpha)

    def test_elastic_bowed_member_recovers_without_artificial_residual(self):
        m=MemberProperties.z30103a6_l125x8(length=3.)
        points,_=protocol(m,'elastic');rows,attempts,s=run_case(m,points,scheme='segmented',divisions=4)
        self.assertTrue(s['complete']);self.assertLess(s['max_fiber_stress_over_fy'],.5)
        self.assertLess(abs(rows[-1]['force_N']),1e-3)
        self.assertLess(s['max_reaction_balance_N'],1e-3)
        self.assertLess(min(r['force_N'] for r in rows),-100e3)

    def test_bowing_creates_member_softening_missing_from_straight_steel02(self):
        m=MemberProperties.z30103a6_l125x8(length=3.)
        points=[dict(target_index=i,leg=1,strain=float(e),target=i==120)
                for i,e in enumerate(np.linspace(0.,-.008,121))]
        bowed,_,b=run_case(m,points,scheme='segmented',divisions=4)
        straight,_,s=run_case(m,points,scheme='straight_steel02')
        self.assertTrue(b['complete'] and s['complete'])
        self.assertGreater(b['max_fiber_stress_over_fy'],1.)
        self.assertLess(abs(bowed[-1]['force_N']),.7*max(abs(r['force_N']) for r in bowed))
        self.assertGreater(abs(straight[-1]['force_N']),.95*m.area*m.yield_strength)

    def test_nonconvergence_cannot_be_published_as_completed_history(self):
        m=MemberProperties.z30103a6_l125x8()
        points=[dict(target_index=0,leg=0,strain=0.,target=True),
                dict(target_index=1,leg=1,strain=-.0001,target=True)]
        with patch('initial_imperfection_material.steel02_tmq_comparison.experiment.ops.analyze',return_value=-3):
            rows,attempts,s=run_case(m,points,scheme='segmented',divisions=4)
        self.assertFalse(s['complete']);self.assertEqual(s['completed_steps'],0)
        self.assertEqual(s['failure']['kind'],'nonconvergence');self.assertEqual(len(rows),1)
        self.assertEqual(s['failed_attempts'],len(attempts));self.assertGreater(len(attempts),1)

    def test_comparison_uses_history_index_and_discloses_common_prefix(self):
        rows=[dict(target_index=i,requested_point=True,displacement_m=x,
                   force_N=f,external_work_J=0.) for i,(x,f) in enumerate([(0.,0.),(-.1,-1.),(.1,2.),(-.1,-.5)])]
        result=compare(rows,rows,10.,requested_steps=3)
        self.assertTrue(result['full_common_history']);self.assertEqual(result['nrmse'],0.)
        prefix=compare(rows[:3],rows[:3],10.,requested_steps=3)
        self.assertFalse(prefix['full_common_history']);self.assertAlmostEqual(prefix['coverage'],2/3)
        wrong=[dict(r) for r in rows];wrong[2]['displacement_m']=-.1
        with self.assertRaises(ValueError):compare(rows,wrong,10.,requested_steps=3)


if __name__=='__main__':unittest.main()
