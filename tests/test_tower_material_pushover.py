"""Numerical contracts and saved-output checks for whole-tower pushover."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tower_material_pushover.experiment import (
    control_dof, displacement_increment, inspect_fibers, OUTPUT)
from initial_imperfection_material.tower_material_pushover.publication import load_history, event_mm
from initial_imperfection_material.tower_material_pushover.evidence import curve_evidence
from util.analysis.stepping import AdaptiveStepper, Algorithm


class PushoverProtocolTests(unittest.TestCase):
    def test_angle_convention_and_target_sampling(self):
        self.assertEqual([control_dof(a) for a in (0,30,45,90)],[1,1,1,2])
        with self.assertRaises(ValueError):control_dof(60)
        x=0.;steps=[]
        while x<1.092-1e-9:
            d=displacement_increment(x,1.092-x);self.assertGreater(d,0);x+=d;steps.append(x)
        self.assertAlmostEqual(x,1.092)
        self.assertTrue(any(abs(v-.05)<1e-10 for v in steps))
        self.assertTrue(any(abs(v-.2)<1e-10 for v in steps))
        self.assertAlmostEqual(displacement_increment(.049,.1),.001)

    def test_first_failure_really_does_not_retry_or_accept_trial(self):
        class FailedOps:
            def __init__(self):self.calls=0
            def analyze(self,n):self.calls+=1;return -3
            def test(self,*args):pass
            def algorithm(self,*args):pass
            def testIter(self):return 40
        ops=FailedOps();events=[];configured=[]
        stepper=AdaptiveStepper(ops,progress=lambda:.2,configure_increment=configured.append,
            algorithms=(Algorithm('Newton'),),maximum_attempts_per_step=1,on_attempt=events.append)
        result=stepper.step(.005)
        self.assertFalse(result.converged);self.assertEqual(ops.calls,1)
        self.assertEqual(result.accepted_increment,0);self.assertEqual(stepper.accepted_steps,0)
        self.assertEqual(events[0]['state'],'failed_attempt');self.assertEqual(events[0]['return_code'],-3)

    def test_all_fibers_and_all_integration_points_are_inspected(self):
        class FiberOps:
            def __init__(self):self.calls=[]
            def eleResponse(self,ele,kind,ip,key):
                self.calls.append((ele,ip))
                stress=-250. if (ele,ip)==(4,6) else 50.
                return [0,0,1,stress,stress/1000,1,0,1,10,.01]
        ops=FiberOps();row=inspect_fibers(ops,{'segments':[1,2,3,4],'fy_Pa':200.,'E_Pa':1000.})
        self.assertEqual(len(ops.calls),24);self.assertEqual(row['critical_segment'],4)
        self.assertEqual(row['critical_integration_point'],6);self.assertEqual(row['fibers_at_or_above_fy'],1)
        self.assertEqual(row['fiber_stress_over_fy'],1.25)

    def test_csv_none_flags_preserved_and_invalid_suffix_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.csv'
            p.write_text('step,relative_control_displacement_m,along_wind_displacement_m,base_shear_along_N,fiber_ever_yielded_members,tmq_buckled_members,tmq_tension_yield_members,committed,equilibrium_passed\n0,0,0,0,0,,,True,True\n1,.01,.01,10,1,,,True,True\n2,.02,.02,11,2,,,True,False\n')
            rows=load_history(p);e=curve_evidence(rows,36.4)
            self.assertIsNone(rows[0]['tmq_buckled_members']);self.assertEqual(e['valid_prefix_points'],2)
            self.assertEqual(event_mm(e['events']['first_fiber_nominal_yield_observed']),'(0.0, 10.0] mm')
            self.assertEqual(event_mm(e['events']['first_tmq_buckling_observed']),'不适用')


class ActualPushoverEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT/'summary.json').exists():raise unittest.SkipTest('Publication not available yet')
        cls.summary=json.loads((OUTPUT/'summary.json').read_text())

    def test_twelve_cases_same_physical_inputs_per_angle(self):
        self.assertEqual(self.summary['cases_present'],12)
        for a,v in self.summary['common_input_checks'].items():
            with self.subTest(angle=a):
                self.assertTrue(v['all_three_present']);self.assertTrue(all(v['equal_inputs'].values()))
        self.assertFalse(self.summary['physical_validation']);self.assertFalse(self.summary['damage_state_thresholds_established'])

    def test_independent_global_force_and_deformed_moment_balance(self):
        v=json.loads((OUTPUT/'verification.json').read_text())
        self.assertTrue(v['all_global_equilibria_passed']);self.assertTrue(v['common_inputs_passed'])
        self.assertEqual(len(v['cases']),12)
        self.assertEqual(v['checked_points'],sum(c['valid_points'] for c in self.summary['cases']))

    def test_saved_curves_and_failure_boundaries_are_honest(self):
        for r in self.summary['cases']:
            with self.subTest(case=r['case']):
                folder=OUTPUT/'runs'/r['case'];s=json.loads((folder/'summary.json').read_text())
                h=load_history(folder/'history.csv');e=curve_evidence(h,s['control_height_m'])
                self.assertGreaterEqual(e['valid_prefix_points'],2)
                self.assertEqual(len(h),s['accepted_steps']+1)
                self.assertTrue(all(row['equilibrium_passed'] for row in h))
                self.assertTrue(all(b['relative_control_displacement_m']>a['relative_control_displacement_m'] for a,b in zip(h,h[1:])))
                self.assertAlmostEqual(e['sampled_peak']['base_shear_along_N']/1000,r['sampled_peak_kN'])
                attempts=[json.loads(v) for v in (folder/'attempts.jsonl').read_text().splitlines()]
                failed=[v for v in attempts if v['return_code']!=0]
                self.assertLessEqual(len(failed),1)
                if failed:
                    self.assertEqual(attempts[-1],failed[0])
                    self.assertEqual(s['stop_reason'],'first_newton_nonconvergence')
                    self.assertGreater(s['failed_target_displacement_m'],h[-1]['relative_control_displacement_m'])
                self.assertTrue(all(v['algorithm']=='Newton' for v in attempts))
                self.assertTrue(all(v['convergence_test']==['NormUnbalance',.005,40,0] for v in attempts))
                self.assertEqual(s['gravity_completed_steps'],10)
                self.assertFalse(e['ultimate_capacity_established'])
                self.assertFalse(e['damage_grades_assigned'])

    def test_all_member_histories_are_present_at_each_saved_state(self):
        for r in self.summary['cases']:
            with self.subTest(case=r['case']):
                folder=OUTPUT/'runs'/r['case'];counts={}
                with (folder/'member_envelopes.csv').open() as f:
                    for row in csv.DictReader(f):
                        counts[row['step']]=counts.get(row['step'],0)+1
                self.assertEqual(len(counts),r['accepted_steps']+1)
                self.assertTrue(all(v==1528 for v in counts.values()))
                with (folder/'critical_member_history.jsonl').open() as f:
                    first=json.loads(next(f));gravity=[json.loads(next(f)) for _ in range(10)]
                self.assertEqual(first['stage_id'],'initial')
                self.assertTrue(all(v['stage_id']=='gravity' for v in gravity))
                self.assertTrue(all(len(v)==6 for v in first['node_displacements'].values()))

if __name__=='__main__':unittest.main()
