"""Fairness and physical-result mapping checks for the comparison workflow."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison import (
    ROOT, case_directory, compare_audits, execute_case, project_end_forces, validate_speeds,
)


class SingleTowerWindComparisonTests(unittest.TestCase):
    def test_tension_projection_keeps_physical_endpoint_values(self):
        # Arbitrary initial chord. Lateral force is orthogonal, so it must not
        # contaminate the physical-member axial component.
        chord = (3., 4., 0.)
        first = [-60.+8., -80.-6., 7., 1., 2., 3., 0., 0., 0., 0., 0., 0.]
        last = [0., 0., 0., 0., 0., 0., 72.+8., 96.-6., 7., 3., 2., 1.]
        self.assertEqual(project_end_forces(first, last, chord), (100.,120.,110.))

    def test_compression_and_endpoint_orientation(self):
        first = [100.,0.,0.,0.,0.,0.,-100.,0.,0.,0.,0.,0.]
        self.assertEqual(project_end_forces(first, first, (2.,0.,0.)),(-100.,-100.,-100.))
        reversed_force = first[6:]+first[:6]
        self.assertEqual(project_end_forces(reversed_force,reversed_force,(-2.,0.,0.)),(-100.,-100.,-100.))
        with self.assertRaises(ValueError):
            project_end_forces(first,first,(0.,0.,0.))

    def test_audit_rejects_missing_evidence_and_single_load_change(self):
        audit = {key:"a" for key in ("original_geometry_sha256", "physical_member_inputs_sha256",
            "nodal_mass_sha256", "supports_sha256", "wind_nodal_load_sha256")}
        audit.update(reference_wind_resultant={"force_N":[1.,2.,0.],"moment_Nm":[2.,-1.,0.]},total_mass_xyz_kg=[3.,3.,3.])
        self.assertTrue(compare_audits(audit,audit)["passed"])
        changed = copy.deepcopy(audit)
        changed["wind_nodal_load_sha256"]="different"
        self.assertFalse(compare_audits(audit,changed)["passed"])
        self.assertFalse(compare_audits({}, {})["passed"])
        changed=copy.deepcopy(audit)
        changed["total_mass_xyz_kg"][2]+=1
        self.assertFalse(compare_audits(audit,changed)["passed"])

    def test_load_control_rejects_invalid_target_order(self):
        self.assertEqual(validate_speeds([20,30,40,60,80]),(20.,30.,40.,60.,80.))
        for values in ([],[20,20],[30,20],[0,20],[math.inf],[math.nan]):
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_speeds(values)

    def test_resume_preserves_complete_and_partial_evidence(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            case=root/"runs/tmq_0"
            case.mkdir(parents=True)
            for status,expected in (("complete",0),("partial",2)):
                evidence=json.dumps({"status":status,"stop_reason":"timeout" if status=="partial" else None})
                (case/"summary.json").write_text(evidence)
                with patch("subprocess.run") as launch:
                    result=execute_case(root,0,"tmq",{})
                launch.assert_not_called()
                self.assertEqual(result["returncode"],expected)
                self.assertEqual((case/"summary.json").read_text(),evidence)

    def test_retry_selection_must_stay_inside_owned_run_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            key="steel02_four_segments_30"
            (root/"case_selections.json").write_text(json.dumps({key:{"selected_directory":f"runs/{key}_budget_retry"}}))
            self.assertEqual(case_directory(root,"steel02_four_segments",30),root/"runs"/f"{key}_budget_retry")
            (root/"case_selections.json").write_text(json.dumps({key:{"selected_directory":"../../outside"}}))
            with self.assertRaises(ValueError):
                case_directory(root,"steel02_four_segments",30)

    def test_completed_summary_does_not_free_slot_before_process_exit(self):
        from unittest.mock import patch
        module="initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            case=root/"runs/tmq_0"
            case.mkdir(parents=True)
            (case/"summary.json").write_text(json.dumps({"status":"complete"}))
            with patch(module+".existing_worker",side_effect=[12345,None]) as process,patch(module+".time.sleep") as sleep:
                result=execute_case(root,0,"tmq",{})
            self.assertEqual(process.call_count,2)
            sleep.assert_called_once_with(1)
            self.assertEqual(result["observed_existing_pid"],12345)
            self.assertEqual(result["returncode"],0)

    def test_observer_tolerates_half_written_legacy_summary(self):
        from unittest.mock import patch
        module="initial_imperfection_material.tian_ma_qu.single_tower_wind_comparison"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            case=root/"runs/tmq_0"
            case.mkdir(parents=True)
            (case/"summary.json").write_text(json.dumps({"status":"complete"}))
            error=json.JSONDecodeError("partial legacy write","",0)
            with patch(module+".json.loads",side_effect=[error,{"status":"complete"}]),patch(module+".existing_worker",side_effect=[12345,None]),patch(module+".time.sleep"):
                result=execute_case(root,0,"tmq",{})
            self.assertEqual(result["returncode"],0)
            self.assertEqual(result["observed_existing_pid"],12345)

    def test_real_s2k_both_model_adapters_use_exact_same_physical_wind_geometry(self):
        # No FE construction/analysis: checks the actual differently namespaced
        # model parsers used by the two schemes, rather than a duplicated fixture.
        from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
        from model.tower_model_with_buckling import OpenSeesModelWithBuckling
        from util.processing.tower_directional_wind import geometry_from_model, PROXY_AREA_BASIS
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            tmq=OpenSeesModelWithTianMaQu(ROOT/"Source/Z30103A6.s2k",output_dir=path/"tmq")
            steel=OpenSeesModelWithBuckling(ROOT/"Source/Z30103A6.s2k",output_dir=path/"steel",member_divisions=4,imperfection_seed=30103,random_disp_ratio=.001)
            options=dict(area_basis=PROXY_AREA_BASIS,area_provenance="same-source comparison test")
            first,second=(geometry_from_model(m,**options) for m in (tmq,steel))
            self.assertEqual(first,second)
            self.assertEqual(len(first.nodes),621)
            self.assertEqual(len(first.members),1528)


if __name__ == "__main__":
    unittest.main()
