"""Independent invariants for saved-state wind/static projection (no FE calls)."""
import unittest
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from initial_imperfection_material.tian_ma_qu.wind_projection import (
    map_loads, mass_normalize, project_static, output_error, validate_mapping,
    build_saved_loads, force_balance_check, MODULE,
)


class ProjectionAlgebraTests(unittest.TestCase):
    def test_singular_mass_static_moment_retains_massless_flexibility(self):
        # DOF2 is a massless rotation; its applied moment has a static term
        # which no finite-frequency eigenvector can independently represent.
        K=np.array([[2.,-1.],[-1.,1.]])
        M=csr_matrix(np.diag([1.,0.]))
        phi,error=mass_normalize(np.array([[3.],[3.]]),M)
        force=np.array([0.,1.])
        q,modal=project_static(phi,np.array([1.]),force,[0])
        direct=np.linalg.solve(K,force)
        np.testing.assert_allclose(q,[1.]);np.testing.assert_allclose(modal,[1.,1.])
        np.testing.assert_allclose(direct,[1.,2.]);np.testing.assert_allclose(direct-modal,[0.,1.])
        self.assertLess(error,1e-14)

    def test_free_equation_load_mapping_includes_moment_excludes_fixed_load(self):
        dofs=np.array([[0,-1,-1,-1,-1,1]])
        force,nodal,fixed=map_loads({10:(2.,3.,4.,0.,0.,5.)},np.array([10]),dofs,2)
        np.testing.assert_equal(force,[2.,5.]);np.testing.assert_equal(fixed,[[0.,3.,4.,0.,0.,0.]])

    def test_invalid_or_mp_mapping_fails_closed(self):
        with self.assertRaises(ValueError):validate_mapping([10],np.array([[0,0,-1,-1,-1,-1]]),2)
        with self.assertRaises(ValueError):validate_mapping([10],np.array([[0,2,-1,-1,-1,-1]]),2)
        with self.assertRaises(ValueError):validate_mapping([10],np.array([[0,-2,-1,-1,-1,-1]]),1)

    def test_missing_node_or_nonfinite_load_fails(self):
        dofs=np.array([[0,-1,-1,-1,-1,-1]])
        with self.assertRaises(ValueError):map_loads({20:(1,0,0,0,0,0)},[10],dofs,1)
        with self.assertRaises(ValueError):map_loads({10:(float('nan'),0,0,0,0,0)},[10],dofs,1)

    def test_modal_sign_and_column_order_do_not_change_static_reconstruction(self):
        M=csr_matrix(np.diag([2.,5.]))
        phi,_=mass_normalize(np.eye(2),M)
        eigen=np.array([3.,7.]);F=np.array([4.,9.])
        _,u=project_static(phi,eigen,F,[0,1])
        _,v=project_static(phi[:,::-1]*np.array([-1.,1.]),eigen[::-1],F,[0,1])
        np.testing.assert_allclose(u,v)
        np.testing.assert_allclose(u,np.linalg.solve(np.diag([6.,35.]),F))

    def test_incomplete_basis_exposes_missing_static_response(self):
        phi=np.eye(2);values=np.array([1.,4.]);force=np.array([2.,3.])
        _,u=project_static(phi,values,force,[0])
        np.testing.assert_equal(u,[2.,0.])
        self.assertFalse(output_error(.75,float(u[1]))['passed'])
        _,zero=project_static(phi,values,force,[]);np.testing.assert_equal(zero,[0.,0.])

    def test_zero_and_invalid_generalized_mass_rejected(self):
        with self.assertRaises(ValueError):mass_normalize(np.array([[0.],[1.]]),csr_matrix(np.diag([1.,0.])))
        with self.assertRaises(ValueError):project_static(np.eye(2),np.array([0.,1.]),np.ones(2),[0])
        with self.assertRaises(ValueError):project_static(np.eye(2),np.ones(2),np.ones(2),[0,0])

    def test_near_zero_absolute_error_cannot_be_hidden_by_relative_denominator(self):
        ok=output_error(1e-12,1e-7);bad=output_error(1e-12,2e-6)
        self.assertTrue(ok['passed']);self.assertIsNone(ok['relative_error'])
        self.assertFalse(bad['passed']);self.assertTrue(bad['near_zero_reference'])
        self.assertTrue(output_error(1.,1.019)['passed']);self.assertFalse(output_error(1.,1.021)['passed'])


class SavedLoadTests(unittest.TestCase):
    def test_cardinal_and_oblique_own_grid_force_and_moment_conservation(self):
        for key in ('bare_checked','coupled_20_checked','coupled_80_checked'):
            run=MODULE/'modal_results/runs'/key
            data=dict(np.load(run/'eigenvectors.npz'))
            for angle in (0,45,90):
                loads,audit=build_saved_loads(run,data,angle)
                self.assertTrue(all(a['passed'] for a in force_balance_check(audit)))
                self.assertEqual(len(audit['conductors']),0 if key=='bare_checked' else 4)
                self.assertTrue(set(loads['combined']) <= set(data['node_tags']))
                if angle==0:self.assertAlmostEqual(sum(v[1] for v in loads['tower'].values()),0.)
                if angle==90:self.assertAlmostEqual(sum(v[0] for v in loads['tower'].values()),0.)

    def test_mesh_has_own_cable_nodes_instead_of_reused_20_segment_tags(self):
        mappings=[]
        for key in ('coupled_20_checked','coupled_80_checked'):
            run=MODULE/'modal_results/runs'/key;data=dict(np.load(run/'eigenvectors.npz'))
            loads,_=build_saved_loads(run,data,45)
            mappings.append(loads['conductors'])
        self.assertGreater(len(mappings[1]),len(mappings[0]))
        self.assertGreater(len(set(mappings[1])-set(mappings[0])),100)


class SavedProjectionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=MODULE/'followup_results/B1_20261024/wind_projection'
        if not (cls.output/'summary.json').exists():
            raise unittest.SkipTest('run the offline N03 projection before saved evidence checks')
        cls.summary=json.loads((cls.output/'summary.json').read_text())

    def test_fixed_free_load_ledger_recovers_all_force_and_moment(self):
        ledger=json.loads((self.output/'load_ledger.json').read_text())
        for row in ledger:
            for field in ('force_N','moment_Nm'):
                np.testing.assert_allclose(np.array(row['free_load_resultant'][field])+row['fixed_load_resultant'][field],
                    row['total_gravity_coordinate_resultant'][field],atol=1e-6,rtol=1e-10)

    def test_saved_direct_response_superposition(self):
        with (self.output/'direct_static_observations.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        lookup={(r['case'],r['angle_deg'],r['point'],r['direction'],r['component']):float(r['linear_tangent_displacement_m']) for r in rows}
        for key,value in lookup.items():
            if key[-1]!='combined':continue
            tower=lookup[(*key[:-1],'tower')]
            cable=lookup.get((*key[:-1],'conductors'),0.)
            self.assertAlmostEqual(value,tower+cable,delta=max(1e-10,abs(value)*1e-8))

    def test_all_historical_load_crosschecks_and_source_fingerprints(self):
        self.assertEqual(self.summary['historical_same_grid_load_crosschecks'],6)
        self.assertTrue(self.summary['same_grid_load_crosschecks_passed'])
        root=Path(__file__).resolve().parents[1]
        for f in json.loads((self.output/'source_fingerprints.json').read_text()):
            self.assertEqual(hashlib.sha256((root/f['path']).read_bytes()).hexdigest(),f['sha256'],f['path'])

    def test_published_main_outputs_are_traceable_and_scope_remains_limited(self):
        self.assertEqual(self.summary['physical_validation'],'unvalidated')
        self.assertEqual(self.summary['new_FE_runs'],0);self.assertEqual(self.summary['eigen_solves'],0)
        self.assertIn('cable_tension',self.summary['unsupported_outputs'])
        with (self.output/'static_observations.csv').open() as stream:rows=list(csv.DictReader(stream))
        for r in self.summary['primary_outputs']:
            candidates=[x for x in rows if all(str(r[k])==x[k] for k in ('case','angle_deg','component','truncation','point','direction'))]
            self.assertEqual(len(candidates),1)
            self.assertAlmostEqual(float(candidates[0]['direct_m']),r['direct_m'])
            self.assertAlmostEqual(abs(r['direct_m']-r['modal_m']),r['absolute_error_m'])


if __name__=='__main__':unittest.main()
