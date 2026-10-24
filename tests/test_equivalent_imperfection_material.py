import tempfile
import unittest
from pathlib import Path

from initial_imperfection_material.experiment import (
    extract_actual_section_lengths,
    run_experiment,
)
from initial_imperfection_material.material import (
    EquivalentImperfectionMaterial,
    MemberProperties,
    ec3_reduction_factor,
    gb50017_reduction_factor,
)


class EquivalentImperfectionMaterialTests(unittest.TestCase):
    def test_section_registration_scales_stress_to_axial_force(self) -> None:
        class FakeOps:
            def __init__(self) -> None:
                self.arguments = None

            def uniaxialMaterial(self, *arguments) -> None:
                self.arguments = arguments

        member = MemberProperties.z30103a6_l125x8(length=2.0)
        material = EquivalentImperfectionMaterial.from_perry(member)
        fake = FakeOps()
        material.register_opensees(
            fake,
            7,
            response_mode="reversible",
            stress_scale=member.area,
        )
        self.assertEqual(fake.arguments[0:3], ("ElasticMultiLinear", 7, "-strain"))
        stress_index = fake.arguments.index("-stress")
        registered_forces = fake.arguments[stress_index + 1 :]
        self.assertAlmostEqual(
            max(abs(value) for value in registered_forces),
            max(
                material.peak_compressive_load,
                max(abs(point.stress) * member.area for point in material.tension_envelope()),
            ),
            delta=1.0,
        )

    def test_z30103a6_member_properties(self) -> None:
        member = MemberProperties.z30103a6_l125x8(length=3.0)
        self.assertAlmostEqual(member.area, 0.001936)
        self.assertAlmostEqual(member.inertia_weak, 1.1939431019283698e-6)
        self.assertAlmostEqual(member.elastic_modulus, 210e9)
        self.assertAlmostEqual(member.steel_hardening_ratio, 0.03)
        self.assertAlmostEqual(member.euler_load, 274954.0755136583, places=3)
        self.assertGreater(member.squash_load, member.euler_load)

    def test_larger_imperfection_reduces_perry_capacity(self) -> None:
        member = MemberProperties.z30103a6_l125x8(length=3.0)
        small = EquivalentImperfectionMaterial.from_perry(
            member, imperfection_ratio=1.0 / 2000.0
        )
        large = EquivalentImperfectionMaterial.from_perry(
            member, imperfection_ratio=1.0 / 250.0
        )
        self.assertGreater(small.peak_compressive_load, large.peak_compressive_load)
        strains = [point.strain for point in small.compression_envelope]
        self.assertTrue(all(right < left for left, right in zip(strains, strains[1:])))

    def test_standard_reduction_factors(self) -> None:
        slenderness = MemberProperties.z30103a6_l125x8().non_dimensional_slenderness
        self.assertAlmostEqual(gb50017_reduction_factor(slenderness, "a"), 0.3600341, places=6)
        self.assertAlmostEqual(ec3_reduction_factor(slenderness, 0.34), 0.3215391, places=6)

    def test_short_experiment_writes_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_experiment(
                directory,
                maximum_strain=0.01,
                steps=80,
                reference_divisions=4,
                run_convergence=False,
                run_actual_validation=False,
            )
            output = Path(directory)
            for filename in (
                "pushover_curves.csv",
                "material_backbones.csv",
                "summary.json",
                "pushover_comparison.png",
                "normalized_pushover.png",
                "material_backbones.png",
                "imperfection_sensitivity.png",
                "pre_yield_unloading.csv",
                "pre_yield_unloading.png",
                "actual_l125x8_members.csv",
            ):
                self.assertTrue((output / filename).is_file(), filename)
            error = summary["metrics"]["equivalent_calibrated"]["normalized_rmse_percent"]
            self.assertLess(error, 8.0)
            self.assertTrue(summary["pre_yield_unloading"]["passed"])
            self.assertAlmostEqual(
                summary["pre_yield_unloading"]["equivalent_final_force"],
                0.0,
                places=6,
            )
            self.assertGreater(
                abs(summary["pre_yield_unloading"]["legacy_hysteretic_final_force"]),
                1000.0,
            )

    def test_actual_l125x8_members_are_extracted(self) -> None:
        source = Path(__file__).resolve().parents[1] / "Source" / "Z30103A6.s2k"
        rows = extract_actual_section_lengths(source, "L125x8Q345")
        lengths = [float(row["length"]) for row in rows]
        self.assertEqual(len(rows), 112)
        self.assertAlmostEqual(min(lengths), 1.43955600502377)
        self.assertAlmostEqual(max(lengths), 2.41362797464729)


if __name__ == "__main__":
    unittest.main()
