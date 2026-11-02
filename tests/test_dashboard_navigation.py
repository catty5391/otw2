"""HTTP contracts for independent modules and unchanged result artifacts."""
import hashlib
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.navigation import GROUPS, PAGES, add_detail_navigation
from py_view.results_dashboard.server import create_server, PROJECT_ROOT


class DashboardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server('127.0.0.1',0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}';cls.http=build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.thread.join();cls.server.server_close()

    def get(self,path):
        with self.http.open(self.base+path,timeout=15) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.headers.get_content_charset(),'utf-8')
            return response.read().decode()

    def test_home_is_a_directory_without_analysis_views_or_application(self):
        page=self.get('/')
        self.assertIn('研究模块',page);self.assertIn('/modules/materials/',page)
        for token in ('<canvas','<iframe','<img','id="diagnosticCases"','src="/static/app.js'):
            self.assertNotIn(token,page)
        self.assertIn('/static/site.js',page)

    def test_all_module_routes_render_with_working_breadcrumb_and_allowlist(self):
        for key in (*GROUPS,*PAGES):
            with self.subTest(module=key):
                page=self.get(f'/modules/{key}/')
                self.assertIn(f'data-page="{key}"',page)
                self.assertIn('返回成果首页',page);self.assertNotIn('{{body}}',page)
        for url in ('/modules/unknown/','/modules/../../Source/Z30103A6.s2k','/static/pages/forces.html','/static/layout.html'):
            with self.subTest(url=url),self.assertRaises(HTTPError) as caught:self.http.open(self.base+url)
            self.assertEqual(caught.exception.code,404)

    def test_module_content_is_separated_in_actual_html(self):
        expected={'member':'pushoverChart','cyclic':'cyclicChart','diagnostics':'diagnosticCurveChart',
                  'followup':'followupRuns','forces':'forceMap','resources':'reportList'}
        for key,own in expected.items():
            page=self.get(f'/modules/{key}/');self.assertIn(f'id="{own}"',page)
            for other in set(expected.values())-{own}:self.assertNotIn(f'id="{other}"',page)

    def test_existing_result_pages_get_return_links_without_rewriting_files(self):
        path=PROJECT_ROOT/'initial_imperfection_material/steel02_tmq_comparison/results/index.html'
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        page=self.get('/steel02-tmq/results/index.html')
        self.assertIn('otw2-module-navigation',page);self.assertIn('/modules/materials/',page)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.assertIn('/modules/tower/',self.get('/tmq/tower_results/index.html'))

    def test_directory_routes_redirect_and_catalogs_keep_all_destinations(self):
        with self.http.open(self.base+'/modules/forces') as response:
            self.assertEqual(response.geturl(),self.base+'/modules/forces/')
        for key,(_,_,entries) in GROUPS.items():
            page=self.get(f'/modules/{key}/')
            for title,description,url in entries:self.assertIn(f'href="{url}"',page)

    def test_injected_navigation_handles_explicit_and_implicit_body(self):
        for document in ('<html><body><h1>例子</h1></body></html>', '<html><meta charset="UTF-8"><main>例子</main></html>'):
            result=add_detail_navigation(document,'/liu-phm/results/index.html')
            self.assertEqual(result.count('class="otw2-module-navigation"'),1)
            self.assertIn('例子',result)
        self.assertEqual(add_detail_navigation('unchanged','/unrelated.html'),'unchanged')


if __name__=='__main__':unittest.main()
