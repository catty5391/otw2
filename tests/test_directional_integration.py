"""Input guards, real OpenSees loading, and saved directional case evidence."""
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from util.processing.directional_wind import apply_nodal_wind_loads, wind_unit_vector
from util.preprocess.tag_manager import TagManager
from initial_imperfection_material.tian_ma_qu.directional_loading import verification_config, validate_config

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/"initial_imperfection_material/tian_ma_qu/directional_results_v2"


def read_csv(path):
    with path.open(newline="",encoding="utf-8") as source:
        return list(csv.DictReader(source))


class DirectionalIntegrationTests(unittest.TestCase):
    def test_explicit_configuration_guards(self):
        self.assertFalse(validate_config(verification_config(30))["validated_for_design"])
        for key,value in (("mode","multiple_towers"),("line_segments",2.5),("air_density",0),
                          ("wind_speed_m_s",math.nan),("height_factors",[1]),("coefficient_provenance","")):
            c=verification_config(30);c[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_config(c)

    def test_perpendicular_control_rejected_before_creating_evidence(self):
        from initial_imperfection_material.tian_ma_qu.full_tower import run
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/"should_not_exist"
            with self.assertRaisesRegex(ValueError,"perpendicular"):
                run(out,control_dof=2,directional_config=verification_config(0))
            self.assertFalse(out.exists())

    def test_real_opensees_path_components_synchronized_without_transverse_restraint(self):
        import openseespy.opensees as ops
        ops.wipe()
        try:
            ops.model("basic","-ndm",3,"-ndf",6)
            ops.node(1,0,0,0);ops.node(2,0,0,3)
            ops.fix(1,1,1,1,1,1,1)
            ops.geomTransf("Linear",1,1,0,0)
            ops.element("elasticBeamColumn",1,1,2,.01,2e11,8e10,1e-4,1e-5,1e-5,1)
            ops.setTime(7.)
            load=apply_nodal_wind_loads({2:(300,400,0,0,0,0)},TagManager(),ops,
                                      time_series_type="Path",path_values=[0,1,.5,0],dt=1.)
            ops.constraints("Plain");ops.numberer("RCM");ops.system("BandGeneral")
            ops.algorithm("Linear");ops.integrator("LoadControl",1.);ops.analysis("Static")
            for factor in (1.,.5,0.):
                self.assertEqual(ops.analyze(1),0)
                ops.reactions()
                self.assertAlmostEqual(ops.getLoadFactor(load.pattern_tag),factor)
                self.assertAlmostEqual(-ops.nodeReaction(1,1),300*factor,places=8)
                self.assertAlmostEqual(-ops.nodeReaction(1,2),400*factor,places=8)
                self.assertAlmostEqual(ops.nodeDisp(2,1)*4,ops.nodeDisp(2,2)*3,places=10)
        finally: ops.wipe()


@unittest.skipUnless((RESULTS/"summary.json").is_file(),"saved verification matrix not generated")
class DirectionalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.summary=json.loads((RESULTS/"summary.json").read_text())

    def test_eight_cases_complete_no_capacity_claim(self):
        s=self.summary
        self.assertEqual(s["case_count"],8)
        self.assertTrue(s["passed"])
        self.assertFalse(s["validated_for_design"])
        self.assertFalse(s["capacity_or_collapse_evaluated"])
        self.assertEqual({(c["mode"],c["wind_angle_deg"]) for c in s["cases"]},
                         {(m,a) for m in ("single_tower","tower_line_explicit") for a in (0,30,45,90)})
        for c in s["cases"]:
            self.assertTrue(c["passed"])
            self.assertEqual(c["run"]["completed_targets"],3)
            self.assertLess(c["global_horizontal_balance_max_N"],.01)
            self.assertIn("directional_input_sha256",c["run"])

    def test_all_directions_and_moments(self):
        for c in self.summary["cases"]:
            t=c["tower_load"];direction=wind_unit_vector(c["wind_angle_deg"])
            for force,unit in zip(t["force_N"],direction):
                self.assertAlmostEqual(force,t["force_magnitude_N"]*unit,delta=1e-7)
            self.assertLess(abs(t["moment_Nm"][2]),1e-7)
            self.assertLess(max(map(abs,t["moment_residual_Nm"])),1e-6)
            self.assertLess(c["conductor_lumping_max_residual"],1e-6)
            for row in c["history"]:
                u=float(row["ux_m"])*direction[0]+float(row["uy_m"])*direction[1]
                self.assertAlmostEqual(u,float(row["along_wind_displacement_m"]),places=12)

    def test_gravity_not_duplicated_and_support_outputs_complete(self):
        bare=next(c for c in self.summary["cases"] if c["key"]=="single_0")["run"]["total_gravity_mass_kg"]
        for c in self.summary["cases"]:
            directory=RESULTS/"runs"/c["key"]
            reactions=read_csv(directory/"support_reactions.csv")
            self.assertEqual(len(reactions),len(c["history"])*(8 if c["mode"]=="tower_line_explicit" else 4))
            plan=json.loads((directory/"wind_load_plan.json").read_text())
            for state in c["history"]:
                step=int(state["step"])
                support_rows=[r for r in reactions if int(r["step"])==step]
                for component,key in enumerate(("Rx_N","Ry_N","Rz_N")):
                    external=float(state["wind_load_factor"])*plan["combined_initial_coordinate_resultant"]["force_N"][component]
                    if component==2:
                        external-=c["run"]["total_gravity_mass_kg"]*9.81
                    self.assertAlmostEqual(-sum(float(r[key]) for r in support_rows),external,delta=.01)
            if c["mode"]=="tower_line_explicit":
                lines=read_csv(directory/"line_model/transmission_lines.csv")
                expected=bare+100+sum(float(r["total_conductor_mass"]) for r in lines)
                self.assertAlmostEqual(c["run"]["total_gravity_mass_kg"],expected,places=7)
                self.assertEqual(c["run"]["line_model"]["towers"],1)
                self.assertTrue((directory/"line_model/effective_configuration.json").is_file())
                line_history=read_csv(directory/"line_history.csv")
                self.assertEqual(len(line_history),len(c["history"])*80)
                self.assertTrue(all(float(r["axial_force_N"])>0 for r in line_history))
            g=plan["gravity_coordinate_resultants"]
            for k in ("force_N","moment_Nm"):
                for i in range(3):
                    expected=g["tower"][k][i]+(g["conductors"][k][i] if g["conductors"] else 0)
                    self.assertAlmostEqual(g["combined"][k][i],expected,delta=1e-6)


if __name__=="__main__": unittest.main()
