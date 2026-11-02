import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.parameter_identification import (
    Bound,decode,ordered_data,response,genetic_minimize,identify_peak,synthetic_manifest,run_synthetic,
    black_peak_features,fit_ordered_history,KIP_N,KSI_PA,
)


class IdentificationContractTests(unittest.TestCase):
    def setUp(self):
        self.p=literature_cases()[0].parameters
        self.manifest=synthetic_manifest(self.p,[0.,.002,-.004,.003,0.],key='contract',steps=3)

    def test_units_convert_but_history_is_not_sorted_by_displacement(self):
        data=ordered_data(self.manifest)
        converted=copy.deepcopy(self.manifest)
        converted['units'].update(displacement='mm',force='kN')
        for r in converted['samples']:r['displacement']*=1000;r['force']/=1000
        actual=ordered_data(converted)
        np.testing.assert_allclose(data['displacement_m'],actual['displacement_m'])
        np.testing.assert_allclose(data['force_N'],actual['force_N'])
        self.assertTrue(np.any(np.diff(actual['displacement_m'])<0))
        self.assertAlmostEqual(float(data['weights'].sum()),1.)

    def test_unordered_image_or_unknown_initial_history_rejected(self):
        for key,value in [('ordered',False),('ordering_evidence',''),('initial_state','unknown'),('data_kind','unlabelled')]:
            with self.subTest(key=key):
                m=copy.deepcopy(self.manifest);m[key]=value
                with self.assertRaises(ValueError):ordered_data(m)
        m=copy.deepcopy(self.manifest);m['samples'][2]['sequence']=m['samples'][1]['sequence']
        with self.assertRaises(ValueError):ordered_data(m)
        m=copy.deepcopy(self.manifest);m['samples'][0]['force']=500
        with self.assertRaises(ValueError):ordered_data(m)

    def test_unknown_units_nonfinite_and_unknown_sign_rejected(self):
        for key,value in [('displacement','inch'),('force','kg'),('sign','compression_positive')]:
            m=copy.deepcopy(self.manifest);m['units'][key]=value
            with self.assertRaises(ValueError):ordered_data(m)
        m=copy.deepcopy(self.manifest);m['samples'][3]['force']=float('nan')
        with self.assertRaises(ValueError):ordered_data(m)

    def test_declared_geometry_and_material_property_provenance_required(self):
        for key in ['geometry_basis','material_property_basis']:
            m=copy.deepcopy(self.manifest);m[key]=''
            with self.assertRaises(ValueError):ordered_data(m)
        for key in ['elastic_modulus_Pa','yield_stress_Pa']:
            m=copy.deepcopy(self.manifest);m[key]=0
            with self.assertRaises(ValueError):ordered_data(m)

    def test_fixed_modulus_and_coupled_search_bounds_checked_before_fit(self):
        data=ordered_data(self.manifest)
        with self.assertRaises(ValueError):fit_ordered_history(data,replace(self.p,elastic_modulus=210e9),[Bound('phi',.4,.9)])
        with self.assertRaises(ValueError):fit_ordered_history(data,self.p,[Bound('mu',.3,1.5),Bound('nu',.8,2.)])

    def test_fitted_parameter_provenance_names_evidence_not_literature_template(self):
        fit=fit_ordered_history(ordered_data(self.manifest),self.p,[Bound('phi',.4,.9)],
                                seeds=(17,),population=8,generations=2)
        provenance=fit['best_parameters']['provenance']
        self.assertIn('data_kind=synthetic_same_model',provenance)
        self.assertIn('specimen_id=contract',provenance)
        self.assertIn('fitted_parameters=phi',provenance)
        self.assertIn(self.manifest['source'],provenance)
        self.assertIn('non-production',provenance)
        self.assertNotEqual(provenance,self.p.provenance)
        self.assertEqual(fit['template_provenance'],self.p.provenance)
        self.assertNotIn('provenance',fit['fixed_parameters'])
        self.assertEqual(fit['runs'][0]['parameters']['provenance'],provenance)

    def test_original_black_units_and_feature_semantics_are_preserved(self):
        features=black_peak_features()
        self.assertEqual(len(features),5)
        by_id={f['specimen_id']:f for f in features}
        f=by_id['Black_1980_8_double_angle_PP']
        self.assertAlmostEqual(f['compression_peak_N'],197*KIP_N)
        self.assertAlmostEqual(f['yield_stress_Pa'],40.8*KSI_PA)
        self.assertIn('coupon',f['yield_basis'])
        for f in features:
            self.assertEqual(f['feature_type'],'first_buckling_peak')
            self.assertFalse(f['angle_transfer_permitted'])
            self.assertIn('not supplied',f['measurement_uncertainty'])
        self.assertIn('not independent coupon',by_id['Black_1980_14_pipe4_PP']['yield_basis'])

    def test_log_bounds_roundtrip_and_material_coupled_constraint(self):
        b=Bound('beta',.001,.1,'log')
        self.assertAlmostEqual(b.value(.5),.01);self.assertAlmostEqual(b.coordinate(.01),.5)
        with self.assertRaises(ValueError):b.value(-.1)
        with self.assertRaises(ValueError):Bound('beta',0,.1,'log')
        with self.assertRaises(ValueError):decode(self.p,[Bound('mu',2,3)],[.5])

    def test_ga_is_reproducible_bounded_and_elitist(self):
        objective=lambda x:float(np.dot(x-np.array([.23,.67]),x-np.array([.23,.67])))
        a=genetic_minimize(objective,2,seed=17,population=20,generations=50)
        b=genetic_minimize(objective,2,seed=17,population=20,generations=50)
        self.assertEqual(a['genes'],b['genes']);self.assertEqual(a['objective'],b['objective'])
        self.assertLess(a['objective'],1e-4)
        self.assertTrue(all(0<=g<=1 for g in a['genes']))
        self.assertTrue(np.all(np.diff([r['best_objective'] for r in a['history']])<=0))

    def test_ga_rejects_population_with_no_admissible_parameters(self):
        with self.assertRaises(ValueError):genetic_minimize(lambda g:float('nan'),1,seed=1,generations=2,population=8)

    def test_peak_identification_is_dimensionally_exact_and_limited(self):
        f={'specimen_id':'known','feature_type':'first_buckling_peak','source':'controlled feature','geometry_basis':'known','yield_basis':'known',
           'area_m2':.002,'yield_stress_Pa':300e6,'compression_peak_N':420e3}
        result=identify_peak(f)
        self.assertAlmostEqual(result['identified_phi'],.7)
        self.assertLess(abs(result['ga_phi']-.7),.002)
        self.assertFalse(result['whole_tower_applicable']);self.assertIn('eta',result['unidentified_parameters'])
        f['compression_peak_N']=900e3
        with self.assertRaises(ValueError):identify_peak(f)

    def test_whole_test_maximum_cannot_be_used_as_first_buckling(self):
        f={'specimen_id':'angle','feature_type':'whole_test_compression_maximum','source':'table','geometry_basis':'known','yield_basis':'known',
           'area_m2':.002,'yield_stress_Pa':300e6,'compression_peak_N':420e3}
        with self.assertRaises(ValueError):identify_peak(f)

    def test_peak_does_not_determine_softening_or_reload_parameters(self):
        p=self.p;q=replace(p,alpha=p.alpha*1.5,eta=p.eta*.8)
        limit=-p.phi*p.yield_strain
        a=response(p,[0,limit,limit*2]);b=response(q,[0,limit,limit*2])
        self.assertAlmostEqual(a[1],b[1]);self.assertNotAlmostEqual(a[2],b[2])

    def test_prebuckling_history_cannot_identify_postbuckling_shape(self):
        e=np.array([0.,.0001,-.0002,.00015,0.])
        a=response(self.p,e);b=response(replace(self.p,alpha=.9,beta=.03,gamma=.3,eta=.3),e)
        np.testing.assert_allclose(a,b,atol=1e-7)

    def test_existing_output_evidence_is_protected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'keep').write_text('original')
            with self.assertRaises(FileExistsError):run_synthetic(p)
            self.assertEqual((p/'keep').read_text(),'original')


if __name__=='__main__':unittest.main()
