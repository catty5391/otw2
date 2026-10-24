"""Independent kinematics, event-memory, data coverage and report regressions."""
import csv
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.weakness_analysis import (
    envelope_panels,geometry,load_history,nodal_sections,panel_drift,
    section_definitions,section_kinematics,update_member,
)

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"initial_imperfection_material/tian_ma_qu"


class SectionKinematicsTests(unittest.TestCase):
    def setUp(self):
        self.xy=np.array([[-2,-2,0],[2,-2,0],[2,2,0],[-2,2,0]],dtype=float)

    def rotation(self,height,omega=(.003,-.002,0),translation=(.4,.6,-.1)):
        xyz=self.xy+np.array([0,0,height])
        disp=np.column_stack((np.cross(np.broadcast_to(omega,xyz.shape),xyz)+translation,np.broadcast_to(omega,xyz.shape)))
        return section_kinematics(xyz,disp)

    def test_small_rigid_rotation_is_removed_in_both_directions(self):
        drift=panel_drift(self.rotation(0),self.rotation(3),3)
        for key in ('isdr_x','isdr_y','geometric_isdr_x','geometric_isdr_y'):
            self.assertAlmostEqual(drift[key],0,places=13)
        self.assertAlmostEqual(drift['raw_y'],-.003)
        self.assertAlmostEqual(drift['raw_x'],-.002)

    def test_rigid_translation_has_zero_all_drifts(self):
        lower=self.rotation(0,omega=(0,0,0))
        upper=self.rotation(3,omega=(0,0,0))
        drift=panel_drift(lower,upper,3)
        self.assertTrue(all(abs(v)<1e-12 for v in drift.values()))

    def test_known_pure_shear_and_negative_direction(self):
        low=section_kinematics(self.xy,np.zeros((4,6)))
        for sign in (-1,1):
            values=np.zeros((4,6));values[:,1]=sign*.03
            high=section_kinematics(self.xy+[0,0,3],values)
            d=panel_drift(low,high,3)
            self.assertAlmostEqual(d['isdr_y'],sign*.01)
            self.assertAlmostEqual(d['geometric_isdr_y'],sign*.01)

    def test_rotation_estimators_may_differ_and_fit_residual_is_preserved(self):
        values=np.zeros((4,6));values[:,3]=.01
        values[:,2]=[.001,-.001,.001,-.001]
        state=section_kinematics(self.xy,values)
        self.assertAlmostEqual(state['rx'],.01)
        self.assertAlmostEqual(state['fit_rx'],0)
        self.assertAlmostEqual(state['fit_rms_m'],.001)

    def test_bad_shapes_nonfinite_values_and_collinear_nodes_fail(self):
        for coords,disp in ((self.xy,np.zeros((4,3))),(self.xy,np.full((4,6),math.nan)),
                            (np.zeros((4,3)),np.zeros((4,6)))):
            with self.assertRaises(ValueError):section_kinematics(coords,disp)
        with self.assertRaises(ValueError):panel_drift({}, {},0)

    def test_signed_and_absolute_envelopes_do_not_drop_negative_peak(self):
        rows=[]
        for i,v in enumerate((0,.01,-.02,.005)):
            rows.append(dict(step=i,panel=1,z_lower=0,z_upper=3,lower_fit_rms_m=0,upper_fit_rms_m=0,
                **{key:v for key in ('raw_x','raw_y','isdr_x','isdr_y','geometric_isdr_x','geometric_isdr_y')}))
        result=envelope_panels(rows)[0]
        self.assertEqual(result['isdr_y_abs_max'],.02)
        self.assertEqual(result['isdr_y_max'],.01)
        self.assertEqual(result['isdr_y_min'],-.02)
        self.assertEqual(result['isdr_y_peak_step'],2)


class MemberMemoryTests(unittest.TestCase):
    def setUp(self):
        self.member=dict(area_m2=.001,yield_stress_Pa=1e6,initial_buckling_force_N=100,initial_buckling_strain=.001)
        self.point=dict(step=10,stage='target_1',drift_ratio=-.003,base_shear_N=-500)
        self.previous=dict(step=9,stage='target_1',drift_ratio=-.0029,base_shear_N=-490)

    def row(self,strain,force,count,stage):
        return dict(strain=strain,force_N=force,stress_Pa=force/.001,buckling_count=count,stage=stage)

    def test_softened_member_with_force_ratio_below_one_is_not_missed(self):
        update_member(self.member,self.row(-.002,-80,1,'first_compression_softening_1'),self.point,self.previous)
        self.assertTrue(self.member['ever_buckled'])
        self.assertEqual(self.member['max_compression_force_ratio'],.8)
        self.assertEqual(self.member['max_compression_strain_demand'],2)
        self.assertEqual(self.member['first_observed']['previous_step'],9)
        update_member(self.member,self.row(.001,20,1,'tension_pinching'),{**self.point,'step':11},self.point)
        self.assertTrue(self.member['ever_buckled'])
        self.assertEqual(self.member['first_observed']['step'],10)
        self.assertEqual(self.member['max_compression_force_ratio'],.8)

    def test_near_threshold_is_not_promoted_to_buckled(self):
        update_member(self.member,self.row(-.00099992,-99.992,0,'elastic'),self.point,self.previous)
        self.assertFalse(self.member['ever_buckled'])
        self.assertNotIn('first_observed',self.member)

    def test_stress_force_inconsistency_nonfinite_and_history_loss_rejected(self):
        row=self.row(-.002,-80,1,'first_compression_softening_1')
        with self.assertRaises(ValueError):update_member(self.member,{**row,'stress_Pa':0},self.point,self.previous)
        with self.assertRaises(ValueError):update_member(self.member,{**row,'strain':math.nan},self.point,self.previous)
        update_member(self.member,row,self.point,self.previous)
        with self.assertRaises(ValueError):update_member(self.member,{**row,'buckling_count':0},self.point,self.previous)


@unittest.skipUnless((MODULE/'weakness_results/summary.json').exists(),'generated weakness results not installed')
class WeaknessEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=json.loads((MODULE/'weakness_results/summary.json').read_text())
        cls.run_dir=MODULE/'weakness_runs/bounded_with_nodes_01'

    def test_replay_identity_and_distinct_partial_extension(self):
        s=self.result
        self.assertTrue(s['replay_check']['passed'])
        self.assertEqual(s['run']['accepted_steps'],409)
        self.assertEqual(s['run']['status'],'complete')
        self.assertEqual(s['extended_run']['status'],'partial')
        self.assertEqual(s['extended_run']['accepted_steps'],264)
        self.assertFalse(s['validated_for_collapse'])

    def test_events_geometry_and_demand_ratios_match_independent_audit(self):
        with (MODULE/'weakness_results/bounded_members.csv').open() as f:
            members={int(r['element_tag']):r for r in csv.DictReader(f)}
        self.assertEqual(len(members),1528)
        for tag,step in ((825,104),(828,104),(917,159),(920,159)):
            m=members[tag]
            self.assertEqual(int(m['first_step']),step)
            self.assertEqual(float(m['z_min']),33)
            self.assertEqual(float(m['z_max']),33)
            self.assertEqual(m['section'],'L40x3Q235')
            self.assertLess(float(m['max_compression_force_ratio']),1)
        self.assertAlmostEqual(float(members[825]['max_compression_strain_demand']),4.418697,places=5)
        self.assertEqual(members[877]['ever_buckled'],'False')
        with (MODULE/'weakness_results/extended_members.csv').open() as f:
            extended={int(r['element_tag']):r for r in csv.DictReader(f)}
        self.assertAlmostEqual(float(extended[877]['max_compression_force_ratio']),.999920,places=5)
        self.assertEqual(extended[877]['ever_buckled'],'False')

    def test_all_nodes_steps_and_body_section_definitions(self):
        nodes,_=geometry(self.run_dir)
        with gzip.open(self.run_dir/'node_states.csv.gz','rt') as f:
            rows=csv.DictReader(f)
            counts={}
            for r in rows:counts[int(r['step'])]=counts.get(int(r['step']),0)+1
        self.assertEqual(set(counts),set(range(410)))
        self.assertTrue(all(count==621 for count in counts.values()))
        sections=section_definitions(nodes)
        self.assertEqual(len(sections),12)
        self.assertEqual(sections[-1]['height_m'],36.4)
        self.assertNotIn(801,{n for s in sections for n in s['node_tags']})
        self.assertEqual(sum(b['member_count'] for b in self.result['height_bins']),1528)
        self.assertEqual(sum(b['ever_buckled_count'] for b in self.result['height_bins']),4)

    def test_panel_coverage_baseline_and_source_definition(self):
        with (MODULE/'weakness_results/panel_history.csv').open() as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),410*11)
        first=[r for r in rows if int(r['step'])==0]
        self.assertTrue(all(float(r['isdr_x'])==0 and float(r['isdr_y'])==0 for r in first))
        self.assertEqual(len(self.result['amplitude_envelopes']),55)
        self.assertIn('Eq 2.2',self.result['literature']['formula'])
        self.assertTrue(all(float(r['fit_rms_max_m'])>=0 for r in self.result['panel_envelopes']))

    def test_missing_node_data_is_not_faked_from_force_history(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):nodal_sections(folder,{},[])


if __name__=='__main__':unittest.main()
