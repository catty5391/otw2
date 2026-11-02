"""Independent analytic checks for the rain loading baseline."""
import math
import json
import hashlib
from pathlib import Path
import unittest
import numpy as np
from scipy.special import gammainc
from rain_loading.physics import *


class RainPhysicsTests(unittest.TestCase):
    def test_mp_mass_matches_truncated_gamma_integral(self):
        r=50.;s=marshall_palmer(r,bins=2000)
        lam=4.1*r**(-.21)
        integral=6/lam**4*(gammainc(4,lam*5.8)-gammainc(4,lam*.2))
        exact=1000*np.pi/6*1e-9*8000*integral
        self.assertAlmostEqual(s.water_content_kg_m3/exact,1.,places=6)

    def test_rain_rate_units_and_explicit_closure(self):
        s=marshall_palmer(50,normalize_rain_rate=True)
        self.assertAlmostEqual(s.recovered_rain_mm_h,50.,places=10)
        self.assertGreater(abs(s.raw_recovered_rain_mm_h-50),1.)
        self.assertNotEqual(s.normalization_factor,1.)
        zero=marshall_palmer(0,normalize_rain_rate=True)
        self.assertEqual(zero.water_content_kg_m3,0.)

    def test_plane_flux_independent_analytic_result(self):
        s=marshall_palmer(50,normalize_rain_rate=True)
        for speed in (-30.,0.,30.):
            force=plane_normal_pressure(s,drop_velocity(s,[speed,0,0]),[1,0,0])
            self.assertAlmostEqual(force[0],s.water_content_kg_m3*speed*abs(speed),places=12)
        f=plane_normal_pressure(s,drop_velocity(s,[30,0,0],horizontal_ratio=1.2),[1,0,0])
        self.assertAlmostEqual(f[0]/(s.water_content_kg_m3*900),1.44)

    def test_no_wind_still_gives_vertical_rain_on_horizontal_conductor(self):
        s=marshall_palmer(50);v=drop_velocity(s,[0,0,0])
        q=cylinder_line_load(s,v,[0,1,0],.0276)
        self.assertEqual(q[0],0.);self.assertLess(q[2],0.)
        np.testing.assert_allclose(cylinder_line_load(s,v,[0,0,1],.0276),0.)

    def test_rigid_rotation_covariance_and_parallel_velocity(self):
        s=marshall_palmer(50);v=drop_velocity(s,[30,0,0]);axis=np.array([0,1,0])
        rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]])
        q=cylinder_line_load(s,v,axis,.0276)
        np.testing.assert_allclose(cylinder_line_load(s,v@rotation.T,rotation@axis,.0276),rotation@q,atol=1e-12)
        np.testing.assert_allclose(cylinder_line_load(s,v+100*axis,axis,.0276),q,atol=1e-12)

    def test_force_moment_and_subdivision_invariance(self):
        nodes={1:(1.,0.,2.),2:(4.,8.,9.),3:(2.5,4.,5.5)}
        whole=[dict(tag=1,node_i=1,node_j=2,breadth_m=.1)]
        split=[dict(tag=1,node_i=1,node_j=3,breadth_m=.1),dict(tag=2,node_i=3,node_j=2,breadth_m=.1)]
        q=lambda a,b:np.array([2.,3.,-4.])
        _,_,a=distribute_members(nodes,whole,q);_,_,b=distribute_members(nodes,split,q)
        np.testing.assert_allclose(a['force_N'],b['force_N'])
        np.testing.assert_allclose(a['moment_Nm'],b['moment_Nm'])
        self.assertLess(a['moment_mapping_error_Nm'],1e-10)

    def test_poisson_mean_and_variance_with_statistical_tolerance(self):
        s=marshall_palmer(50,normalize_rain_rate=True)
        _,_,a=poisson_plate_history(s,30,duration_s=200.,dt_s=.02)
        self.assertLess(abs(a['observed_mean_N']-a['expected_mean_N']),5*a['standard_error_mean_N'])
        self.assertLess(abs(a['observed_variance_N2']/a['expected_variance_N2']-1),.12)

    def test_kaimal_parseval_and_band_variance(self):
        _,u,f,s,a=kaimal_history(duration_s=200.,dt_s=.1)
        self.assertAlmostEqual(float(np.mean(u)),30.)
        self.assertAlmostEqual(a['realized_variance'],a['discrete_band_variance'],places=11)
        self.assertLess(a['realized_variance'],a['target_infinite_band_variance'])
        np.testing.assert_array_equal(u,kaimal_history(duration_s=200.,dt_s=.1)[1])

    def test_invalid_physical_inputs_rejected(self):
        for rain in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):marshall_palmer(rain)
        with self.assertRaises(ValueError):terminal_velocity([.1])
        with self.assertRaises(ValueError):marshall_palmer(50,bins=2.5)
        with self.assertRaises(ValueError):drop_velocity(marshall_palmer(50),[30,0,1])
        with self.assertRaises(ValueError):cylinder_line_load(marshall_palmer(50),np.zeros((240,3)),[0,0,0],.0276)


class RainPublishedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]
        cls.output=cls.root/'rain_loading/results'
        if not (cls.output/'verification.json').exists():raise unittest.SkipTest('No published rain evidence')
        cls.evidence=json.loads((cls.output/'verification.json').read_text())

    def test_all_three_tower_runs_are_actual_balanced_states(self):
        v=self.evidence
        self.assertFalse(v['physical_validation'])
        self.assertEqual({c['angle_deg'] for c in v['tower_cases']},{0,45,90})
        source_hash=hashlib.sha256((self.root/'Source/Z30103A6.s2k').read_bytes()).hexdigest()
        for c in v['tower_cases']:
            self.assertEqual(c['source_sha256'],source_hash)
            self.assertEqual(c['status'],'completed')
            self.assertEqual([x['stage'] for x in c['states']],['wind_only','wind_and_rain'])
            for state in c['states']:
                self.assertTrue(state['equilibrium_passed'])
                np.testing.assert_allclose(np.array(state['external_force_N'])+state['reactions_force_N'],0,atol=.1)
                np.testing.assert_allclose(np.array(state['external_moment_Nm'])+state['reactions_moment_Nm'],0,atol=1.)

    def test_publication_does_not_claim_physical_or_dynamic_validation(self):
        s=json.loads((self.output/'summary.json').read_text())
        self.assertEqual(s['status'],'numerical_verified')
        self.assertTrue(all(c['passed'] for c in s['verification']['checks']))
        self.assertIn('全塔仅静力',''.join(s['assumptions']))
        self.assertIn('未施加到四分段内部节点',''.join(s['assumptions']))
        for item in s['figures']+s['artifacts']:
            self.assertTrue((self.output/item['file']).is_file(),item['file'])


if __name__=='__main__':unittest.main()
