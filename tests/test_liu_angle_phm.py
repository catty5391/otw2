"""Physical sign, analytical tangent, history and integration checks."""
import unittest
from dataclasses import replace

import numpy as np
from scipy.integrate import quad

from initial_imperfection_material.liu_angle_phm.material import (
    AnglePHMParameters,LiuAnglePHM,PHMDomainError,compression_response,reload_response)
from initial_imperfection_material.liu_angle_phm.experiment import simulate


def parameters():
    return AnglePHMParameters.from_regression(elastic_modulus=210e9,yield_stress=367.7e6,
        slenderness=100,hardening_ratio=.005,unloading_exponent=1.5,
        reload_stress_fraction=.8,reload_span_yield_strains=2.,reload_linear_ratio=.5,
        max_abs_strain=.03)


class CurvedPHMTests(unittest.TestCase):
    def test_compression_matches_integrated_softening_and_never_changes_sign(self):
        p=parameters();sc=p.first_buckling_stress;ec=sc/p.elastic_modulus
        for d in (.0001,.001,.01,.02):
            integral=quad(lambda x:(p.eta1+1.5*p.eta2*np.sqrt(x))*np.exp(-(p.eta1+p.eta2*np.sqrt(x))*x),0,d)[0]
            expected=sc+(p.sigma_a-sc)*integral
            stress,tangent=compression_response(p,ec-d,ec,sc)
            self.assertAlmostEqual(stress/abs(sc),expected/abs(sc),places=10)
            self.assertLess(sc,stress);self.assertLess(stress,p.sigma_a);self.assertLess(tangent,0.)

    def test_curved_tangents_match_independent_finite_differences(self):
        p=parameters();sc=p.first_buckling_stress;ec=sc/p.elastic_modulus
        for x in (ec-.0002,ec-.003,ec-.012):
            h=1e-8;a=compression_response(p,x+h,ec,sc)[0];b=compression_response(p,x-h,ec,sc)[0]
            self.assertAlmostEqual((a-b)/(2*h)/p.elastic_modulus,compression_response(p,x,ec,sc)[1]/p.elastic_modulus,places=7)
        for x in (-.002,-.0005,.001):
            f=lambda e:reload_response(e,-.004,.002,.8*p.yield_stress,p.xi1)
            numeric=(f(x+1e-9)[0]-f(x-1e-9)[0])/2e-9
            self.assertAlmostEqual(numeric/p.elastic_modulus,f(x)[1]/p.elastic_modulus,places=7)

    def test_reload_endpoints_and_integral_agree(self):
        p=parameters();eg=-.004;eh=.002;sh=.8*p.yield_stress;xi2=1/sh-p.xi1/(eh-eg)
        self.assertAlmostEqual(reload_response(eg,eg,eh,sh,p.xi1)[0],0.,places=5)
        self.assertEqual(reload_response(eh,eg,eh,sh,p.xi1)[0],sh)
        integral=quad(lambda e:p.xi1/(p.xi1+xi2*(eh-e))**2,-.001,eh)[0]
        self.assertAlmostEqual(reload_response(-.001,eg,eh,sh,p.xi1)[0]/sh,(sh-integral)/sh,places=11)

    def test_small_elastic_cycles_restore_origin_and_no_buckling(self):
        p=parameters();small=.2*abs(p.first_buckling_stress)/p.elastic_modulus
        rows,_=simulate(LiuAnglePHM(p),[0.,-small,small,-small/2,0.],10)
        self.assertLess(abs(rows[-1]["stress_Pa"]),1e-5)
        self.assertEqual(rows[-1]["buckling_count"],0)
        self.assertEqual(rows[-1]["plastic_max"],0.)
        self.assertLess(abs(rows[-1]["work_density"]),1e-7)

    def test_trial_rollback_and_copy_do_not_accumulate_history(self):
        p=parameters();m=LiuAnglePHM(p);m.set_trial_strain(-.003);m.commit_state();state=m.get_state()
        for e in (.001,.005,-.004,.007):m.set_trial_strain(e)
        m.revert_to_last_commit();self.assertEqual(m.get_state(),state)
        clone=m.get_copy();clone.set_trial_strain(.009);clone.commit_state()
        self.assertEqual(m.get_state(),state)
        self.assertGreater(clone.get_state()["plastic_max"],state["plastic_max"])

    def test_coarse_and_fine_steps_preserve_target_states(self):
        p=parameters();targets=[0.,.004,-.004,.006,-.006,.008,-.008,0.]
        a,_=simulate(LiuAnglePHM(p),targets,5);b,_=simulate(LiuAnglePHM(p),targets,50)
        a=[r for r in a if r['is_target']];b=[r for r in b if r['is_target']]
        for x,y in zip(a,b):
            self.assertAlmostEqual(x['stress_Pa']/p.yield_stress,y['stress_Pa']/p.yield_stress,places=10)
            self.assertEqual(x['buckling_count'],y['buckling_count'])
            self.assertAlmostEqual(x['plastic_max'],y['plastic_max'],places=12)

    def test_minor_reversal_retraces_then_returns_to_parent(self):
        p=parameters();m=LiuAnglePHM(p)
        for e in (-.004,-.002):m.set_trial_strain(e);m.commit_state()
        stress=m.get_stress()
        for e in (-.003,-.002):m.set_trial_strain(e);m.commit_state()
        self.assertAlmostEqual(m.get_stress()/p.yield_stress,stress/p.yield_stress,places=12)

    def test_domain_failure_preserves_last_trial(self):
        p=parameters();m=LiuAnglePHM(p);m.set_trial_strain(.001);state=m.get_state()
        with self.assertRaises(PHMDomainError):m.set_trial_strain(.031)
        self.assertEqual(m.get_state(),state)
        with self.assertRaises(ValueError):replace(p,eta2=-10000.)

    def test_degradation_uses_history_maximum_not_trial_count(self):
        p=parameters();self.assertEqual(p.degradation(0.),1.)
        self.assertLess(p.degradation(.01),p.degradation(.005))
        m=LiuAnglePHM(p);m.set_trial_strain(.008);m.commit_state()
        for _ in range(10):m.set_trial_strain(-.008)
        a=m.get_state();m.set_trial_strain(-.008);self.assertEqual(m.get_state(),a)
        peak=[x for x in a['events'] if x['event']=='buckling'][0]
        self.assertAlmostEqual(peak['stress']/p.first_buckling_stress,p.degradation(peak['plastic_max']),places=12)


if __name__=='__main__':unittest.main()
