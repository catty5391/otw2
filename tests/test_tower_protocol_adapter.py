import unittest

from initial_imperfection_material.compare_runs import (
    compare_protocol_histories, normalize_tower_cyclic_history,
)


class TowerProtocolAdapterTests(unittest.TestCase):
    def fixture(self):
        return [
            {'stage': 'gravity', 'relative_displacement': 0, 'base_shear': 0},
            {'stage': 'target_1_+0.001000', 'target_displacement': 1., 'relative_displacement': .5, 'base_shear': 5},
            {'stage': 'target_1_+0.001000', 'target_displacement': 1., 'relative_displacement': 1., 'base_shear': 10},
            {'stage': 'target_2_-0.001000', 'target_displacement': -1., 'relative_displacement': 0., 'base_shear': 0},
            {'stage': 'target_2_-0.001000', 'target_displacement': -1., 'relative_displacement': -1., 'base_shear': -10},
        ]

    def test_reversal_and_stage_start_are_preserved(self):
        normalized = normalize_tower_cyclic_history(self.fixture(), [1., -1.])
        self.assertEqual([r['u_m'] for r in normalized], [0, .5, 1, 1, 0, -1])
        self.assertEqual(normalized[3]['direction'], -1)
        self.assertEqual(normalized[3]['stage_progress'], 0)
        result = compare_protocol_histories(normalized, normalized, protocol_stages=[('1', 1), ('2', -1)])
        self.assertEqual(result['reference_protocol_coverage_percent'], 100.)
        self.assertEqual(result['metrics']['base_shear']['rmse'], 0.)

    def test_missing_targets_do_not_receive_invented_rows(self):
        normalized = normalize_tower_cyclic_history(self.fixture()[:3], [1., -1.])
        result = compare_protocol_histories(normalized, normalized, protocol_stages=[('1', 1), ('2', -1)])
        self.assertEqual(result['reference_protocol_coverage_percent'], 50.)
        self.assertEqual(result['stages'][1]['reason'], 'stage_missing_in_both')

    def test_protocol_mismatch_and_unknown_stage_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'declared protocol'):
            normalize_tower_cyclic_history(self.fixture(), [2., -1.])
        rows = self.fixture()
        rows[1]['stage'] = 'unlabeled'
        with self.assertRaisesRegex(ValueError, 'unexpected tower stage'):
            normalize_tower_cyclic_history(rows, [1., -1.])
        with self.assertRaisesRegex(ValueError, 'gravity endpoint'):
            normalize_tower_cyclic_history(self.fixture()[1:], [1., -1.])


if __name__ == '__main__':
    unittest.main()
