"""Wind-speed mapping, rejected inputs, real loading and interpretation checks."""
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.directional_loading import verification_config
from initial_imperfection_material.tian_ma_qu.wind_speed_exploration import collect_case, speed_from_factor


class WindSpeedTests(unittest.TestCase):
    def test_speed_squared_mapping_and_invalid_factors(self):
        self.assertEqual(speed_from_factor(20,0),0)
        self.assertEqual(speed_from_factor(20,9),60)
        self.assertAlmostEqual(speed_from_factor(30,4),60)
        for ref,factor in ((0,1),(math.nan,1),(20,-1),(20,math.inf)):
            with self.subTest(ref=ref,factor=factor),self.assertRaises(ValueError):
                speed_from_factor(ref,factor)

    def test_reject_invalid_ramp_before_creating_output(self):
        from initial_imperfection_material.tian_ma_qu.full_tower import run
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"unused"
            for targets in ((),(20,20),(30,20),(0,20),(math.nan,)):
                with self.subTest(targets=targets),self.assertRaises(ValueError):
                    run(out,wind_speed_targets=targets,directional_config=verification_config(0),control_dof=1)
                self.assertFalse(out.exists())
            with self.assertRaisesRegex(ValueError,"dimensional"):
                run(out,wind_speed_targets=(20,))
            self.assertFalse(out.exists())

    def test_real_elastic_tower_ramp_keeps_gravity_and_scales_xy_together(self):
        from initial_imperfection_material.tian_ma_qu.full_tower import run
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"tower"
            result=run(root,axial_mode="elastic",control_dof=1,
                directional_config=verification_config(30),wind_speed_targets=(10,20,30),
                maximum_load_increment=1,timeout=60)
            self.assertEqual(result["status"],"complete")
            self.assertEqual(result["completed_targets"],3)
            self.assertFalse(result["true_ultimate_wind_speed_established"])
            self.assertTrue(result["ceiling_reached_without_establishing_limit"])
            plan=json.loads((root/"wind_load_plan.json").read_text())
            force=plan["combined_initial_coordinate_resultant"]["force_N"]
            with (root/"history.csv").open() as f: rows=list(csv.DictReader(f))
            with (root/"support_reactions.csv").open() as f: reactions=list(csv.DictReader(f))
            self.assertAlmostEqual(float(rows[-1]["wind_load_factor"]),2.25)
            for row in rows:
                factor=float(row["wind_load_factor"])
                self.assertAlmostEqual(float(row["equivalent_wind_speed_m_s"]),20*math.sqrt(factor))
                support=[r for r in reactions if r["step"]==row["step"]]
                for i,key in enumerate(("Rx_N","Ry_N","Rz_N")):
                    expected=factor*force[i]-(9.81*result["total_gravity_mass_kg"] if i==2 else 0)
                    self.assertAlmostEqual(-sum(float(r[key]) for r in support),expected,delta=.01)

    def test_numerical_stop_ceiling_and_peak_are_not_certified_collapse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/"runs/case";run.mkdir(parents=True)
            execution=dict(key="case",process_returncode=2,process_timed_out=False,
                           continuation_target_control_drift=None)
            with (run/"history.csv").open("w") as f:
                f.write("wind_load_factor\n0\n4\n3\n")
            (run/"equilibrium.jsonl").write_text('\n'.join(json.dumps({"passed":True}) for _ in range(3)))
            summary=dict(status="partial",accepted_steps=2,stop_reason="minimum_increment")
            (run/"summary.json").write_text(json.dumps(summary))
            result=collect_case(root,execution)
            self.assertTrue(result["evidence_valid"])
            self.assertEqual(result["classification"],"numerical_boundary_not_collapse")
            self.assertIsNone(result["true_ultimate_wind_speed_m_s"])
            execution["continuation_target_control_drift"]=.02
            self.assertEqual(collect_case(root,execution)["classification"],"sampled_path_peak_with_decline_not_certified_collapse")
            execution["continuation_target_control_drift"]=None
            summary["status"]="complete";summary["stop_reason"]=None
            (run/"summary.json").write_text(json.dumps(summary))
            self.assertEqual(collect_case(root,execution)["classification"],"requested_range_completed_limit_not_established")
            summary["accepted_steps"]=3
            (run/"summary.json").write_text(json.dumps(summary))
            self.assertFalse(collect_case(root,execution)["evidence_valid"])


if __name__=="__main__":unittest.main()
