import tempfile
import unittest
from pathlib import Path

from initial_imperfection_material.experiment import run_experiment
from initial_imperfection_material.material import (
    EquivalentImperfectionMaterial,
    MemberProperties,
    ec3_reduction_factor,
    gb50017_reduction_factor,
)


class EquivalentImperfectionMaterialTests(unittest.TestCase):
    def test_z30103a6_member_properties(self) -> None:
        member = MemberProperties.z30103a6_l125x8(length=3.0)
        self.assertAlmostEqual(member.area, 0.001936)
        self.assertAlmostEqual(member.inertia_weak, 1.1939431019283698e-6)
        self.assertAlmostEqual(member.euler_load, 269716.8550276843, places=3)
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
        self.assertAlmostEqual(gb50017_reduction_factor(slenderness, "a"), 0.3539865, places=6)
        self.assertAlmostEqual(ec3_reduction_factor(slenderness, 0.34), 0.3164886, places=6)

    def test_short_experiment_writes_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_experiment(
                directory,
                maximum_strain=0.01,
                steps=80,
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
            ):
                self.assertTrue((output / filename).is_file(), filename)
            error = summary["metrics"]["equivalent_calibrated"]["normalized_rmse_percent"]
            self.assertLess(error, 8.0)


if __name__ == "__main__":
    unittest.main()
