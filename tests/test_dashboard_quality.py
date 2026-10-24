import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.server import API_SCHEMA, DashboardData, create_server
from util.analysis.result_quality import MemberDomainRange, ResultQuality


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DashboardQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DashboardData(PROJECT_ROOT)

    def test_historical_completion_and_validation_remain_independent(self):
        cases = {item['id']: item for item in self.data.diagnostic_cases()['cases']}
        self.assertEqual(cases['baseline']['quality']['execution_status'], 'nonconverged')
        self.assertEqual(cases['baseline']['summary']['completed_targets'], 6)
        fine = cases['fine_sparse']['quality']
        self.assertEqual(fine['execution_status'], 'completed')
        self.assertEqual(fine['validation_status'], 'failed')
        self.assertEqual(fine['domain_status'], 'out_of_range')
        self.assertFalse(fine['eligible_for_fragility'])
        self.assertEqual(fine['first_out_of_domain_by_member']['877']['accepted_step'], 499)
        self.assertEqual(fine['first_out_of_domain_by_member']['878']['stage_id'], '8')
        self.assertEqual(cases['elastic_877_878']['quality']['purpose'], 'diagnostic')
        self.assertIn('diagnostic_material_substitution', cases['elastic_877_878']['quality']['quality_flags'])

    def test_historical_manifest_stays_quarantined_and_fair_speedup_unknown(self):
        result = self.data.overview()
        self.assertEqual(result['api_schema'], API_SCHEMA)
        self.assertIsNone(result['tower']['speedup'])
        self.assertFalse(result['tower']['runtime_comparison_valid'])
        self.assertNotIn('3.7.1.2', result['project']['analysis_engine'])
        fine = next(item for item in result['diagnostics']['cases'] if item['id'] == 'fine_sparse')
        self.assertEqual(fine['historical_manifest_quality']['validation_status'], 'legacy_unknown')

    def test_member_detail_preserves_order_units_and_reference_scope(self):
        result = self.data.diagnostic_member('fine_sparse', 877)
        self.assertEqual(len(result['points']), 591)
        self.assertEqual(result['points'][0]['step'], 0)
        self.assertEqual(result['points'][-1]['step'], 590)
        self.assertEqual(result['metadata']['section_name'], 'L40x3Q235')
        self.assertFalse(result['deformation_animation_available'])
        self.assertLess(result['same_stage_reference_checkpoints'][0]['compression_magnitude_difference_percent'], -78)
        with self.assertRaises(ValueError):
            self.data.diagnostic_member('../full_tower_cyclic', 877)
        with self.assertRaises(ValueError):
            self.data.diagnostic_member('fine_sparse', 1)

    def test_absent_data_returns_unknown_not_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DashboardData(directory)
            result = data.overview()
            self.assertFalse(result['tower']['available'])
            self.assertFalse(result['member']['available'])
            self.assertEqual(result['project']['analysis_engine'], 'unknown')
            self.assertEqual(data.followup_runs()['count'], 0)
            self.assertEqual(data.resources()['reports'], [])
            self.assertTrue(all(not item['available'] for item in result['diagnostics']['cases']))
            self.assertTrue(all(not item['quality']['eligible_for_fragility'] for item in result['diagnostics']['cases']))

    def test_new_followup_legacy_manifest_cannot_claim_validity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'initial_imperfection_material/results/followup/batch/case/run_manifest.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'status':'completed', 'eligible_for_fragility': True}))
            result = DashboardData(directory).followup_runs()
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['runs'][0]['quality']['validation_status'], 'legacy_unknown')
            self.assertFalse(result['runs'][0]['quality']['eligible_for_fragility'])

    def test_local_comparison_does_not_fail_merely_because_rows_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diagnosis = root / 'initial_imperfection_material/results/convergence_diagnosis'
            (diagnosis / 'baseline').mkdir(parents=True)
            (diagnosis / 'baseline/summary.json').write_text(json.dumps({'converged':True, 'requested_targets':1, 'completed_targets':1}))
            (diagnosis / 'evidence.json').write_text(json.dumps({'member_comparison_at_negative_0_6_percent':[
                {'element':877, 'compression_magnitude_difference_percent':0.0}]}))
            profile = root / 'docs/ai_execution_plan/execution_20261022/acceptance_profile.json'
            profile.parent.mkdir(parents=True)
            profile.write_text(json.dumps({'tower_critical_force_relative':0.1}))
            case = DashboardData(root).diagnostic_cases()['cases'][0]
            self.assertEqual(case['quality']['validation_status'], 'unvalidated')
            self.assertNotIn('local_response_mismatch', case['quality']['quality_flags'])

    def test_fixed_download_and_asset_paths_reject_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            target = Path(outside) / 'secret.pdf'
            target.write_text('outside project')
            folder = root / 'literature/transmission_tower_wind/papers'
            folder.mkdir(parents=True)
            (folder / 'escaped.pdf').symlink_to(target)
            data = DashboardData(root)
            self.assertIsNone(data.downloadable('paper:escaped.pdf'))
            self.assertIsNone(data.downloadable('paper:../secret.pdf'))
            self.assertIsNone(data.downloadable('../../secret.pdf'))
            self.assertIsNone(data.asset('../../secret.pdf'))

    def test_sqlite_connector_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'read_only.sqlite'
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE evidence (id INTEGER)')
            with self.data._connect_read_only(path) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute('INSERT INTO evidence VALUES (1)')


class DashboardHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server('127.0.0.1', 0, project_root=PROJECT_ROOT)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get_json(self, path):
        with self.opener.open(self.base + path, timeout=30) as response:
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            result = json.load(response)
            self.assertEqual(result['api_schema'], API_SCHEMA)
            return result

    def test_new_api_live_http_and_static_entry(self):
        result = self.get_json('/api/diagnostics')
        self.assertEqual(len(result['cases']), 3)
        self.assertEqual(len(self.get_json('/api/diagnostics/curve?case=fine_sparse')['series']), 591)
        self.assertEqual(self.get_json('/api/diagnostics/member?case=fine_sparse&member=878')['member'], 878)
        self.assertIn('runs', self.get_json('/api/followup'))
        with self.opener.open(self.base + '/', timeout=10) as response:
            html = response.read().decode()
            self.assertIn('diagnosticCases', html)
            self.assertNotIn('共同验证区间', html)

    def test_query_allowlists_and_nonfinite_values(self):
        for path in ('/api/diagnostics/curve?case=../../secret',
                     '/api/diagnostics/member?case=fine_sparse&member=1',
                     '/api/internal-force/meta?model=../secret',
                     '/api/internal-force/snapshot?time=NaN',
                     '/api/internal-force/envelope?start=Infinity',
                     '/api/internal-force/snapshot?component=p_i%3BDROP'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.opener.open(self.base + path, timeout=10)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        for path in ('/download?key=../../pyproject.toml', '/static/../server.py', '/asset/../../server.py'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.opener.open(self.base + path, timeout=10)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        with self.assertRaises(HTTPError) as caught:
            self.opener.open(self.base + '/api/unknown-endpoint', timeout=10)
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(json.load(caught.exception)['api_schema'], API_SCHEMA)
        caught.exception.close()


class DashboardSummaryPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.manifest = cls.root / 'initial_imperfection_material/results/followup/batch/full_tower/run_manifest.json'
        cls.manifest.parent.mkdir(parents=True)
        quality = ResultQuality(purpose='diagnostic', domain_policy='diagnostic_continue')
        quality.add_evidence('domain', 'actual_member_calibration.json')
        quality.add_evidence('history', 'committed_member_states.jsonl')
        quality.set_execution('completed')
        quality.set_coverage(9, 9)
        quality.set_validation('unvalidated', flags=['legacy_unknown', 'local_response_mismatch', 'custom_review_flag'])
        for member in range(1, 1529):
            quality.register_domain(MemberDomainRange(member, 'strain', 0.0, 1.0, ('domain',)))
            quality.observe_member_state(member, 'strain', 0.5, accepted_step=0, evidence_ids=['history'])
            quality.observe_member_state(member, 'strain', 1.5, accepted_step=1, evidence_ids=['history'])
            quality.observe_member_state(member, 'strain', 1.6, accepted_step=2, evidence_ids=['history'])
        cls.full_quality = quality.to_dict()
        cls.original = json.dumps({'status':'completed', 'quality':cls.full_quality}).encode()
        cls.manifest.write_bytes(cls.original)
        cls.data = DashboardData(cls.root)
        cls.server = create_server('127.0.0.1', 0, project_root=cls.root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.directory.cleanup()

    def test_compact_quality_preserves_conclusions_flags_first_event_and_counts(self):
        result = self.data.followup_runs()['runs'][0]
        summary = result['quality']
        self.assertEqual(summary['schema'], 'otw2.result_quality_summary.v1')
        for field in ('execution_status','validation_status','domain_status','limit_state_status',
                      'coverage','quality_flags','first_out_of_domain_event','eligible_for_fragility'):
            self.assertEqual(summary[field], self.full_quality[field])
        self.assertFalse(summary['eligible_for_fragility'])
        self.assertEqual(summary['detail_counts']['member_domains'], 1528)
        self.assertEqual(summary['detail_counts']['observed_domains'], 1528)
        self.assertEqual(summary['detail_counts']['domain_events'], 3056)
        self.assertEqual(summary['detail_counts']['first_out_of_domain_members'], 1528)
        self.assertEqual(len(summary['first_out_of_domain_by_member']), 20)
        self.assertTrue(summary['first_out_of_domain_by_member_truncated'])
        self.assertEqual(summary['authoritative_manifest'], result['manifest'])
        for field in ('member_domains','observed_domains','events','evidence'):
            self.assertNotIn(field, summary)
        self.assertLess(len(json.dumps(result).encode()), 30000)
        self.assertEqual(self.manifest.read_bytes(), self.original)

    def test_real_http_overview_serialization_is_small_and_keeps_flags(self):
        with self.opener.open(self.base + '/api/overview', timeout=30) as response:
            body = response.read()
            self.assertEqual(int(response.headers['Content-Length']), len(body))
        self.assertLess(len(body), 40000)
        self.assertLess(len(body), len(self.original) / 20)
        payload = json.loads(body)
        self.assertEqual(payload['api_schema'], API_SCHEMA)
        quality = payload['followup']['runs'][0]['quality']
        self.assertEqual(quality['quality_flags'], self.full_quality['quality_flags'])
        self.assertEqual(quality['first_out_of_domain_event']['member_id'], '1')
        self.assertEqual(self.manifest.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
