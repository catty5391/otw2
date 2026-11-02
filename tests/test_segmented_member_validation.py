import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import openseespy.opensees as ops

from initial_imperfection_material.member_reference_3d import run_axial_boundary_case
from initial_imperfection_material.segmented_member_validation.mechanics import (
    compare_histories, protocol, read_members, run_case, weak_direction_global)
from model.mechanical_profile import local_axes
from model.steel02_parameters import Steel02Parameters


class SpatialSegmentedMemberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.members=read_members()

    def tearDown(self):
        ops.wipe()

    def test_material_and_fibers_are_production_tower_profile(self):
        member=self.members[349]
        self.assertEqual(len(member['fibers']),17)
        steel=member['steel_tower']
        expected=Steel02Parameters.legacy_tower(E0=steel['E0'],fy=steel['fy'],b=steel['b']).as_dict()
        self.assertEqual(steel,expected)
        self.assertAlmostEqual(sum(c['area'] for c in member['fibers']),member['section']['area'])
        self.assertEqual({m['section']['material_name'] for m in self.members.values()},{'Q235','Q345','Q420'})

    def test_weak_displacement_is_transverse_and_correct_equal_angle_direction(self):
        for m in self.members.values():
            axes=local_axes(m['coordinates']);direction=weak_direction_global(m)
            self.assertAlmostEqual(np.linalg.norm(direction),1.)
            self.assertAlmostEqual(float(axes[0]@direction),0.)
            np.testing.assert_allclose((axes@direction)[1:],np.ones(2)/np.sqrt(2),atol=1e-12)

    def test_three_dimensional_driver_matches_existing_builder_driver(self):
        member=self.members[349];direction=weak_direction_global(member)
        result=run_case(member,divisions=4,targets_strain=[0.,-.00002],steps=2)
        old=run_axial_boundary_case(member,[0.,-.00001*member['length'],-.00002*member['length']],
                                   divisions=4,imperfection_vector=.001*member['length']*direction)
        self.assertTrue(result['summary']['complete'])
        self.assertEqual(old['execution_status'],'completed')
        for row,state in zip(result['history'],old['states']):
            self.assertAlmostEqual(row['force_N'],state['end_global_internal_force'][6],delta=1e-4)

    def test_slender_member_elastic_history_recovers_and_checks_every_fiber(self):
        result=run_case(self.members[920],divisions=4,loading='elastic',steps=40)
        summary=result['summary']
        self.assertTrue(summary['complete']);self.assertTrue(summary['elastic_all_fibers_every_step'])
        self.assertTrue(all(row['fiber_observation']=='all' for row in result['history']))
        self.assertLess(summary['max_observed_fiber_stress_over_fy'],.2)
        self.assertLess(abs(summary['final_force_kN']),1e-7)
        self.assertLess(summary['max_reaction_balance_N'],1e-3)

    def test_protocol_order_and_common_prefix_are_preserved(self):
        member=self.members[349]
        points,_=protocol(member,'cyclic',steps=40)
        self.assertGreater(sum(1 for a,b in zip(points,points[1:]) if b['strain']>a['strain']),1)
        history=[dict(target_index=i,requested_point=True,strain=x,force_N=f)
                 for i,(x,f) in enumerate([(0.,0.),(-.1,-1.),(.1,2.),(-.1,-.5)])]
        matched=compare_histories(history,history,normalization=10.,requested_steps=3)
        self.assertTrue(matched['full_common_history']);self.assertEqual(matched['nrmse_Afy'],0.)
        partial=compare_histories(history,history[:3],normalization=10.,requested_steps=3)
        self.assertFalse(partial['full_common_history']);self.assertAlmostEqual(partial['coverage'],2/3)
        wrong=[dict(row) for row in history];wrong[2]['strain']=-.1
        with self.assertRaises(ValueError):compare_histories(history,wrong,normalization=10.,requested_steps=3)

    def test_solver_failure_keeps_last_committed_prefix(self):
        with patch('initial_imperfection_material.segmented_member_validation.mechanics.ops.analyze',return_value=-3):
            result=run_case(self.members[349],divisions=4,targets_strain=[0.,-.00001],steps=1)
        self.assertFalse(result['summary']['complete']);self.assertEqual(result['summary']['completed_steps'],0)
        self.assertEqual(result['summary']['failure']['kind'],'nonconvergence')
        self.assertEqual(len(result['history']),1)
        self.assertTrue(all(a['code']==-3 for a in result['attempts']))

    def test_budget_stop_is_not_collapse_and_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            result=run_case(self.members[349],output=folder,divisions=4,max_runtime_seconds=0.)
            self.assertFalse(result['summary']['complete'])
            self.assertEqual(result['summary']['failure']['kind'],'runtime_budget')
            with self.assertRaises(FileExistsError):run_case(self.members[349],output=folder,divisions=4)


if __name__=='__main__':unittest.main()
