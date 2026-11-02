"""Trust boundaries of the tower-line model comparison (no heavy FE reruns)."""
import math
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.tian_ma_qu.tower_line_wind_comparison import (
    canonical_ledger, common_target_rows, digest, finalize_interrupted_case,
)


def state(speed, *, local=True, global_balance=True):
    return {"wind_speed_m_s": speed, "equilibrium_passed": local,
            "global_balance_passed": global_balance}


class TowerLineWindComparisonTests(unittest.TestCase):
    def test_semantic_ledger_ignores_allocator_but_detects_force_change(self):
        first = canonical_ledger({7: (1., 2., 3., 0., 0., 0.)},
                                 {7: dict(x=2., y=0., z=30.)}, {7: "line:west:3"})
        renumbered = canonical_ledger({900: (1., 2., 3., 0., 0., 0.)},
                                      {900: dict(x=2., y=0., z=30.)}, {900: "line:west:3"})
        changed = canonical_ledger({900: (1., 2., 3.001, 0., 0., 0.)},
                                   {900: dict(x=2., y=0., z=30.)}, {900: "line:west:3"})
        self.assertEqual(first, renumbered)
        self.assertEqual(digest(first), digest(renumbered))
        self.assertNotEqual(digest(first), digest(changed))

    def test_semantic_ledger_rejects_missing_ambiguous_and_invalid_inputs(self):
        for identities, loads in (
            ({}, {7: (0.,)*6}),
            ({7: "same", 8: "same"}, {7: (0.,)*6}),
            ({7: "line:a:1"}, {7: (math.nan, 0., 0., 0., 0., 0.)}),
            ({7: "line:a:1"}, {7: (0.,)*3}),
        ):
            with self.subTest(identities=identities, loads=loads), self.assertRaises(ValueError):
                canonical_ledger(loads, {7: dict(x=0., y=0., z=0.)}, identities)

    def test_comparison_does_not_extrapolate_or_accept_failed_committed_states(self):
        reference = [state(20.), state(30.), state(40., local=False), state(60.)]
        candidate = [state(20.), state(30., global_balance=False), state(40.), state(55.)]
        paired = common_target_rows(reference, candidate)
        self.assertEqual([speed for speed, _, _ in paired], [20.])

    def test_target_pairing_tolerates_float_roundoff_without_interpolating(self):
        paired = common_target_rows([state(30.)], [state(29.999999999999996)])
        self.assertEqual(len(paired), 1)
        self.assertEqual(common_target_rows([state(30.)], [state(29.999)]), [])

    def test_budget_stop_recovers_only_complete_saved_states_and_preserves_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            initial={"status":"hard_timeout", "completed_targets_m_s":[20.,30.,40.],
                     "last_point":{"wind_speed_m_s":40.}, "accepted_steps":9}
            (p/"summary.json").write_text(json.dumps(initial))
            a={"step":9,"wind_speed_m_s":40.,"equilibrium_passed":True,"global_balance_passed":True,
               "axial_assumption_guard_passed":True,"force_residual_N":.0001,
               "global_force_balance_max_N":.00001,"global_moment_balance_max_Nm":.00002}
            b={**a,"step":16,"wind_speed_m_s":54.7722557505,"axial_assumption_guard_passed":False}
            raw=json.dumps(a)+"\n"+json.dumps(b)+'\n{"step":17'
            (p/"states.jsonl").write_text(raw)
            (p/"history.csv").write_text(",".join(a)+"\n")
            result=finalize_interrupted_case(p)
            self.assertEqual(result["last_point"]["wind_speed_m_s"],b["wind_speed_m_s"])
            self.assertEqual(result["accepted_steps"],16)
            self.assertEqual(result["completed_targets_m_s"],[20.,30.,40.])
            self.assertEqual(result["first_axial_assumption_guard_failure"]["step"],16)
            self.assertEqual((p/"states.jsonl").read_text(),raw)
            self.assertEqual(json.loads((p/"summary_at_supervisor_stop.json").read_text()),initial)
            self.assertEqual(finalize_interrupted_case(p),result)


if __name__ == "__main__":
    unittest.main()
