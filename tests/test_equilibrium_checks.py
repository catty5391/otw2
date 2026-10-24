from __future__ import annotations

import math
import unittest

import openseespy.opensees as ops

from util.analysis.equilibrium_checks import CommittedStateRejected, dynamic_equilibrium, require_equilibrium, static_equilibrium
from util.postprocess.energy import conjugate_external_work


class EquilibriumTests(unittest.TestCase):
    def tearDown(self):
        ops.wipe()

    def springs(self):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        for node in (1, 2, 3):
            ops.node(node, node - 1.)
        ops.fix(1, 1)
        ops.uniaxialMaterial("Elastic", 1, 1000.)
        ops.element("truss", 1, 1, 2, 1., 1)
        ops.element("truss", 2, 2, 3, 1., 1)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.)
        ops.load(3, 20.)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.)
        ops.analysis("Static")
        self.assertEqual(ops.analyze(1), 0)

    def test_real_two_springs_balance_excludes_support_and_does_not_modify_state(self):
        self.springs()
        before = (ops.getTime(), tuple(ops.nodeDisp(2)), tuple(ops.nodeDisp(3)), tuple(ops.eleForce(1)))
        result = static_equilibrium(ops, {(2, 1): 10., (3, 1): 20.}, constrained_dofs={(1, 1)}, force_scale=30.)
        self.assertTrue(result["passed"])
        self.assertEqual(result["translation"]["count"], 2)
        self.assertLess(result["translation"]["maximum_absolute"], 1e-10)
        self.assertEqual(before, (ops.getTime(), tuple(ops.nodeDisp(2)), tuple(ops.nodeDisp(3)), tuple(ops.eleForce(1))))
        # A nonzero nodeUnbalance here is a real applied load, not a residual.
        self.assertAlmostEqual(ops.nodeUnbalance(3, 1), 20.)

    def test_small_displacement_cannot_hide_a_wrong_force_ledger(self):
        self.springs()
        result = static_equilibrium(ops, {(2, 1): 10., (3, 1): 19.}, constrained_dofs={(1, 1)})
        self.assertFalse(result["passed"])
        self.assertAlmostEqual(result["translation"]["maximum_absolute"], 1.)
        position = ops.nodeDisp(3, 1)
        with self.assertRaises(CommittedStateRejected) as error:
            require_equilibrium(result)
        self.assertIs(error.exception.report, result)
        self.assertEqual(ops.nodeDisp(3, 1), position)

    def test_real_frame_groups_moments_and_forces_separately(self):
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0., 0.)
        ops.node(2, 2., 0.)
        ops.fix(1, 1, 1, 1)
        ops.geomTransf("Linear", 1)
        ops.element("elasticBeamColumn", 1, 1, 2, 2., 2000., 3., 1)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 12., -8., 5.)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.)
        ops.analysis("Static")
        self.assertEqual(ops.analyze(1), 0)
        result = static_equilibrium(ops, {(2, 1): 12., (2, 2): -8., (2, 3): 5.},
                                    constrained_dofs={(1, 1), (1, 2), (1, 3)},
                                    rotational_dofs={(1, 3), (2, 3)}, force_scale=12., moment_scale=5.)
        self.assertTrue(result["passed"])
        self.assertEqual(result["translation"]["unit"], "N")
        self.assertEqual(result["rotation"]["unit"], "N m")
        self.assertEqual(result["rotation"]["count"], 1)

    def test_softening_spring_series_has_real_free_dof_balance(self):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        for node in (1, 2, 3):
            ops.node(node, node - 1.)
        ops.fix(1, 1)
        ops.uniaxialMaterial("Elastic", 1, 1000.)
        ops.uniaxialMaterial("ElasticMultiLinear", 2, "-strain", -1., 0., .02, .04, .2,
                             "-stress", -1000., 0., 20., 10., 10.)
        ops.element("truss", 1, 1, 2, 1., 1)
        ops.element("truss", 2, 2, 3, 1., 2)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(3, 1.)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 30)
        ops.algorithm("Newton")
        ops.integrator("DisplacementControl", 3, 1, .001)
        ops.analysis("Static")
        peaks = []
        for _ in range(49):
            self.assertEqual(ops.analyze(1), 0)
            result = static_equilibrium(ops, {(3, 1): ops.getLoadFactor(1)}, constrained_dofs={(1, 1)}, force_scale=20.)
            self.assertTrue(result["passed"])
            peaks.append(ops.getLoadFactor(1))
        self.assertLess(peaks[-1], max(peaks))
        self.assertAlmostEqual(ops.nodeDisp(3, 1), .049)

    def test_unsupported_element_layout_is_rejected(self):
        class Domain:
            getNodeTags = lambda self: [1, 2]
            nodeDisp = lambda self, node: [0.]
            getEleTags = lambda self: [1]
            eleNodes = lambda self, ele: [1, 2]
            eleForce = lambda self, ele: [1.]
        with self.assertRaisesRegex(ValueError, "adapter required"):
            static_equilibrium(Domain(), {}, constrained_dofs={(1, 1)})

    def test_rigid_translation_does_not_create_element_residual(self):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        for node in (1, 2, 3):
            ops.node(node, node - 1.)
        ops.uniaxialMaterial("Elastic", 1, 1000.)
        ops.element("truss", 1, 1, 2, 1., 1)
        ops.element("truss", 2, 2, 3, 1., 1)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.sp(1, 1, 10.)
        ops.sp(3, 1, 10.)
        ops.constraints("Transformation")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.)
        ops.analysis("Static")
        self.assertEqual(ops.analyze(1), 0)
        self.assertAlmostEqual(ops.nodeDisp(2, 1), 10.)
        self.assertTrue(static_equilibrium(ops, {}, constrained_dofs={(1, 1), (3, 1)})["passed"])
        self.assertAlmostEqual(ops.eleForce(1)[0], 0.)

    def test_mp_constraints_require_an_adapter_instead_of_false_balance(self):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        ops.node(1, 0.)
        ops.node(2, 1.)
        ops.equalDOF(1, 2, 1)
        with self.assertRaisesRegex(NotImplementedError, "MP constraints"):
            static_equilibrium(ops, {}, constrained_dofs=())


class ConjugateWorkTests(unittest.TestCase):
    def test_distributed_force_work_differs_from_base_shear_top_displacement(self):
        result = conjugate_external_work([
            {"displacements": {"n2x": 0., "n3x": 0.}, "external_forces": {"n2x": 0., "n3x": 0.}},
            {"displacements": {"n2x": .03, "n3x": .05}, "external_forces": {"n2x": 10., "n3x": 20.}},
        ], all_applied_dofs_included=True)
        self.assertAlmostEqual(result["signed_external_work"], .65)
        self.assertNotAlmostEqual(result["signed_external_work"], .5 * 30 * .05)

    def test_moment_gravity_and_moving_constraint_work_are_included(self):
        result = conjugate_external_work([
            {"displacements": {"rotation": 0., "gravity": 0., "support": 0.},
             "external_forces": {"rotation": 0., "gravity": -10., "support": 3.}},
            {"displacements": {"rotation": .1, "gravity": -.2, "support": .2},
             "external_forces": {"rotation": 4., "gravity": -10., "support": 3.}},
        ], all_applied_dofs_included=True, constraint_work_included=True)
        self.assertAlmostEqual(result["signed_external_work"], .2 + 2. + .6)
        self.assertTrue(result["constraint_work_included"])

    def test_closed_elastic_path_has_zero_work_but_does_not_claim_internal_closure(self):
        result = conjugate_external_work([
            {"displacements": {"x": x}, "external_forces": {"x": 2 * x}}
            for x in (0., 1., .5, 0.)])
        self.assertAlmostEqual(result["signed_external_work"], 0.)
        self.assertTrue(result["endpoint_force_displacement_closed"])
        self.assertFalse(result["internal_state_closure_verified"])
        self.assertFalse(result["all_applied_dofs_included"])

    def test_trial_missing_channel_and_nonfinite_work_are_rejected(self):
        start = {"displacements": {"x": 0.}, "external_forces": {"x": 0.}}
        for end in ({**start, "accepted": False}, {**start, "committed": False},
                    {"displacements": {"x": 1.}, "external_forces": {}},
                    {"displacements": {"x": float("nan")}, "external_forces": {"x": 1.}}):
            with self.subTest(end=end), self.assertRaises(ValueError):
                conjugate_external_work([start, end])


class DynamicEquilibriumTests(unittest.TestCase):
    def tearDown(self):
        ops.wipe()

    def oscillator(self, damping=0.):
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)
        ops.node(1, 0.)
        ops.node(2, 0.)
        ops.fix(1, 1)
        ops.mass(2, 2.)
        ops.uniaxialMaterial("Elastic", 1, 200.)
        ops.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 1.)
        ops.rayleigh(damping / 2., 0., 0., 0.)
        ops.constraints("Plain")
        ops.numberer("Plain")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1e-12, 20)
        ops.algorithm("Newton")
        ops.integrator("Newmark", .5, .25)
        ops.analysis("Transient")
        ops.setNodeAccel(2, 1, .5, "-commit")

    def check_oscillator(self, damping):
        self.oscillator(damping)
        residuals = []
        for _ in range(100):
            self.assertEqual(ops.analyze(1, .001), 0)
            before = (ops.getTime(), ops.nodeDisp(2, 1), ops.nodeVel(2, 1), ops.nodeAccel(2, 1))
            report = dynamic_equilibrium(ops, {(2, 1): 1.},
                inertial_nodal_forces={(1, 1): 0., (2, 1): 2. * ops.nodeAccel(2, 1)},
                damping_nodal_forces={(1, 1): 0., (2, 1): damping * ops.nodeVel(2, 1)},
                mass_model="nodal_diagonal_only", constrained_dofs={(1, 1)}, force_scale=1.,
                force_provenance={"inertia": "node2 diagonal mass 2 kg * committed acceleration",
                                  "damping": f"known mass-proportional Rayleigh C={damping} N s/m"})
            self.assertTrue(report["passed"])
            self.assertTrue(report["dynamic_terms_included"])
            self.assertEqual(before, (ops.getTime(), ops.nodeDisp(2, 1), ops.nodeVel(2, 1), ops.nodeAccel(2, 1)))
            residuals.append(report["translation"]["maximum_absolute"])
        zeta, omega, time = damping / 40., 10., .1
        omega_d = omega * math.sqrt(1 - zeta * zeta)
        expected = (1 - math.exp(-zeta * omega * time) * (math.cos(omega_d * time) +
                    zeta / math.sqrt(1-zeta*zeta) * math.sin(omega_d * time))) / 200.
        self.assertAlmostEqual(ops.nodeDisp(2, 1), expected, delta=5e-8)
        self.assertLess(max(residuals), 1e-9)

    def test_constant_load_newmark_oscillator_has_true_inertial_balance(self):
        self.check_oscillator(0.)

    def test_known_viscous_coefficient_has_true_damped_balance(self):
        self.check_oscillator(4.)

    def test_missing_unknown_or_incomplete_dynamic_ledger_fails_closed(self):
        self.oscillator()
        complete = {(1, 1): 0., (2, 1): 0.}
        provenance = {"inertia": "explicit known mass", "damping": "explicit known zero damping"}
        cases = [dict(), dict(inertial_nodal_forces=complete, damping_nodal_forces=complete),
                 dict(inertial_nodal_forces=complete, damping_nodal_forces=complete,
                      mass_model="unknown_element_consistent_mass", force_provenance=provenance),
                 dict(inertial_nodal_forces={(2, 1): 0.}, damping_nodal_forces=complete,
                      mass_model="nodal_diagonal_only", force_provenance=provenance)]
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                dynamic_equilibrium(ops, {(2, 1): 1.}, constrained_dofs={(1, 1)}, **settings)

    def test_omitted_inertia_is_detected_even_after_analyze_succeeds(self):
        self.oscillator()
        self.assertEqual(ops.analyze(1, .001), 0)
        report = dynamic_equilibrium(ops, {(2, 1): 1.},
            inertial_nodal_forces={(1, 1): 0., (2, 1): 0.},
            damping_nodal_forces={(1, 1): 0., (2, 1): 0.}, mass_model="nodal_diagonal_only",
            force_provenance={"inertia": "deliberately incorrect zero inertia fixture", "damping": "zero"},
            constrained_dofs={(1, 1)}, force_scale=1.)
        self.assertFalse(report["passed"])
        self.assertGreater(report["translation"]["maximum_absolute"], .9)


if __name__ == "__main__":
    unittest.main()
