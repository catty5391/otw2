"""Artifact/protocol/adapter tests; no claim of agreement with experiments."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.experiment import (
    curve_points, demonstration_targets, displacement_history, numerical_checks,
    simulate, summarize_case,
)


class TMQExperimentTests(unittest.TestCase):
    def test_nominal_pipe_names_are_not_outside_diameters(self):
        a,b,c=literature_cases()
        self.assertAlmostEqual(a.outside_diameter,.1143)
        self.assertAlmostEqual(c.outside_diameter,.1016)
        self.assertAlmostEqual(a.area*1e6,2047.833348,places=5)
        self.assertAlmostEqual(c.area*1e6,1728.618632,places=5)
        self.assertNotEqual(a.parameters.phi,b.parameters.phi)
        self.assertIn("assumptions",a.to_dict())

    def test_protocol_retains_all_turning_points_and_final_zero(self):
        targets=demonstration_targets();history=displacement_history(targets,7)
        self.assertEqual(len(history),34*7+1)
        self.assertEqual([row[2] for row in history if row[3]],targets)
        self.assertEqual(history[-1][2],0)
        self.assertEqual(max(targets),.035)
        self.assertEqual(min(targets),-.035)

    def test_rejects_invalid_histories(self):
        for targets,steps in (([0,0],2),([1,2],2),([0,float('nan')],2),([0,1],0)):
            with self.assertRaises(ValueError):displacement_history(targets,steps)

    def test_all_three_cases_cover_full_mechanism_without_tail_extension(self):
        required={"elastic","tension_hardening","compression_elastic","compression_unloading",
                  "first_compression_softening_1","first_compression_softening_2",
                  "subsequent_compression_softening_1","subsequent_compression_softening_2",
                  "tension_pinching","tension_reloading"}
        for case in literature_cases():
            with self.subTest(case=case.key):
                rows,events=simulate(case,steps_per_leg=50)
                summary=summarize_case(case,rows,events)
                self.assertEqual(len(rows),1701)
                self.assertTrue(summary["complete"])
                self.assertTrue(required.issubset(summary["stages_visited"]))
                self.assertEqual(summary["tail_extension_steps"],0)
                self.assertEqual(summary["buckling_count"],13)
                self.assertAlmostEqual(summary["first_buckling_kN"],case.parameters.first_buckling_stress*case.area/1000)
                self.assertAlmostEqual(summary["subsequent_buckling_kN"],summary["first_buckling_kN"]*case.parameters.eta)

    def test_curve_points_preserve_history_and_include_exact_peak(self):
        case=literature_cases()[0]
        rows,events=simulate(case,steps_per_leg=5)
        points=curve_points(case,rows,events)
        summary=summarize_case(case,rows,events)
        self.assertAlmostEqual(min(points[:,1]),summary["first_buckling_kN"])
        self.assertEqual(points[0,0],0)
        self.assertEqual(points[-1,0],0)
        self.assertTrue(any(a>b for a,b in zip(points[:,0],points[1:,0])))
        self.assertTrue(any(a<b for a,b in zip(points[:,0],points[1:,0])))

    def test_elastic_recovery_and_refinement(self):
        case=literature_cases()[0];targets=demonstration_targets()
        rows,_=simulate(case,targets,20)
        result=numerical_checks(case,targets,20,rows)
        self.assertTrue(result["passed"],result)

    def test_existing_results_are_protected(self):
        from initial_imperfection_material.tian_ma_qu.run_experiment import run_experiment
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"keep.txt";p.write_text("preserve")
            with self.assertRaises(FileExistsError):run_experiment(folder)
            self.assertEqual(p.read_text(),"preserve")

    def test_plot_and_viewer_artifacts_have_full_data(self):
        from initial_imperfection_material.tian_ma_qu.visualization import create_figures,create_viewer
        bundles=[]
        for case in literature_cases():
            rows,events=simulate(case,steps_per_leg=3)
            bundles.append({"case":case,"rows":rows,"events":events})
        with tempfile.TemporaryDirectory() as folder:
            create_figures(folder,bundles,[])
            create_viewer(folder,bundles)
            for filename in ("full_hysteresis.png","full_hysteresis.pdf","full_hysteresis.svg",
                             "loading_history.png","mechanism_checks.png","index.html"):
                self.assertGreater((Path(folder)/filename).stat().st_size,500)
            page=(Path(folder)/"index.html").read_text()
            payload=json.loads(page.split("const data=",1)[1].split(";\nconst select",1)[0])
            self.assertEqual(len(payload),3)
            self.assertTrue(all(len(item["rows"])==103 for item in payload))

    @unittest.skipUnless(os.environ.get("TMQ_TEST_NATIVE")=="1","opt-in native ABI test; set TMQ_TEST_NATIVE=1")
    def test_native_material_copies_are_independent(self):
        code='''
import openseespy.opensees as ops
from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.opensees_adapter import register_material
c=literature_cases()[0]
ops.wipe()
try:
    ops.model('basic','-ndm',1,'-ndf',1)
    ops.node(1,0.0);ops.node(2,c.length);ops.node(3,c.length)
    ops.fix(1,1);ops.fix(3,1)
    register_material(1,c.parameters)
    ops.element('truss',1,1,2,c.area,1);ops.element('truss',2,1,3,c.area,1)
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1);ops.load(2,1.0)
    ops.constraints('Plain');ops.numberer('Plain');ops.system('FullGeneral')
    ops.test('NormUnbalance',1e-6,30);ops.algorithm('Newton')
    ops.integrator('DisplacementControl',2,1,.0001);ops.analysis('Static')
    assert ops.analyze(100)==0
    s1=ops.eleResponse(1,'material','stress')[0]
    s2=ops.eleResponse(2,'material','stress')[0]
    assert s1>c.parameters.yield_stress,(s1,s2)
    assert s2==0,(s1,s2)
finally:
    ops.wipe()
print('TMQ_COPIES_OK')
'''
        result=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("TMQ_COPIES_OK",result.stdout)

    @unittest.skipUnless(os.environ.get("TMQ_TEST_NATIVE")=="1","opt-in native ABI test; set TMQ_TEST_NATIVE=1")
    def test_actual_opensees_truss_in_isolated_process(self):
        code='''
import json
from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.experiment import simulate,run_opensees
for case in literature_cases():
    rows,_=simulate(case,steps_per_leg=8)
    native,result=run_opensees(case,rows)
    assert result['complete'],result
    assert result['passed'],result
    assert len(native)==len(rows)
print('TMQ_NATIVE_OK')
'''
        result=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("TMQ_NATIVE_OK",result.stdout)


if __name__=="__main__":unittest.main()
