"""Numerical and mechanical invariants, not experimental validation of TMQ."""

from dataclasses import replace
import math
import unittest

from initial_imperfection_material.tian_ma_qu import TMQParameters, TianMaQuPrototype


def parameters() -> TMQParameters:
    # First P102 table row; E/rho/gamma/zeta are explicitly demonstration choices.
    return TMQParameters(
        elastic_modulus=206e9, yield_stress=327.28e6, phi=0.797,
        rho=0.005, alpha=0.506, beta=0.020, gamma=0.5,
        tau=1.449, mu=0.474, nu=1.549, zeta=0.2,
        eta=0.544, theta=0.020, kappa=0.0044,
        provenance="test: published table row plus explicit unverified E/rho/gamma/zeta",
    )


def move(material: TianMaQuPrototype, target: float, steps: int = 1) -> list[dict]:
    start = material.get_strain()
    results = []
    for index in range(1, steps + 1):
        material.set_trial_strain(start + (target - start) * index / steps)
        results.append(material.get_state())
        material.commit_state()
    return results


class TianMaQuMaterialTests(unittest.TestCase):
    def test_invalid_parameters_and_nonfinite_trial_fail_without_mutating_state(self):
        for field, value in (("phi", 1.1), ("gamma", 1), ("mu", 2),
                             ("rho", -0.1), ("beta", 0), ("tau", math.nan)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(parameters(), **{field: value})
        material = TianMaQuPrototype(parameters())
        material.set_trial_strain(0.0001)
        before = material.get_state()
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                material.set_trial_strain(value)
            self.assertEqual(before, material.get_state())

    def test_virgin_elastic_small_cycles_return_zero_without_residual_or_work(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        for target in (0.2, -0.4, 0.3, -0.2, 0):
            move(material, target * p.yield_strain, 13)
            self.assertAlmostEqual(material.get_stress(), p.elastic_modulus * material.get_strain(), delta=1e-6)
        state = material.get_state()
        self.assertEqual(state["buckling_count"], 0)
        self.assertAlmostEqual(state["stress"], 0, delta=1e-7)
        self.assertAlmostEqual(state["external_work_density"], 0, delta=1e-7)

    def test_initial_tension_matches_independent_bilinear_equation(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        for factor in (0.3, 1, 1.3, 4):
            strain = factor * p.yield_strain
            material.set_trial_strain(strain)
            expected = p.elastic_modulus * strain if factor <= 1 else (
                p.yield_stress + p.rho * p.elastic_modulus * (strain - p.yield_strain)
            )
            self.assertAlmostEqual(material.get_stress(), expected, delta=1e-6)
            material.commit_state()

    def test_tensile_unloading_has_elastic_slope_and_expected_residual(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        move(material, 1.2 * p.yield_strain)
        e_b, s_b = material.get_strain(), material.get_stress()
        zero = e_b - s_b / p.elastic_modulus
        move(material, zero, 7)
        self.assertAlmostEqual(material.get_stress(), 0, delta=1e-6)
        self.assertAlmostEqual(material.get_tangent(), p.elastic_modulus)
        self.assertEqual(material.get_state()["buckling_count"], 0)

    def test_touching_elastic_limits_and_reversing_does_not_create_residual(self):
        p = parameters()
        for limit in (p.yield_strain, p.first_buckling_stress / p.elastic_modulus):
            material = TianMaQuPrototype(p)
            move(material, limit)
            # At a corner the tangent is the outgoing loading tangent; this
            # alone must not commit a finite plastic/buckled excursion.
            expected_tangent = p.rho * p.elastic_modulus if limit > 0 else -p.alpha * p.elastic_modulus
            self.assertEqual(material.get_tangent(), expected_tangent)
            self.assertEqual(material.get_state()["buckling_count"], 0)
            move(material, limit / 2)
            self.assertAlmostEqual(material.get_tangent(), p.elastic_modulus)
            move(material, 0)
            self.assertAlmostEqual(material.get_stress(), 0, delta=1e-6)
            self.assertAlmostEqual(material.get_state()["external_work_density"], 0, delta=1e-6)

    def test_crossing_compression_limit_by_a_finite_amount_activates_softening(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        peak_strain = p.first_buckling_stress / p.elastic_modulus
        move(material, peak_strain)
        self.assertEqual(material.get_state()["buckling_count"], 0)
        move(material, peak_strain - 1e-8)
        self.assertEqual(material.get_state()["buckling_count"], 1)
        before = material.get_state()
        move(material, material.get_strain() + 1e-10)
        self.assertEqual(material.get_state()["stage"], "compression_unloading")
        self.assertLess(abs(material.get_stress() - before["stress"]), p.elastic_modulus * 1e-9)

    def test_first_compression_corners_and_slopes_match_equation_3(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        peak = -p.phi * p.yield_stress
        e_c = peak / p.elastic_modulus
        e_d = e_c + ((p.gamma - 1) * peak) / (-p.alpha * p.elastic_modulus)
        samples = (
            (e_c, peak, -p.alpha * p.elastic_modulus),
            ((e_c + e_d) / 2, (peak + p.gamma * peak) / 2, -p.alpha * p.elastic_modulus),
            (e_d - 0.2 * p.yield_strain,
             p.gamma * peak + (-p.beta * p.elastic_modulus) * (-0.2 * p.yield_strain),
             -p.beta * p.elastic_modulus),
        )
        for strain, stress, tangent in samples:
            material.set_trial_strain(strain)
            self.assertAlmostEqual(material.get_stress(), stress, delta=1e-6)
            self.assertAlmostEqual(material.get_tangent(), tangent, delta=1e-3)
            material.commit_state()
        self.assertEqual(material.get_state()["buckling_count"], 1)

    def test_single_large_increment_visits_all_corners_and_integrates_work(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        final = -4 * p.yield_strain
        material.set_trial_strain(final)
        events = material.get_state()["events"]
        self.assertEqual(sum(event["event"] == "buckling" for event in events), 1)
        self.assertGreaterEqual(sum(event["event"] == "corner" for event in events), 2)
        peak = p.first_buckling_stress
        e_c = peak / p.elastic_modulus
        e_d = e_c + (p.gamma * peak - peak) / (-p.alpha * p.elastic_modulus)
        last_stress = p.gamma * peak - p.beta * p.elastic_modulus * (final - e_d)
        expected_work = (0.5 * peak * e_c
                         + 0.5 * (peak + p.gamma * peak) * (e_d - e_c)
                         + 0.5 * (p.gamma * peak + last_stress) * (final - e_d))
        self.assertAlmostEqual(material.get_state()["external_work_density"], expected_work, delta=1e-7)

    def test_reloading_uses_historical_extrema_secant_and_three_exact_slopes(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        move(material, 2 * p.yield_strain)
        e_b, s_b = material.get_strain(), material.get_stress()
        move(material, -3 * p.yield_strain)
        e_f, s_f = material.get_strain(), material.get_stress()
        secant = (s_b - s_f) / (e_b - e_f)
        e_g = e_f - s_f / (p.tau * secant)
        e_h = e_g + p.zeta * p.yield_stress / (p.mu * secant)
        e_i = e_h + (1 - p.zeta) * p.yield_stress / (p.nu * secant)
        for strain, stress, tangent in (
            ((e_f + e_g) / 2, s_f / 2, p.tau * secant),
            ((e_g + e_h) / 2, p.zeta * p.yield_stress / 2, p.mu * secant),
            ((e_h + e_i) / 2, (1 + p.zeta) * p.yield_stress / 2, p.nu * secant),
            (e_i + p.yield_strain, p.yield_stress * (1 + p.rho), p.rho * p.elastic_modulus),
        ):
            move(material, strain)
            self.assertAlmostEqual(material.get_stress(), stress, delta=1e-6)
            self.assertAlmostEqual(material.get_tangent(), tangent, delta=1e-4)

    def test_second_peak_reduces_by_eta_without_unpublished_exponential_damage(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        peaks = []
        for high, low in ((2, -3), (5, -6), (8, -10)):
            move(material, high * p.yield_strain, 20)
            rows = move(material, low * p.yield_strain, 20)
            peaks.extend(event["stress"] for row in rows for event in row["events"]
                         if event["event"] == "buckling")
        self.assertEqual(len(peaks), 3)
        self.assertAlmostEqual(peaks[0], p.first_buckling_stress)
        self.assertAlmostEqual(peaks[1], p.eta * peaks[0])
        self.assertAlmostEqual(peaks[2], peaks[1])

    def test_subsequent_compression_reaches_kappa_segment_continuously(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        for target in (2, -4, 6):
            move(material, target * p.yield_strain)
        self.assertEqual(material.get_state()["stage"], "tension_hardening")
        peak = p.eta * p.first_buckling_stress
        e_k = material.get_strain() + (peak - material.get_stress()) / p.elastic_modulus
        e_l = e_k + (p.gamma * peak - peak) / (-p.theta * p.elastic_modulus)
        target = e_l - 0.3 * p.yield_strain
        expected = p.gamma * peak - p.kappa * p.elastic_modulus * (target - e_l)
        move(material, target)
        self.assertEqual(material.get_state()["stage"], "subsequent_compression_softening_2")
        self.assertAlmostEqual(material.get_stress(), expected, delta=1e-6)
        self.assertEqual(material.get_tangent(), -p.kappa * p.elastic_modulus)
        self.assertEqual(material.get_state()["buckling_count"], 2)

    def test_repeated_trial_commit_revert_and_copy_are_independent(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        move(material, 2 * p.yield_strain)
        committed = material.get_state()
        material.set_trial_strain(-4 * p.yield_strain)
        trial = material.get_state()
        material.set_trial_strain(-4 * p.yield_strain)
        self.assertEqual(trial, material.get_state())
        other = material.get_copy()
        other.commit_state()
        other.set_trial_strain(4 * p.yield_strain)
        self.assertEqual(trial, material.get_state())
        material.revert_to_last_commit()
        self.assertEqual(committed, material.get_state())
        material.set_trial_strain(2.1 * p.yield_strain)
        self.assertEqual(material.get_state()["buckling_count"], 0)
        material.revert_to_start()
        self.assertEqual(material.get_stress(), 0)
        self.assertEqual(material.get_state()["external_work_density"], 0)

    def test_minor_reversal_closes_and_restores_parent_branch(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        move(material, 2 * p.yield_strain)
        move(material, -3 * p.yield_strain)
        compression = material.get_copy()
        start = material.get_state()
        move(material, -1.5 * p.yield_strain)
        move(material, -3 * p.yield_strain)
        self.assertAlmostEqual(material.get_stress(), start["stress"], delta=1e-6)
        self.assertAlmostEqual(material.get_state()["external_work_density"], start["external_work_density"], delta=1e-6)
        move(material, -4 * p.yield_strain)
        move(compression, -4 * p.yield_strain)
        self.assertAlmostEqual(material.get_stress(), compression.get_stress(), delta=1e-6)
        self.assertEqual(material.get_state()["buckling_count"], 1)

    def test_finite_difference_tangent_on_each_smooth_branch(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        checked = set()
        for target in (2, -4, 6, -10, 8):
            start = material.get_strain()
            for index in range(1, 151):
                strain = start + (target * p.yield_strain - start) * index / 150
                # Both perturbations start from identical committed history.
                material.set_trial_strain(strain)
                center = material.get_state()
                if center["events"]:
                    material.commit_state()
                    continue
                h = 1e-9
                material.set_trial_strain(strain + h)
                upper = material.get_stress()
                upper_stage = material.get_state()["stage"]
                material.set_trial_strain(strain - h)
                lower = material.get_stress()
                lower_stage = material.get_state()["stage"]
                material.set_trial_strain(strain)
                if upper_stage != lower_stage:
                    # A central difference at a corner averages its two slopes.
                    material.commit_state()
                    continue
                finite_difference = (upper - lower) / (2 * h)
                self.assertAlmostEqual(finite_difference / p.elastic_modulus,
                                       center["tangent"] / p.elastic_modulus, delta=1e-8)
                checked.add(center["stage"])
                material.commit_state()
        self.assertTrue({"elastic", "tension_hardening", "first_compression_softening_1",
                         "first_compression_softening_2", "compression_unloading",
                         "tension_pinching", "tension_reloading",
                         "subsequent_compression_softening_1"}.issubset(checked), checked)

    def test_step_refinement_preserves_complete_history_and_exact_work(self):
        p = parameters()
        targets = [0.2, -0.3, 0, 2, -4, 5, -8, 8, -12, 9, 0]
        outputs = []
        for divisions in (1, 10, 100):
            material = TianMaQuPrototype(p)
            checkpoints = []
            for target in targets:
                move(material, target * p.yield_strain, divisions)
                checkpoints.append(material.get_state())
            outputs.append(checkpoints)
        for coarse, middle, fine in zip(*outputs):
            for key in ("stress", "tangent", "external_work_density",
                        "min_strain", "max_strain"):
                scale = max(1, abs(fine[key]))
                self.assertAlmostEqual(coarse[key] / scale, fine[key] / scale, delta=1e-11)
                self.assertAlmostEqual(middle[key] / scale, fine[key] / scale, delta=1e-11)
            self.assertEqual(coarse["buckling_count"], fine["buckling_count"])

    def test_reversal_stress_continuity_and_finite_complete_loop(self):
        p = parameters()
        material = TianMaQuPrototype(p)
        stages = set()
        for target in (2, -4, 5, -8, 8, -12, 9, 0):
            start = material.get_state()
            direction = 1 if target * p.yield_strain > start["strain"] else -1
            material.set_trial_strain(start["strain"] + direction * 1e-12)
            self.assertLess(abs(material.get_stress() - start["stress"]), p.elastic_modulus * 2e-12)
            material.revert_to_last_commit()
            for state in move(material, target * p.yield_strain, 50):
                stages.add(state["stage"])
                for key in ("strain", "stress", "tangent", "external_work_density"):
                    self.assertTrue(math.isfinite(state[key]))
        self.assertGreater(material.get_state()["external_work_density"], 0)
        self.assertGreaterEqual(material.get_state()["buckling_count"], 3)
        self.assertIn("tension_pinching", stages)
        self.assertFalse(material.get_state()["damage_model_enabled"])

    def test_explicit_compression_tail_never_turns_into_tensile_resistance(self):
        for residual in (0.0, 0.02):
            p = replace(parameters(), residual_compression_ratio=residual)
            material = TianMaQuPrototype(p)
            move(material, -0.2)
            self.assertEqual(material.get_state()["stage"], "compression_tail_extension")
            self.assertLessEqual(material.get_stress(), 0)
            self.assertAlmostEqual(material.get_stress(), residual * p.first_buckling_stress)
            self.assertEqual(material.get_tangent(), 0)


if __name__ == "__main__":
    unittest.main()
