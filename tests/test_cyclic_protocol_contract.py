"""Synthetic protocol contracts only; no OpenSees or physical reference results."""

import copy
import json
import math
import unittest

from initial_imperfection_material.cyclic_protocol_contract import (
    DEFAULT_PACKAGE, BINDINGS_SCHEMA, ProtocolContractError, ReferenceNotReadyError,
    fingerprint, resolve_case, validate_package, validate_usage,
)


class CyclicProtocolContractTests(unittest.TestCase):
    def setUp(self):
        self.package = json.loads(DEFAULT_PACKAGE.read_text())
        self.c1 = "q235_l40_0850_c1_train"

    def bindings(self):
        bindings = {"schema": BINDINGS_SCHEMA, "package_sha256": fingerprint(self.package),
            "evidence": {"fixture": {"source": "fixture://synthetic-not-physical-validation", "sha256": "a" * 64}},
            "gates": {"G1": {"status": "passed", "evidence_ids": ["fixture"]},
                      "T09": {"status": "completed", "evidence_ids": ["fixture"]}},
            "references": {}, "histories": {}, "usage": {"fit_case_ids": [], "model_selection_case_ids": [], "response_fingerprints": []}}
        values = {"elastic_compression_small": (.0001, .05), "elastic_tension_small": (-.0001, .05),
                  "compression_far_low": (.0002, .2), "compression_far_high": (.0004, .4),
                  "compression_near_peak": (.001, .9), "compression_postpeak": (.002, 1.2), "tension_reversal": (-.001, 1.1)}
        for reference_id, declared in self.package["amplitude_references"].items():
            anchors = {}
            for key, (displacement, ratio) in values.items():
                anchors[key] = {"committed": True, "observation_kind": self.package["anchor_definitions"][key]["observation_kind"],
                    "end_shortening_m": displacement, "max_abs_fiber_stress_over_fy": ratio,
                    "evidence_ids": ["fixture"], "after_observed_peak": key == "compression_postpeak"}
            bindings["references"][reference_id] = {
                "group_id": declared["group_id"], "boundary_id": declared["boundary_id"], "material_model": declared["material_model"],
                "completed": True, "mesh_and_fiber_accepted": True, "control_quantity": "end_shortening_m",
                "accepted_control_range_m": [-.002, .003], "evidence_ids": ["fixture"], "anchors": anchors,
                "fiber_coverage": "all_declared_sections_and_fibers",
                "first_nominal_fy_crossing": {"criterion": "first_committed_max_abs_sigma_over_fy_ge_1", "observed": True,
                    "end_shortening_m": .0015, "max_abs_fiber_stress_over_fy": 1.0, "evidence_ids": ["fixture"]},
            }
        return bindings

    def reference(self, bindings):
        return bindings["references"]["q235_l40_0850_steel02"]

    def test_package_is_pre_frozen_16_cases_and_two_actual_groups(self):
        result = validate_package(self.package)
        self.assertEqual(result["cases"], 16)
        self.assertEqual(result["split_counts"], {"diagnostic": 4, "training": 8, "holdout": 4})
        self.assertEqual({group["length_m"] for group in self.package["groups"].values()}, {.85, 1.95})
        self.assertEqual(result["resolved_cases"], 0)
        self.assertFalse(result["physical_validation_passed"])

    def test_pending_template_cannot_unlock_actual_amplitudes(self):
        template = json.loads(DEFAULT_PACKAGE.with_name("t10_reference_bindings_template.json").read_text())
        self.assertEqual(template["package_sha256"], fingerprint(self.package))
        with self.assertRaisesRegex(ReferenceNotReadyError, "G1"):
            resolve_case(self.package, self.c1, template)

    def test_package_change_invalidates_reference_binding(self):
        bindings = self.bindings()
        self.package["version"] = 2
        with self.assertRaisesRegex(ReferenceNotReadyError, "package hash"):
            resolve_case(self.package, self.c1, bindings)

    def test_c1_uses_measured_fiber_margin_and_preserves_three_cycles_per_level(self):
        bindings = self.bindings()
        before = copy.deepcopy(bindings)
        result = resolve_case(self.package, self.c1, bindings)
        self.assertEqual(result["targets_m"], [0, .0002, 0, .0002, 0, .0002, 0, .0004, 0, .0004, 0, .0004, 0])
        self.assertFalse(result["physical_validation_passed"])
        self.assertFalse(result["analysis_executed"])
        self.assertEqual(result["preyield_reversibility"], "to_measure_not_assumed")
        self.assertEqual(bindings, before)

    def test_raw_equivalent_strain_target_rejected(self):
        case = next(case for case in self.package["cases"] if case["case_id"] == self.c1)
        case["targets"][1] = {"equivalent_strain": -.0005}
        with self.assertRaisesRegex(ProtocolContractError, "measured anchors"):
            validate_package(self.package)

    def test_c0_requires_pure_elastic_steel(self):
        self.package["cases"][0]["reference_material"] = "Steel02"
        with self.assertRaisesRegex(ProtocolContractError, "pure Elastic"):
            validate_package(self.package)

    def test_nominal_yield_crossing_must_be_declared_from_reference_fibers(self):
        bindings = self.bindings()
        self.reference(bindings).pop("first_nominal_fy_crossing")
        with self.assertRaisesRegex(ReferenceNotReadyError, "nominal fiber fy"):
            resolve_case(self.package, self.c1, bindings)
        bindings = self.bindings()
        self.reference(bindings)["first_nominal_fy_crossing"]["max_abs_fiber_stress_over_fy"] = .99
        with self.assertRaisesRegex(ProtocolContractError, "contradicts"):
            resolve_case(self.package, self.c1, bindings)

    def test_far_from_yield_guard_is_not_an_equivalent_strain_threshold(self):
        bindings = self.bindings()
        self.reference(bindings)["anchors"]["compression_far_high"]["max_abs_fiber_stress_over_fy"] = .51
        with self.assertRaisesRegex(ProtocolContractError, "fiber state.*margin"):
            resolve_case(self.package, self.c1, bindings)

    def test_postpeak_requires_observed_peak_evidence(self):
        bindings = self.bindings()
        self.reference(bindings)["anchors"]["compression_postpeak"]["after_observed_peak"] = False
        with self.assertRaisesRegex(ReferenceNotReadyError, "observed reference peak"):
            resolve_case(self.package, "q235_l40_0850_c3_train", bindings)

    def test_no_extrapolation_nonfinite_uncommitted_or_wrong_boundary(self):
        for field, value in (("end_shortening_m", .03), ("end_shortening_m", math.nan), ("committed", False)):
            bindings = self.bindings()
            self.reference(bindings)["anchors"]["compression_far_high"][field] = value
            with self.assertRaises((ProtocolContractError, ValueError)):
                resolve_case(self.package, self.c1, bindings)
        bindings = self.bindings()
        self.reference(bindings)["boundary_id"] = "tower_6dof_replay"
        with self.assertRaisesRegex(ProtocolContractError, "boundary_id"):
            resolve_case(self.package, self.c1, bindings)

    def test_holdout_cannot_be_used_for_fit_or_model_selection(self):
        holdout = "q235_l40_0850_c6_sequence_holdout"
        with self.assertRaises(ProtocolContractError):
            validate_usage(self.package, fit_case_ids=[holdout])
        with self.assertRaises(ProtocolContractError):
            validate_usage(self.package, model_selection_case_ids=[holdout])
        validate_usage(self.package, fit_case_ids=[self.c1])

    def test_aliasing_response_hash_cannot_hide_training_holdout_leakage(self):
        with self.assertRaisesRegex(ProtocolContractError, "identical response"):
            validate_usage(self.package, response_fingerprints=[
                {"case_id": self.c1, "sha256": "b" * 64},
                {"case_id": "q235_l40_0850_c6_sequence_holdout", "sha256": "b" * 64},
            ])

    def test_seen_diagnostic_source_cannot_be_relabelled_holdout(self):
        source = self.package["response_sources"]["response_q235_l40_0850_c5_future_holdout"]
        source["previously_used_for_diagnosis"] = True
        with self.assertRaisesRegex(ProtocolContractError, "seen diagnostic"):
            validate_package(self.package)

    def test_missing_reference_fingerprints_do_not_pass(self):
        bindings = self.bindings()
        bindings["evidence"]["fixture"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ReferenceNotReadyError, "fingerprint"):
            resolve_case(self.package, self.c1, bindings)

    def test_full_six_dof_holdout_needs_gravity_and_independent_future_path(self):
        case_id = "q235_l40_0850_c5_future_holdout"
        bindings = self.bindings()
        history = {"group_id": "q235_l40_0850", "member_id": 878,
            "completed": True, "includes_initial_unloaded_state": True, "includes_gravity": True,
            "both_end_6dof": True, "committed_only": True,
            "path": "fixture://future-held-out-6dof", "sha256": "c" * 64,
            "evidence_ids": ["fixture"], "used_for_parameter_fit": False, "independent_future_path": True}
        bindings["histories"]["response_" + case_id] = history
        result = resolve_case(self.package, case_id, bindings)
        self.assertEqual(result["history"]["member_id"], 878)
        self.assertNotIn("targets_m", result)
        history["includes_gravity"] = False
        with self.assertRaisesRegex(ReferenceNotReadyError, "gravity"):
            resolve_case(self.package, case_id, bindings)
        history["includes_gravity"] = True
        history["used_for_parameter_fit"] = True
        with self.assertRaisesRegex(ProtocolContractError, "unused for fitting"):
            resolve_case(self.package, case_id, bindings)

    def test_complete_fiber_coverage_and_boolean_completion_are_required(self):
        bindings = self.bindings()
        self.reference(bindings)["fiber_coverage"] = "one_selected_fiber"
        with self.assertRaisesRegex(ReferenceNotReadyError, "complete reference fiber coverage"):
            resolve_case(self.package, self.c1, bindings)
        bindings = self.bindings()
        self.reference(bindings)["completed"] = "yes"
        with self.assertRaises(ReferenceNotReadyError):
            resolve_case(self.package, self.c1, bindings)


if __name__ == "__main__":
    unittest.main()
