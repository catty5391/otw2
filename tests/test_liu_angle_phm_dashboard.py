import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler,build_opener

from py_view.results_dashboard.server import create_server


class CurvedMaterialPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server('127.0.0.1',0)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.client=build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.worker.join();cls.server.server_close()

    def test_material_page_and_all_recorded_states_are_published(self):
        with self.client.open(self.base+'/liu-phm/') as r:
            self.assertTrue(r.geturl().endswith('/liu-phm/results/index.html'))
            self.assertIn('尚非原作者完整复现',r.read().decode('utf-8'))
        with self.client.open(self.base+'/liu-phm/results/summary.json') as r:s=json.load(r)
        self.assertTrue(s['opensees']['passed'])
        self.assertFalse(s['physical_validation'])
        with self.client.open(self.base+'/liu-phm/results/curved_history.csv') as r:
            self.assertEqual(len(r.read().decode().splitlines())-1,s['completed_steps']+1)

    def test_chinese_report_encoding_remains_explicit(self):
        with self.client.open(self.base+'/liu-phm/results/REPORT.md') as r:
            self.assertEqual(r.headers.get_content_charset(),'utf-8')
            self.assertEqual(r.headers.get_content_type(),'text/plain')
            self.assertIn('解析曲线本构',r.read().decode('utf-8'))

    def test_source_and_directory_traversal_are_not_published(self):
        for path in ('/liu-phm/material.py','/liu-phm/results/../../pyproject.toml','/liu-phm/results/missing.csv'):
            with self.subTest(path=path),self.assertRaises(HTTPError) as caught:
                self.client.open(self.base+path)
            self.assertEqual(caught.exception.code,404)


if __name__=='__main__':unittest.main()
