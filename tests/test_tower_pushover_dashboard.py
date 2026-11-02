"""Independent pushover page, artifact encoding and safe public routes."""
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
from py_view.results_dashboard.server import create_server,PROJECT_ROOT


class TowerPushoverDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=PROJECT_ROOT/'initial_imperfection_material/tower_material_pushover/results'
        if not (cls.root/'index.html').exists():raise unittest.SkipTest('Publication pending')
        cls.server=create_server('127.0.0.1',0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}';cls.client=build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.thread.join();cls.server.server_close()

    def test_page_directory_and_return_navigation(self):
        with self.client.open(self.base+'/tower-pushover/') as r:
            self.assertTrue(r.geturl().endswith('/results/index.html'));p=r.read().decode()
        for term in ('全塔推覆','Steel01','Steel02','Tian–Ma–Qu','angle-filter','/modules/tower/','未指定易损性损伤等级'):
            self.assertIn(term,p)
        for route in ('/','/modules/tower/'):
            with self.client.open(self.base+route) as r:self.assertIn('/tower-pushover/results/index.html',r.read().decode())

    def test_utf8_report_downloads_and_data(self):
        for route in ('/tower-pushover/results/REPORT.md','/download?key=tower-pushover-report'):
            with self.client.open(self.base+route) as r:
                self.assertEqual(r.headers.get_content_charset(),'utf-8');text=r.read().decode()
                self.assertIn('实际执行步骤',text);self.assertIn('不收敛问题记录',text)
        for filename in ('summary.json','issues.json','damage_candidates.json','case_summary.csv','histories.csv'):
            with self.client.open(self.base+'/tower-pushover/results/'+filename) as r:
                self.assertEqual(r.status,200);self.assertGreater(len(r.read()),100)

    def test_all_exported_figures(self):
        for figure in ('capacity','alongwind_capacity','member_events','story_drift','stiffness'):
            for ext,mime in [('png','image/png'),('svg','image/svg+xml'),('pdf','application/pdf')]:
                with self.subTest(figure=figure,ext=ext),self.client.open(self.base+f'/tower-pushover/results/{figure}.{ext}') as r:
                    self.assertEqual(r.headers.get_content_type(),mime);self.assertGreater(len(r.read()),1000)

    def test_only_whitelisted_results_are_public(self):
        for route in ('/tower-pushover/experiment.py','/tower-pushover/results/../../Source/Z30103A6.s2k',
                      '/tower-pushover/results/runs/tmq_deg_0/code_snapshot/model/tower_model.py'):
            with self.subTest(route=route),self.assertRaises(HTTPError) as c:self.client.open(self.base+route)
            self.assertEqual(c.exception.code,404)
        with self.client.open(self.base+'/tower-pushover/results/runs/steel01_four_segments_deg_0/summary.json') as r:
            self.assertEqual(json.load(r)['scheme'],'steel01_four_segments')

if __name__=='__main__':unittest.main()
