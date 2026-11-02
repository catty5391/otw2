"""Synthetic fixtures exercise admission logic; no physical validation claim."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.parameter_identification import response, ordered_data
from initial_imperfection_material.tian_ma_qu.grouped_identification import (
    CHECKS, admission_reasons, require_admitted, require_excitation, stage_residual, fit_group,
)
from initial_imperfection_material.tian_ma_qu.ordered_history_study import read_curve, candidate_group, audit_specimen
from py_view.results_dashboard.server import DashboardData, TMQ_ORDERED_ROOT

ROOT = Path(__file__).resolve().parents[1]


def fixture(specimen="unit_test_training", final=-.007):
    """Artificial example with asserted checks ONLY for unit testing the contract."""
    p = literature_cases()[0].parameters
    strains = [0.]
    phases = ["first_compression"]
    for target, phase in [(-.005, "first_compression"), (.025, "unload_reload"), (final, "subsequent_compression")]:
        strains.extend(np.linspace(strains[-1], target, 121)[1:])
        phases.extend([phase]*120)
    force = response(p, strains)*.002
    ver = {key: {"status": "verified", "source_reference": "UNIT TEST ARTIFICIAL EVIDENCE; not a real experiment"} for key in CHECKS}
    for key in ("E", "fy"):
        ver[key]["basis"] = "measured_coupon"
    ver["order"]["basis"] = "instrument_sequence"
    ver["geometry"]["basis"] = "measured_specimen"
    manifest = {"schema": "otw2.tmq_ordered_history.v1", "data_kind": "experiment",
        "source": "Artificial fixture that exercises an experimental admission contract ONLY",
        "ordered": True, "ordering_evidence": "fixture construction", "specimen_id": specimen,
        "geometry_basis": "unit-test values", "material_property_basis": "unit-test values",
        "elastic_modulus_Pa": p.elastic_modulus, "yield_stress_Pa": p.yield_stress,
        "length_m": 1., "area_m2": .002, "initial_state": "virgin_zero_load",
        "units": {"displacement": "m", "force": "N", "sign": "tension_positive"},
        "verification": ver, "group_key": "unit_test_only", "force_resolution_N": 1.,
        "samples": [{"sequence": i, "displacement": float(e), "force": float(f), "segment": phase, "phase": phase}
                    for i, (e, f, phase) in enumerate(zip(strains, force, phases))]}
    return p, manifest


def plan():
    return [{"name": name, "bounds": [{"name": coefficient, "lower": low, "upper": high}]}
            for name, coefficient, low, high in (("first_compression", "phi", .6, .9),
                ("unload_reload", "tau", 1.1, 1.8), ("subsequent_compression", "eta", .35, .75))]


class GroupedIdentificationTests(unittest.TestCase):
    def setUp(self):
        self.p, self.m = fixture()

    def test_missing_measured_E_and_unreviewed_order_cannot_enter_fit(self):
        for key, field, value in (("E", "basis", "database_unspecified"), ("fy", "status", "unverified"),
                                  ("order", "basis", "unordered_scan"), ("initial_state", "status", "unknown")):
            m = copy.deepcopy(self.m); m["verification"][key][field] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_admitted(m)
        self.assertEqual(admission_reasons(self.m), [])

    def test_nonzero_start_or_shuffled_sample_order_rejected(self):
        for field, value in (("force", 17840.), ("displacement", .0005)):
            m = copy.deepcopy(self.m); m["samples"][0][field] = value
            with self.assertRaises(ValueError): require_admitted(m)
        m = copy.deepcopy(self.m); m["samples"].reverse()
        with self.assertRaises(ValueError): require_admitted(m)

    def test_elastic_only_data_cannot_identify_postbuckling(self):
        m = copy.deepcopy(self.m)
        for i, row in enumerate(m["samples"]):
            row.update(displacement=-i*1e-7, force=-i*1e-7*self.p.elastic_modulus*m["area_m2"], phase="first_compression")
        with self.assertRaisesRegex(ValueError, "peak|Elastic"):
            require_excitation(require_admitted(m), "first_compression", ["alpha"])

    def test_displacement_reversal_is_not_sorted_into_compression_branch(self):
        m = copy.deepcopy(self.m); m["samples"][5]["displacement"] = .0001
        with self.assertRaisesRegex(ValueError, "contiguous"):
            require_excitation(require_admitted(m), "first_compression", ["phi"])

    def test_later_stage_replays_prior_history_before_masking(self):
        d = require_admitted(self.m)
        mask = require_excitation(d, "subsequent_compression", ["eta"])
        np.testing.assert_allclose(stage_residual(self.p, d, mask), 0., atol=1e-14)
        restarted = response(self.p, d["strain"][mask])*d["area_m2"]
        self.assertGreater(np.max(abs(restarted-d["force_N"][mask])), 1e3)

    def test_physical_properties_and_prior_stages_cannot_be_optimized(self):
        _, h = fixture("unit_test_holdout", -.009)
        for coefficient in ("elastic_modulus", "yield_stress", "rho", "eta"):
            stages = plan(); stages[0]["bounds"][0]["name"] = coefficient
            with self.subTest(coefficient=coefficient), self.assertRaises(ValueError):
                fit_group([self.m], [h], self.p, stages)
        with self.assertRaisesRegex(ValueError, "E/fy"):
            fit_group([self.m], [h], replace(self.p, elastic_modulus=210e9), plan())

    def test_no_train_holdout_leak_or_pooling_different_geometry(self):
        with self.assertRaisesRegex(ValueError, "leakage"):
            fit_group([self.m], [self.m], self.p, plan())
        _, h = fixture("unit_test_holdout"); h["length_m"] = 2.
        with self.assertRaisesRegex(ValueError, "Group"):
            fit_group([self.m], [h], self.p, plan())

    def test_stage_order_and_missing_later_phase_fail_before_GA(self):
        _, h = fixture("unit_test_holdout")
        with self.assertRaisesRegex(ValueError, "order"):
            fit_group([self.m], [h], self.p, list(reversed(plan())))
        m = copy.deepcopy(self.m)
        for row in m["samples"]:
            if row["phase"] == "subsequent_compression": row["phase"] = "unknown"
        with self.assertRaisesRegex(ValueError, "six"):
            fit_group([m], [h], self.p, plan())

    def test_staged_synthetic_recovery_freezes_E_fy_and_does_not_claim_validation(self):
        _, h = fixture("unit_test_holdout", -.009)
        result = fit_group([self.m], [h], replace(self.p, phi=.65, tau=1.2, eta=.4), plan(),
            seeds=(17,), population=8, generations=3, timeout_seconds=20.)
        self.assertEqual(result["status"], "candidate_evaluated_not_automatically_validated")
        self.assertEqual(result["best_parameters"]["elastic_modulus"], self.p.elastic_modulus)
        self.assertEqual(result["best_parameters"]["yield_stress"], self.p.yield_stress)
        for name in ("phi", "tau", "eta"):
            self.assertAlmostEqual(result["best_parameters"][name], getattr(self.p, name), places=4)
        self.assertLess(result["scores"][1]["full_history_nrmse"], 1e-5)
        self.assertFalse(result["full_hysteresis_validation"])
        self.assertFalse(result["production_parameters_changed"])

    def test_unexcited_repeat_coefficient_is_not_returned_as_determined(self):
        # A reversal before tensile yield retraces this prototype's prior branch;
        # eta has no influence. An apparent later compression peak is insufficient.
        p, m = fixture()
        for row in m["samples"]:
            if row["phase"] == "unload_reload":
                row["displacement"] = -.005 + (row["displacement"]+.005)*(.013/.030)
            elif row["phase"] == "subsequent_compression":
                row["displacement"] = .008 + (row["displacement"]-.025)*(.015/.032)
        f = response(p, [r["displacement"] for r in m["samples"]])*.002
        for row, force in zip(m["samples"], f): row["force"] = float(force)
        h = copy.deepcopy(m); h["specimen_id"] = "holdout"
        result = fit_group([m], [h], p, plan(), seeds=(17,), population=8, generations=2)
        self.assertEqual(result["status"], "nonidentifiable_stage")
        self.assertEqual(result["stages"][-1]["stage"], "subsequent_compression")
        self.assertNotIn("best_parameters", result)

    def test_holdout_observations_cannot_change_optimized_coefficients(self):
        _, h = fixture("unit_test_holdout", -.009)
        options = dict(seeds=(17,), population=8, generations=2)
        a = fit_group([self.m], [h], self.p, plan(), **options)
        for row in h["samples"]: row["force"] *= .8
        b = fit_group([self.m], [h], self.p, plan(), **options)
        self.assertEqual(a["best_parameters"], b["best_parameters"])
        self.assertGreater(b["scores"][1]["full_history_nrmse"], a["scores"][1]["full_history_nrmse"])


class SourceHistoryTests(unittest.TestCase):
    def test_csv_preserves_offsets_duplicate_displacements_and_reversals(self):
        a = read_curve(b"Displacement [mm],Force [kN]\n0.5,17.8\n-1,-5\n-1,3\n2,10\n")
        np.testing.assert_array_equal(a, [[.5,17.8],[-1,-5],[-1,3],[2,10]])
        for payload in (b"u,f\n0,0\n1,1\n2,2", b"Displacement [mm],Force [kN]\n0,0\n1,nan\n2,2"):
            with self.assertRaises(ValueError): read_curve(payload)

    def test_catalog_groups_do_not_silently_merge_lengths_or_boundary_conditions(self):
        row = dict(cross_section_size="L25x25x6", l_b=1000, area=282, fy_m=365, e=200000,
                   boundary_condition="gusset", steel="M1020")
        for key, value in (("l_b", 1200), ("boundary_condition", "fixed"), ("area", 280)):
            other = {**row, key: value}
            self.assertNotEqual(candidate_group(row), candidate_group(other))

    def test_source_audit_never_promotes_metadata_or_global_peak_to_calibration(self):
        row = dict(id="test", cross_section_size="L37.7x37.7x3.18", l_b=1295, area=273, fy_m=352,
            e=200000, boundary_condition="Gusset plate", kl_r=120, k_assumed=.7,
            loading_protocol="Asymmetric", b_br=37.7, d_br=37.7, t_br=3.18)
        a = audit_specimen(row, b"Displacement [mm],Force [kN]\n.5,17.8\n-1,-5\n2,20\n")
        self.assertFalse(a["strict_fit_admitted"])
        self.assertTrue(a["geometry_review_flag"])
        self.assertIsNone(a["fitted_parameters"])
        self.assertTrue(a["force_extrema_are_not_first_buckling_features"])
        self.assertFalse(a["sort_applied"])
        self.assertFalse(a["normalization_applied"])


class OrderedPublicationTests(unittest.TestCase):
    def test_missing_and_unknown_publication_do_not_gain_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DashboardData(directory)
            self.assertIsNone(data.tian_ma_qu()["ordered_history"])
            path = data.tmq_root/TMQ_ORDERED_ROOT/"summary.json"
            path.parent.mkdir(parents=True); path.write_text('{"schema":"unknown"}')
            with self.assertRaises(ValueError): data.tian_ma_qu()

    @unittest.skipUnless((ROOT/"literature/tmq_ordered_history_20261026/raw/braces.json").exists(),
                         "Downloaded raw research data is intentionally local")
    def test_published_samples_exactly_preserve_downloaded_rows_and_offsets(self):
        data = DashboardData(ROOT)
        publication = data.tian_ma_qu()["ordered_history"]
        self.assertEqual(publication["curve_count"], 7)
        self.assertEqual(publication["strict_fit_admitted_count"], 0)
        self.assertFalse(publication["real_history_fit_executed"])
        root = data.tmq_root/TMQ_ORDERED_ROOT
        summary = json.loads((root/"summary.json").read_text())
        histories = json.loads((root/"curves.json").read_text())["curves"]
        audit = {a["specimen_id"]: a for a in summary["specimens"]}
        for h in histories:
            raw = (ROOT/"literature/tmq_ordered_history_20261026/raw"/(h["id"]+".csv")).read_bytes()
            np.testing.assert_array_equal(read_curve(raw), h["samples"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), audit[h["id"]]["source_sha256"])
        self.assertEqual(sum(len(h["samples"]) for h in histories), summary["point_count"])
        self.assertIsNotNone(data.tmq_file(f"{TMQ_ORDERED_ROOT}/curves.json"))
        self.assertIsNone(data.tmq_file(f"{TMQ_ORDERED_ROOT}/../raw/braces.json"))
        self.assertIsNone(data.tmq_file("grouped_identification.py"))


if __name__ == "__main__":
    unittest.main()
