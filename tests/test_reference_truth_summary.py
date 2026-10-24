import csv
import json
from pathlib import Path
import tempfile
import unittest

from initial_imperfection_material.summarize_member_states import summarize


class ReferenceTruthSummaryTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'reference'
        source.mkdir()
        history = source / 'member_states.jsonl'
        (source / 'run_manifest.json').write_text(json.dumps({'status': 'completed', 'run_id': 'fixture'}))
        metadata = {
            'node_coordinates': {'1': [0, 0, 0], '2': [.5, .001, 0], '3': [1, 0, 0]},
            'material_parameters': {'1': {'fy': 235e6, 'e0': 210e9}},
            'members': {'7': [{'node_j': 2, 'mat_tag': 1}, {'node_j': 3, 'mat_tag': 1}]},
        }
        history.with_suffix('.metadata.json').write_text(json.dumps(metadata))
        section = {'fiber_status': 'available', 'max_abs_stress': {'stress': -240e6},
                   'max_abs_strain': {'strain': -.002}}
        end_force = [0.] * 12
        end_force[6] = -100.
        row = {'committed': True, 'accepted_step': 0, 'source_step': 0,
               'stage_id': 'target_1', 'stage_progress': 1,
               'node_displacements': {str(tag): [0.] * 6 for tag in (1, 2, 3)},
               'members': [{'original_member_id': 7, 'node_i': 1, 'node_j': 3,
                            'initial_chord_m': 1., 'current_chord_m': .999, 'chord_strain': -.001,
                            'segments': [{'global_force': end_force, 'sections': [section]},
                                         {'global_force': end_force, 'sections': [section]}]}]}
        history.write_text(json.dumps(row) + '\n')
        return history, row

    def test_nominal_markers_and_original_axis_projection_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history, _ = self.fixture(root)
            result = summarize(history, root / 'summary')
            member = result['members'][0]
            self.assertEqual(member['maximum_compression_N'], 100.)
            self.assertAlmostEqual(member['maximum_bow_m'], .001)
            self.assertEqual(len(result['events']), 2)
            self.assertFalse(result['reference_mesh_converged'])
            self.assertTrue(all('not_a_unique_Steel02_plastic_yield_state' in event['interpretation']
                                for event in result['events']))
            with (root / 'summary/member_7_reference.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(float(rows[0]['original_axis_N']), -100.)
            self.assertTrue((root / 'summary/local_reference_response.png').is_file())
            with self.assertRaises(FileExistsError):
                summarize(history, root / 'summary')

    def test_unfinished_parent_cannot_generate_final_truth_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history, _ = self.fixture(root)
            history.with_name('run_manifest.json').write_text(json.dumps({'status': 'running'}))
            with self.assertRaisesRegex(ValueError, 'completed run'):
                summarize(history, root / 'summary')
            self.assertFalse((root / 'summary').exists())

    def test_missing_fibers_and_trial_rows_are_not_silently_accepted(self):
        for case in ('fiber', 'trial'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                history, row = self.fixture(root)
                if case == 'trial':
                    row['committed'] = False
                else:
                    row['members'][0]['segments'][0]['sections'][0]['fiber_status'] = 'unavailable'
                history.write_text(json.dumps(row) + '\n')
                with self.assertRaises(ValueError):
                    summarize(history, root / 'summary')
                self.assertFalse((root / 'summary').exists())


if __name__ == '__main__':
    unittest.main()
