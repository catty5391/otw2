"""HTTP boundary and UTF-8 publication of rain-loading evidence."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.server import create_server


class RainLoadingDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        results = cls.root / 'rain_loading/results'
        results.mkdir(parents=True)
        (results / 'summary.json').write_text(json.dumps({'schema':'otw2.rain_loading.v1',
            'status':'numerical_verified','findings':['数值检查不替代物理试验。']},ensure_ascii=False),encoding='utf-8')
        (results / 'REPORT.md').write_text('# 雨谱与风雨荷载\n真实计算范围。\n',encoding='utf-8')
        (results / 'loading_interface.md').write_text('# 通用接口\n静力与时程的适用范围。\n',encoding='utf-8')
        (results / 'loading_interface_verification.json').write_text('{"passed":true}',encoding='utf-8')
        (results / 'tower_nodal_loads.csv').write_text('节点,力\n1,0\n',encoding='utf-8-sig')
        (results / 'drop_spectrum.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'test-png-bytes')
        literature = cls.root / 'literature/rain_loading_investigation_20261102'
        literature.mkdir(parents=True)
        (literature/'README.md').write_text('# 文献公式核对\n来源范围。',encoding='utf-8')
        cls.server = create_server('127.0.0.1',0,project_root=cls.root)
        cls.worker = threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.client = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.worker.join();cls.server.server_close();cls.temp.cleanup()

    def get(self,path):
        return self.client.open(self.base+path,timeout=10)

    def test_independent_page_aliases_and_home_entry(self):
        for route in ('/rain-loading/','/rain-loading/results/index.html','/modules/rain/'):
            with self.subTest(route=route),self.get(route) as r:
                text=r.read().decode('utf-8')
                self.assertEqual(r.headers.get_content_charset(),'utf-8')
                self.assertIn('data-page="rain"',text)
                self.assertIn('雨滴粒径谱',text)
                self.assertIn('雨强时间过程',text)
                self.assertIn('荷载功率谱',text)
                self.assertIn('/static/rain.js',text)
                self.assertNotIn('/static/app.js',text)
                self.assertNotIn('{{body}}',text)
        with self.get('/') as r:self.assertIn('href="/rain-loading/"',r.read().decode())

    def test_summary_and_reports_preserve_utf8(self):
        with self.get('/rain-loading/results/summary.json') as r:
            self.assertEqual(r.headers.get_content_charset(),'utf-8')
            self.assertEqual(json.load(r)['schema'],'otw2.rain_loading.v1')
        for route in ('/rain-loading/results/REPORT.md','/download?key=rain-loading-report',
                      '/rain-loading/results/loading_interface.md',
                      '/rain-loading/literature/README.md','/download?key=rain-loading-literature'):
            with self.subTest(route=route),self.get(route) as r:
                self.assertEqual(r.headers.get_content_charset(),'utf-8')
                self.assertIn('范围',r.read().decode())
                if route.startswith('/download'):self.assertIn('attachment',r.headers['Content-Disposition'])
                else:self.assertEqual(r.headers.get_content_type(),'text/plain')

    def test_data_and_figure_bytes_are_unchanged(self):
        for name in ('tower_nodal_loads.csv','drop_spectrum.png'):
            with self.get('/rain-loading/results/'+name) as r:
                self.assertEqual(r.read(),(self.root/'rain_loading/results'/name).read_bytes())
        with self.get('/rain-loading/results/drop_spectrum.png') as r:
            self.assertEqual(r.headers['Content-Type'],'image/png')

    def test_missing_and_unpublished_files_do_not_leak(self):
        for route in ('/rain-loading/results/tower_response.png','/rain-loading/experiment.py',
                      '/rain-loading/results/../../Source/Z30103A6.s2k',
                      '/rain-loading/literature/private.md','/static/pages/rain.html'):
            with self.subTest(route=route),self.assertRaises(HTTPError) as caught:self.get(route)
            self.assertEqual(caught.exception.code,404)

    def test_fixed_public_filename_cannot_escape_root_through_symlink(self):
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'private.json';target.write_text('{"private":true}')
            link=self.root/'rain_loading/results/verification.json';link.symlink_to(target)
            try:
                with self.assertRaises(HTTPError) as caught:self.get('/rain-loading/results/verification.json')
                self.assertEqual(caught.exception.code,404)
            finally:link.unlink()

    def test_page_assets_are_served_with_revalidation(self):
        for name in ('rain.js','rain.css'):
            with self.get('/static/'+name) as r:
                self.assertEqual(r.headers.get_content_charset(),'utf-8')
                self.assertEqual(r.headers['Cache-Control'],'no-cache')
                self.assertGreater(len(r.read()),100)


if __name__ == '__main__': unittest.main()
