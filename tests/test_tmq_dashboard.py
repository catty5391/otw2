"""Read-only publication of TMQ results, with no material analysis in HTTP requests."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import ProxyHandler, build_opener
from html.parser import HTMLParser

from py_view.results_dashboard.server import API_SCHEMA, DashboardData, create_server

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ViewerLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if (tag == 'img' and key == 'src') or (tag == 'a' and key == 'href'):
                self.links.append(value)


class TMQDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = DashboardData(PROJECT_ROOT)
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

    def test_api_matches_actual_three_case_results_without_rewriting_them(self):
        path = self.data.tmq_root / 'results/summary.json'
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.opener.open(self.base+'/api/tian-ma-qu', timeout=10) as response:
            data = json.load(response)
        self.assertEqual(data['api_schema'], API_SCHEMA)
        self.assertTrue(data['available'])
        self.assertEqual(data['summary'], json.loads(path.read_text()))
        self.assertEqual(len(data['summary']['cases']), 3)
        self.assertFalse(data['summary']['experimental_validation_performed'])
        self.assertFalse(data['summary']['tower_model_modified'])
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_homepage_has_distinct_new_material_entry_and_fresh_application_assets(self):
        for url in ('/', '/static/app.js?v=tmq-20261023', '/static/styles.css?v=tmq-20261023'):
            with self.opener.open(self.base+url, timeout=10) as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-cache')
                text = response.read().decode()
                if url == '/':
                    self.assertIn('id="tianmaqu"', text)
                    self.assertIn('旧版等效材料', text)
                    self.assertIn('/tmq/results/index.html', text)
                    self.assertIn('已接入独立全塔试验', text)
                    self.assertIn('id="tmqTowerPanel"', text)

    def test_standalone_viewer_redirect_and_all_relative_assets_work(self):
        with self.opener.open(self.base+'/tmq/', timeout=10) as response:
            self.assertEqual(response.geturl(), self.base+'/tmq/results/index.html')
            parser = ViewerLinks();parser.feed(response.read().decode())
        self.assertGreater(len(parser.links), 7)
        for link in parser.links:
            with self.subTest(link=link):
                with self.opener.open(urljoin(self.base+'/tmq/results/index.html', link), timeout=10) as response:
                    self.assertEqual(response.status, 200)

    def test_case_csv_keeps_every_committed_step(self):
        for case in ('p102_row_a','p102_row_b','p89_pf'):
            for filename in ('history.csv','opensees_history.csv'):
                with self.opener.open(f'{self.base}/tmq/results/{case}/{filename}', timeout=10) as response:
                    self.assertEqual(len(response.read().decode().splitlines()), 3402)

    def test_reports_are_in_resource_index_and_downloadable(self):
        keys={r['key'] for r in self.data.resources()['reports']}
        for key in ('tmq-report','tmq-readme','tmq-sources'):
            self.assertIn(key, keys)
            with self.opener.open(self.base+'/download?key='+key, timeout=10) as response:
                self.assertIn('attachment', response.headers['Content-Disposition'])
                self.assertGreater(len(response.read()), 100)

    def test_private_sources_and_traversals_are_not_exposed(self):
        for suffix in ('material.py','_native_cache/manifest.json','results/../../../pyproject.toml',
                       '%2e%2e/pyproject.toml','results/unknown/history.csv'):
            with self.subTest(suffix=suffix), self.assertRaises(HTTPError) as caught:
                self.opener.open(self.base+'/tmq/'+suffix, timeout=10)
            self.assertEqual(caught.exception.code, 404)

    def test_missing_and_incomplete_runs_never_gain_completed_status(self):
        with tempfile.TemporaryDirectory() as folder:
            data=DashboardData(folder)
            self.assertFalse(data.tian_ma_qu()['available'])
            path=data.tmq_root/'results/summary.json';path.parent.mkdir(parents=True)
            raw={'schema_version':1,'complete':False,'cases':[],'experimental_validation_performed':False}
            path.write_text(json.dumps(raw))
            self.assertFalse(data.tian_ma_qu()['summary']['complete'])
            path.write_text(json.dumps({'schema_version':99,'cases':[]}))
            with self.assertRaises(ValueError):data.tian_ma_qu()

    def test_whitelisted_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            data=DashboardData(folder);data.tmq_root.mkdir(parents=True)
            secret=Path(outside)/'secret.md';secret.write_text('not publishable')
            (data.tmq_root/'REPORT.md').symlink_to(secret)
            self.assertIsNone(data.tmq_file('REPORT.md'))
            self.assertIsNone(data.downloadable('tmq-report'))

    def test_full_tower_published_results_keep_partial_extension_status(self):
        payload=self.data.tian_ma_qu()["full_tower"]
        self.assertIsNotNone(payload)
        self.assertEqual(payload["run"]["status"],"complete")
        self.assertFalse(payload["validated_for_tower"])
        self.assertEqual(payload["extended_run"]["status"],"partial")
        self.assertEqual(payload["extended_run"]["stop_reason"],"minimum_increment")
        with self.opener.open(self.base+'/tmq/tower_results/index.html') as response:
            page=response.read().decode()
        self.assertIn('264',page)
        self.assertIn('409',page)
        self.assertIn('不能直接认定全塔倒塌',page)

    def test_full_tower_assets_are_explicitly_whitelisted(self):
        for suffix in ('index.html','publication.json','full_tower_hysteresis.svg','critical_members.svg',
                       'extended_hysteresis.svg','tmq_bounded_03/history.csv',
                       'tmq_bounded_03/model_data/tmq_member_parameters.csv','tmq_cyclic_02/attempts.jsonl'):
            with self.opener.open(self.base+'/tmq/tower_results/'+suffix) as response:
                self.assertEqual(response.status,200)
                self.assertGreater(len(response.read()),100)
        for suffix in ('tmq_cyclic_01/summary.json','../material.py','tmq_bounded_03/unknown.txt'):
            with self.assertRaises(HTTPError):
                self.opener.open(self.base+'/tmq/tower_results/'+suffix)

    def test_weakness_analysis_is_not_advertised_as_damage_or_collapse_validation(self):
        data=self.data.tian_ma_qu()['weakness']
        self.assertFalse(data['validated_for_collapse'])
        self.assertTrue(data['replay_check']['passed'])
        self.assertEqual(data['primary_max_isdr_y']['panel'],4)
        self.assertEqual(data['geometric_max_isdr_y']['panel'],8)
        self.assertEqual({e['element_tag'] for e in data['events']},{825,828,917,920})
        with self.opener.open(self.base+'/tmq/weakness_results/index.html') as response:
            page=response.read().decode()
            self.assertIn('不是论文的多风向',page)
            self.assertIn('不强行合成一个危险评分',page)

    def test_weakness_links_and_private_paths(self):
        with self.opener.open(self.base+'/tmq/weakness_results/index.html') as response:
            parser=ViewerLinks();parser.feed(response.read().decode())
        for link in parser.links:
            with self.opener.open(urljoin(self.base+'/tmq/weakness_results/index.html',link)) as response:
                self.assertEqual(response.status,200)
                self.assertGreater(len(response.read()),0)
        for suffix in ('weakness_analysis.py','weakness_viewer.html','weakness_runs/arbitrary/summary.json'):
            with self.assertRaises(HTTPError):
                self.opener.open(self.base+'/tmq/'+suffix)


if __name__ == '__main__':
    unittest.main()
