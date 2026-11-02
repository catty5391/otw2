import math
from pathlib import Path
import tempfile
import unittest

from model.insulator_mechanics import axial_contract, register_axial_material, v_geometry
from initial_imperfection_material.tian_ma_qu.directional_loading import verification_config, validate_config
from initial_imperfection_material.tian_ma_qu.insulator_experiment import analytical_slack_state, run_standalone


class InsulatorContractTests(unittest.TestCase):
    def test_default_and_explicit_laws_do_not_silently_regularize(self):
        self.assertEqual(axial_contract({})["compression_stiffness_ratio"], 1.)
        self.assertEqual(axial_contract({"axial_behavior":"tension_only"})["compression_stiffness_ratio"], 0.)
        self.assertEqual(axial_contract({"axial_behavior":"regularized_tension_only", "compression_stiffness_ratio":1e-6})["compression_stiffness_ratio"], 1e-6)

    def test_invalid_and_contradictory_laws_are_rejected(self):
        for material in ({"axial_behavior":"unknown"}, {"axial_behavior":"regularized_tension_only"},
                         {"axial_behavior":"tension_only", "compression_stiffness_ratio":.01},
                         {"axial_behavior":"elastic", "compression_stiffness_ratio":0},
                         {"compression_stiffness_ratio":math.nan}, {"compression_stiffness_ratio":True}):
            with self.subTest(material=material), self.assertRaises(ValueError): axial_contract(material)

    def test_existing_geometry_is_drop_not_leg_length(self):
        geometry = v_geometry([(19.3,0.,33.),(1.95,0.,33.)],(10.625,0.,29.))
        self.assertAlmostEqual(geometry["initial_leg_lengths_m"][0],9.55278100869061)
        self.assertAlmostEqual(geometry["included_angle_deg"],130.49160939566522)
        self.assertAlmostEqual(geometry["drop_from_upper_midpoint_m"],4.)
        with self.assertRaises(ValueError): v_geometry([(0,0,0),(0,0,0)],(0,0,-4))

    def test_configuration_is_explicit_and_old_defaults_preserved(self):
        baseline=verification_config(0,mode="tower_line_explicit")
        self.assertNotIn("insulator_axial_behavior",validate_config(baseline))
        c={**baseline,"insulator_axial_behavior":"tension_only"}
        self.assertEqual(validate_config(c)["insulator_compression_stiffness_ratio"],0)
        self.assertNotIn("insulator_compression_stiffness_ratio",c)
        with self.assertRaises(ValueError):validate_config({**c,"mode":"single_tower"})


class InsulatorNativeTests(unittest.TestCase):
    def tearDown(self):
        import openseespy.opensees as ops
        ops.wipe()

    def test_material_compression_release_and_reload_are_reversible(self):
        import openseespy.opensees as ops
        ops.wipe()
        register_axial_material(ops,1,1e8,2.,{"axial_behavior":"tension_only"})
        ops.testUniaxialMaterial(1)
        for strain in (1e-3,0.,-.2,0.,1e-3):
            ops.setStrain(strain)
            self.assertAlmostEqual(ops.getStress()*2.,1e8*max(0.,strain))
        with self.assertRaises(ValueError):register_axial_material(ops,2,1e8,0.,{})

    def test_actual_line_setup_keeps_source_configuration_separate_from_override(self):
        import json
        from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
        from initial_imperfection_material.tian_ma_qu.directional_loading import attach_explicit_lines
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            tower=OpenSeesModelWithTianMaQu(root/"Source/Z30103A6.s2k",output_dir=output/"tower",axial_mode="elastic")
            tower.model_tower()
            config=validate_config({**verification_config(0,mode="tower_line_explicit"),"insulator_axial_behavior":"tension_only"})
            system,_=attach_explicit_lines(tower,output/"lines",config)
            original=json.loads(system.config_path.read_text())
            self.assertEqual(json.loads((output/"lines/source_configuration.json").read_text()),original)
            self.assertEqual({r["compression_stiffness_ratio"] for r in system.insulator_map.values()},{0.})

    def test_two_leg_solution_matches_analytical_slack_geometry_and_unloads(self):
        s,rows=run_standalone("tension_only",increment=.05)
        self.assertLess(s["analytical_position_error_m"],1e-7)
        self.assertLess(s["return_to_gravity_position_error_m"],1e-7)
        self.assertLess(s["maximum_equilibrium_residual_N"],1e-4)
        self.assertGreaterEqual(s["minimum_force_N"],-1e-7)
        self.assertGreater(s["peak"]["ux_m"],.3)
        self.assertTrue(any(row["horizontal_to_vertical_ratio"] < -2.9 for row in rows))
        with self.assertRaises(ValueError):analytical_slack_state(8.675,4,1e8,5000,0.)

    def test_regularization_error_and_original_compressive_force_are_visible(self):
        exact,_=run_standalone("tension_only",increment=.1,targets=(3.,0.))
        soft,_=run_standalone("regularized",increment=.1,targets=(3.,0.))
        elastic,_=run_standalone("elastic",increment=.1,targets=(3.,0.))
        self.assertLess(abs(soft["peak"]["ux_m"]-exact["peak"]["ux_m"]),.003)
        self.assertLess(soft["minimum_force_N"],0)
        self.assertLess(elastic["minimum_force_N"],-1000)
        self.assertLess(elastic["peak"]["ux_m"],.01)


if __name__=="__main__": unittest.main()
