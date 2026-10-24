import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import openseespy.opensees as ops

from util.processing.member_state_recorder import MemberStateRecorder, iter_member_states


class MemberStateRecorderTests(unittest.TestCase):
    def tearDown(self):
        ops.wipe()

    def beam(self):
        ops.wipe()
        ops.model('basic','-ndm',3,'-ndf',6)
        ops.node(1,0,0,0)
        ops.node(2,0,0,1)
        ops.fix(1,1,1,1,1,1,1)
        ops.uniaxialMaterial('Elastic',1,200e9)
        ops.section('Fiber',1,'-GJ',1e6)
        fibers=[]
        for y in (-.01,.01):
            for z in (-.01,.01):
                ops.fiber(y,z,.0025,1)
                fibers.append({'y':y,'z':z,'area':.0025})
        ops.geomTransf('Linear',1,0,1,0)
        ops.beamIntegration('Legendre',1,1,3)
        ops.element('dispBeamColumn',1,1,2,1,1)
        ops.timeSeries('Linear',1)
        ops.pattern('Plain',1,1)
        ops.load(2,0,0,-1000,0,0,0)
        ops.system('BandGeneral')
        ops.constraints('Plain')
        ops.numberer('RCM')
        ops.test('NormDispIncr',1e-12,20)
        ops.algorithm('Newton')
        ops.integrator('LoadControl',.5)
        ops.analysis('Static')
        return SimpleNamespace(ops=ops,element_map={1:{'node_i':1,'node_j':2,'original_element_tag':877,
            'segment_index':1,'num_intgr_pts':3,'section_tag':1}},section_fiber_map={1:fibers})

    def test_capture_is_read_only_and_has_real_fiber_response(self):
        model=self.beam()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'states.jsonl'
            with MemberStateRecorder(model,path,members=[877]) as recorder:
                recorder.capture(stage_id='initial',step=0,progress=0)
                self.assertEqual(ops.analyze(1),0)
                before=(ops.getTime(),ops.nodeDisp(2),ops.eleResponse(1,'localForce'))
                row=recorder.capture(stage_id='gravity',step=1,progress=.5,direction=1)
                after=(ops.getTime(),ops.nodeDisp(2),ops.eleResponse(1,'localForce'))
                self.assertEqual(before,after)
                section=row['members'][0]['segments'][0]['sections'][0]
                self.assertEqual(section['fiber_status'],'available')
                self.assertAlmostEqual(section['max_abs_stress']['stress'],-50000,places=4)
                self.assertEqual(len(row['node_displacements']['2']),6)
                self.assertAlmostEqual(row['members'][0]['chord_strain'],-2.5e-7,places=12)
                self.assertEqual(ops.analyze(1),0)
                recorder.capture(stage_id='gravity',step=2,progress=1,direction=1)
            self.assertEqual(len(list(iter_member_states(path))),3)
            with self.assertRaises(FileExistsError):
                MemberStateRecorder(model,path,members=[877])

    def test_rejects_trial_nonfinite_and_unknown_members(self):
        model=self.beam()
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                MemberStateRecorder(model,Path(td)/'missing.jsonl',members=[999])
            with MemberStateRecorder(model,Path(td)/'states.jsonl',members=[877]) as recorder:
                with self.assertRaises(ValueError):
                    recorder.capture(stage_id='x',step=1,progress=.1,committed=False)
                with self.assertRaises(ValueError):
                    recorder.capture(stage_id='x',step=1,progress=float('nan'))
            self.assertEqual((Path(td)/'states.jsonl').read_text(),'')

    def test_recording_does_not_change_next_solution(self):
        values=[]
        for enabled in (False,True):
            model=self.beam()
            with tempfile.TemporaryDirectory() as td:
                recorder=MemberStateRecorder(model,Path(td)/'states.jsonl',members=[877]) if enabled else None
                try:
                    for step in (1,2):
                        self.assertEqual(ops.analyze(1),0)
                        if recorder: recorder.capture(stage_id='load',step=step,progress=step/2)
                    values.append((ops.nodeDisp(2),ops.eleResponse(1,'localForce')))
                finally:
                    if recorder: recorder.close()
        self.assertEqual(values[0],values[1])

    def test_missing_history_requires_new_run(self):
        with self.assertRaisesRegex(FileNotFoundError,'new instrumented run'):
            list(iter_member_states('/tmp/otw2-no-such-boundary-record-20261022'))


class ReferenceSolverConfigIntegrationTests(unittest.TestCase):
    def test_tower_loop_uses_selected_step_recovery_policy(self):
        from initial_imperfection_material import full_tower_cyclic as tower
        from util.analysis import AdaptiveStepper
        counts={}
        for policy in ('legacy','last_success','gradual'):
            ops.wipe()
            ops.model('basic','-ndm',1,'-ndf',1)
            ops.node(1,0.)
            ops.node(2,0.)
            ops.fix(1,1)
            ops.uniaxialMaterial('Elastic',1,100.)
            ops.element('zeroLength',1,1,2,'-mat',1,'-dir',1)
            ops.timeSeries('Linear',1)
            ops.pattern('Plain',1,1)
            ops.load(2,1.)
            ops.constraints('Plain');ops.numberer('Plain');ops.system('BandGeneral')
            ops.test('NormDispIncr',1e-12,10);ops.algorithm('Newton')
            ops.integrator('DisplacementControl',2,1,.005);ops.analysis('Static')
            class LimitedIncrement:
                increment=.005
                def __getattr__(self,name): return getattr(ops,name)
                def analyze(self,*args):
                    return -1 if abs(self.increment)>.001250000001 else ops.analyze(*args)
                def configure(self,increment):
                    self.increment=increment
                    ops.integrator('DisplacementControl',2,1,increment)
            proxy=LimitedIncrement()
            stepper=AdaptiveStepper(proxy,progress=lambda:ops.nodeDisp(2,1),
                configure_increment=proxy.configure,minimum_increment=.000625,
                convergence_test=('NormDispIncr',1e-12,10),recovery_policy=policy)
            fake_recorder=SimpleNamespace(capture=lambda **kw:None)
            fake_run=SimpleNamespace(update=lambda **kw:None)
            history=[]
            with patch.object(tower,'ops',proxy):
                completed,failed=tower._run_cyclic_targets([.01],1.,0.,2,1,.005,
                    stepper,fake_recorder,history,[1],1,fake_run)
            self.assertEqual(completed,1)
            self.assertIsNone(failed)
            self.assertAlmostEqual(ops.nodeDisp(2,1),.01)
            self.assertAlmostEqual(history[-1].base_shear,1.)
            counts[policy]=stepper.diagnostics()['failed_attempts']
        self.assertLess(counts['last_success'],counts['legacy'])
        self.assertLess(counts['gradual'],counts['legacy'])
        ops.wipe()

    def test_strict_retry_keeps_tolerance_and_restores_on_error(self):
        from initial_imperfection_material import experiment
        from initial_imperfection_material.config import ReferenceSolverConfig
        fake=SimpleNamespace(analyze=unittest.mock.Mock(side_effect=[-1,RuntimeError('probe')]),
            test=unittest.mock.Mock(),algorithm=unittest.mock.Mock())
        with patch.object(experiment,'ops',fake):
            with self.assertRaisesRegex(RuntimeError,'probe'):
                experiment._analyze_one_step(ReferenceSolverConfig())
        self.assertTrue(all(c.args[1]==1e-8 for c in fake.test.call_args_list))
        self.assertEqual(fake.algorithm.call_args.args,('Newton',))

    def test_no_common_tower_target_is_not_index_error(self):
        from initial_imperfection_material.full_tower_cyclic import _write_comparison_tables
        empty=SimpleNamespace(history=[],completed_targets=0)
        with tempfile.TemporaryDirectory() as td:
            result=_write_comparison_tables(Path(td),empty,empty)
            self.assertEqual(result['common_target_count'],0)
            self.assertIsNone(result['comparison_end_stage'])
            self.assertEqual(len((Path(td)/'target_comparison.csv').read_text().splitlines()),1)

    def test_existing_tower_run_is_protected_before_opensees(self):
        from initial_imperfection_material.full_tower_cyclic import run_tower_cyclic
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'segmented_reference'
            folder.mkdir()
            (folder/'evidence.txt').write_text('keep')
            with self.assertRaises(FileExistsError):
                run_tower_cyclic('segmented_reference',output_root=Path(td))
            self.assertEqual((folder/'evidence.txt').read_text(),'keep')


if __name__=='__main__':
    unittest.main()
