import tempfile
import unittest
from pathlib import Path

import numpy as np

from initial_imperfection_material.tian_ma_qu.damping_audit import (
    equal_target_coefficients, spectrum, source_audit, run,
)


class DampingAuditTests(unittest.TestCase):
    def test_anchor_fit_and_unit_sensitivity(self):
        alpha, beta = equal_target_coefficients(.2, 2.5, .01)
        np.testing.assert_allclose(spectrum([.2, 2.5], alpha, beta), [.01, .01], rtol=1e-12)
        a2, b2 = equal_target_coefficients(2., 25., .01)
        self.assertAlmostEqual(a2 / alpha, 10.)
        self.assertAlmostEqual(b2 / beta, .1)

    def test_sdof_complex_poles_recover_candidate_damping(self):
        alpha, beta = equal_target_coefficients(.2, 2.5, .01)
        # Independent first-order state eigenvalues of three analytic oscillators.
        for f in [.2, .7, 2.5]:
            w = 2 * np.pi * f
            c = alpha + beta * w*w
            poles = np.linalg.eigvals([[0., 1.], [-w*w, -c]])
            measured = -poles[0].real / abs(poles[0])
            self.assertAlmostEqual(measured, float(spectrum([f], alpha, beta)[0]), places=12)

    def test_counterexample_and_tower_anchor_low_frequency_penalty(self):
        a, b = equal_target_coefficients(.195, .19501, .01)
        self.assertGreater(spectrum([2.5], a, b)[0], .06)
        a, b = equal_target_coefficients(2.1, 2.5, .01)
        self.assertGreater(spectrum([.195], a, b)[0], .05)

    def test_bad_inputs_and_identical_anchors_rejected(self):
        for args in [(0, 2, .01), (1, 1, .01), (1, 2, float("nan")), (1, -2, .01)]:
            with self.assertRaises(ValueError): equal_target_coefficients(*args)
        for fs in [[], [0], [float("inf")], [[1, 2]]]:
            with self.assertRaises(ValueError): spectrum(fs, .1, .01)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keep"; p.write_text("preserve")
            with self.assertRaises(FileExistsError): run(d)
            self.assertEqual(p.read_text(), "preserve")

    def test_source_coverage_does_not_claim_runtime_validation(self):
        audit = source_audit()
        lines = [r for r in audit["calls"] if r.get("first_argument") in {"corotTruss", "corotTrussSection"}]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(not r["explicit_doRayleigh"] for r in lines))
        self.assertFalse(audit["runtime_verified"])
        self.assertTrue(any(r["first_argument"] == "Plain" for r in audit["calls"]))


if __name__ == "__main__": unittest.main()
