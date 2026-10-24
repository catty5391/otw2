import tempfile
from pathlib import Path
import unittest

import openseespy.opensees as ops

from initial_imperfection_material.diagnostic_probe import probe_tangent, selected_event


class DiagnosticProbeTests(unittest.TestCase):
    def tearDown(self):
        ops.wipe()

    def spring(self):
        ops.wipe()
        ops.model('basic','-ndm',1,'-ndf',1)
        for n in (1,2,3): ops.node(n,0.)
        ops.fix(1,1)
        ops.uniaxialMaterial('Elastic',1,100.)
        ops.element('zeroLength',1,1,2,'-mat',1,'-dir',1)
        ops.element('zeroLength',2,2,3,'-mat',1,'-dir',1)
        ops.timeSeries('Linear',1)
        ops.pattern('Plain',1,1)
        ops.load(3,1.)
        ops.constraints('Plain')
        ops.numberer('Plain')
        ops.system('BandGeneral')
        ops.test('NormDispIncr',1e-12,10)
        ops.algorithm('Newton')
        ops.integrator('LoadControl',1.)
        ops.analysis('Static')

    def test_actual_sparse_probe_preserves_next_solution(self):
        answers=[]
        for enabled in (False,True):
            self.spring()
            self.assertEqual(ops.analyze(1),0)
            if enabled:
                with tempfile.TemporaryDirectory() as td:
                    report=probe_tangent(ops,Path(td)/'probe',event_id='local_softening',modes=1)
                    self.assertEqual(report['status'],'completed',report)
                    self.assertTrue(report['physical_state_unchanged'])
                    self.assertAlmostEqual(report['eigenvalues'][0],38.1966011250105,places=9)
            self.assertEqual(ops.analyze(1),0)
            answers.append((ops.getTime(),ops.nodeDisp(2),ops.nodeDisp(3)))
        self.assertEqual(answers[0],answers[1])

    def test_unavailable_capability_is_explicit(self):
        class Missing:
            def getTime(self): return 0
            def getNodeTags(self): return []
            def getEleTags(self): return []
            def eigen(self,*args): raise NotImplementedError('PythonSparse unavailable')
        with tempfile.TemporaryDirectory() as td:
            report=probe_tangent(Missing(),Path(td)/'probe',event_id='test')
        self.assertEqual(report['status'],'capability_unavailable')
        self.assertTrue(report['physical_state_unchanged'])

    def test_event_selection_is_not_fixed_to_old_step_or_member(self):
        self.assertTrue(selected_event('target_other',[],stages=['target_other']))
        self.assertTrue(selected_event('unknown',[{'kind':'negative_tangent','member':123}],kinds=['negative_tangent']))
        self.assertFalse(selected_event('target_272',[],stages=['other']))


if __name__=='__main__': unittest.main()
