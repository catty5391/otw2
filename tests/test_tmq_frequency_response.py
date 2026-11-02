import tempfile
import hashlib
import json
import csv
from pathlib import Path
import unittest
import numpy as np
from scipy.sparse import csc_matrix, diags
from initial_imperfection_material.tian_ma_qu.frequency_response import (
    direct_response,modal_response,response_metrics,check_mass,frequency_grid,run,
    output_projection,projected_grid_checks,refinement_metrics)
from initial_imperfection_material.tian_ma_qu.wind_projection import mass_normalize

class FrequencyResponseTests(unittest.TestCase):
    def test_scalar_analytic_amplitude_and_phase(self):
        K=diags([9.]);M=diags([2.]);F=np.array([[3.]])
        f=.4;alpha=.02;beta=.003;w=2*np.pi*f
        u,res=direct_response(K,M,F,f,alpha,beta)
        expected=3/(9-2*w*w+1j*w*(2*alpha+9*beta))
        self.assertAlmostEqual(u[0,0].real,expected.real,13)
        self.assertAlmostEqual(u[0,0].imag,expected.imag,13)
        self.assertLess(res,1e-12)

    def test_complete_modes_match_independent_coupled_matrix(self):
        M=diags([2.,3.]);K=csc_matrix([[10.,-2.],[-2.,6.]])
        from scipy.linalg import eigh
        values,vectors=eigh(K.toarray(),M.toarray())
        vectors,err=mass_normalize(vectors,M)
        F=np.array([[1.,2.],[3.,-1.]])
        for f in (0.,.1,.3,1.):
            direct,_=direct_response(K,M,F,f,.02,.005)
            approximate=modal_response(values,vectors,F,f,.02,.005)
            np.testing.assert_allclose(approximate,direct,rtol=1e-12,atol=1e-12)
        self.assertLess(err,1e-12)

    def test_massless_compliance_requires_explicit_restoration(self):
        K=diags([4.,5.]);M=diags([2.,0.]);F=np.array([[1.],[3.]])
        values=np.array([2.]);phi=np.array([[1/np.sqrt(2.)],[0.]])
        static=np.array([[.25],[.6]])
        mass=check_mass(M);self.assertEqual(mass['positive_mass_rank'],1)
        for f in (0.,.3,1.):
            direct,_=direct_response(K,M,F,f,.02,.01)
            raw=modal_response(values,phi,F,f,.02,.01)
            restored=modal_response(values,phi,F,f,.02,.01,static)
            self.assertGreater(abs(direct[1,0]-raw[1,0]),.5)
            np.testing.assert_allclose(restored,direct,rtol=1e-12,atol=1e-12)

    def test_static_correction_is_not_dynamic_accuracy_guarantee(self):
        K=diags([1.,4.]);M=diags([1.,1.]);F=np.ones((2,1))
        phi=np.array([[1.],[0.]]);values=np.array([1.]);static=np.array([[1.],[.25]])
        f=np.sqrt(4.)/(2*np.pi)
        direct,_=direct_response(K,M,F,f,.01,.001)
        corrected=modal_response(values,phi,F,f,.01,.001,static)
        self.assertGreater(abs(direct[1,0]-corrected[1,0])/abs(direct[1,0]),.9)
        np.testing.assert_allclose(modal_response(values,phi,F,0.,.01,.001,static),static)

    def test_complex_error_detects_wrong_phase_despite_equal_peak(self):
        f=np.linspace(.05,1,20);reference=np.ones(20,dtype=complex)
        result=response_metrics(f,reference,1j*reference)
        self.assertTrue(result['peak_passed']);self.assertFalse(result['L2_passed'])
        self.assertAlmostEqual(result['phase_max_abs_difference_deg'],90.)

    def test_near_zero_is_absolute_not_infinite_relative_error(self):
        f=np.linspace(.05,1,20);r=np.zeros(20,dtype=complex)
        result=response_metrics(f,r,r+1e-8)
        self.assertTrue(result['L2_passed']);self.assertIsNone(result['complex_L2_relative_error'])
        self.assertIsNone(result['phase_max_abs_difference_deg'])
        with self.assertRaises(ValueError):response_metrics(f[::-1],r,r)
        with self.assertRaises(ValueError):response_metrics(f,r,r+np.nan)

    def test_no_negative_or_fake_mass_admission(self):
        with self.assertRaises(ValueError):check_mass(diags([-1.,2.]))
        with self.assertRaises(ValueError):check_mass(csc_matrix([[1.,.1],[.1,2.]]))

    def test_frequency_grid_contains_fixed_band_limits_and_resonances(self):
        values=(2*np.pi*np.array([.2,1.,2.5]))**2
        f=frequency_grid(values,.02,.001)
        self.assertTrue(all(np.min(abs(f-v))<1e-10 for v in [.05,.9,3.,.2,1.,2.5]))
        self.assertTrue(np.all(np.diff(f)>0))

    def test_output_overwrite_is_rejected_before_loading_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'saved').write_text('existing evidence')
            with self.assertRaises(FileExistsError):run(directory)

    def test_projection_and_subband_grid_cannot_inherit_cartesian_pass(self):
        f=np.array([.05,.9,3.]);ff=np.array([.05,.475,.9,1.95,3.])
        coarse=np.ones((3,3,3),dtype=complex);fine=np.ones((5,3,3),dtype=complex)
        fine[1,1,1]+=.001
        cartesian=refinement_metrics(f,coarse,ff,fine)
        self.assertTrue(all(row['passed'] for row in cartesian))
        obs=[{'name':'control','group':'control','node_tag':350,'direction':d} for d in ['X','Y','Z']]
        desc,project=output_projection(obs)
        rows=projected_grid_checks(f,project(coarse),ff,project(fine),desc)
        cross=[r for r in rows if r['angle_deg']==45 and r['direction']=='cross' and r['band']=='common_40_to_300']
        self.assertEqual(len(cross),1);self.assertFalse(cross[0]['passed'])


OUTPUT=Path(__file__).resolve().parents[1]/'initial_imperfection_material/tian_ma_qu/followup_results/B2_20261024/frequency_response'

@unittest.skipUnless((OUTPUT/'summary.json').exists(),'local N06 evidence not installed')
class FrequencySavedEvidenceTests(unittest.TestCase):
    def test_saved_matrix_identity_and_eigen_quality(self):
        from scipy.sparse import load_npz
        source=OUTPUT.parents[2]/'modal_results/runs/coupled_80_checked'
        frozen=json.loads((OUTPUT/'frozen_plan.json').read_text())
        for name in ('mass.npz','stiffness.npz'):
            self.assertEqual(hashlib.sha256((source/name).read_bytes()).hexdigest(),frozen['C_candidate']['input_matrix_sha256'][name])
        M=load_npz(source/'mass.npz');K=load_npz(source/'stiffness.npz')
        data=np.load(OUTPUT/'expanded_modes.npz');values,phi=data['values'],data['vectors']
        self.assertEqual(len(values),300);self.assertTrue(np.all(values>0))
        kv=K@phi;mv=(M@phi)*values
        residual=np.linalg.norm(kv-mv,axis=0)/(np.linalg.norm(kv,axis=0)+np.linalg.norm(mv,axis=0))
        self.assertLess(max(residual),1e-6)
        self.assertLess(np.max(abs(phi.T@(M@phi)-np.eye(300))),1e-6)

    def test_every_output_band_has_its_own_grid_and_admission_check(self):
        rows=json.loads((OUTPUT/'frequency_grid_checks.json').read_text())[-1]['checks']
        descriptors=json.loads((OUTPUT/'output_descriptors.json').read_text())
        self.assertEqual(len(rows),2*len(descriptors))
        lookup={(r['angle_deg'],r['name'],r['direction'],r['band']):r['passed'] for r in rows}
        self.assertEqual(len(lookup),len(rows))
        with (OUTPUT/'response_metrics.csv').open() as stream:
            for metric in csv.DictReader(stream):
                key=(int(metric['angle_deg']),metric['name'],metric['direction'],metric['band'])
                self.assertEqual(metric['frequency_grid_passed']=='True',lookup[key])
                passed=lookup[key] and all(metric[k]=='True' for k in ('band_covered_by_modes','L2_passed','peak_passed'))
                self.assertEqual(metric['frequency_passed']=='True',passed)
        admission=json.loads((OUTPUT/'modal_admission.json').read_text())
        self.assertFalse(admission['G2_passed']);self.assertFalse(admission['global_G1_passed'])
        self.assertFalse(admission['actual_C_implemented_confirmed'])

    def test_postprocessing_retains_original_and_preserves_raw_response(self):
        audit=json.loads((OUTPUT/'postprocessing_revision.json').read_text())
        self.assertFalse(audit['raw_responses_modified']);self.assertEqual(audit['new_eigen_solves'],0)
        self.assertEqual(hashlib.sha256((OUTPUT/'frequency_responses.npz').read_bytes()).hexdigest(),audit['raw_responses_sha256'])
        self.assertTrue((OUTPUT/audit['initial_publication_retained']/'summary.json').is_file())

if __name__=='__main__':unittest.main()
