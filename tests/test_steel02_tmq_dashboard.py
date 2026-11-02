import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.server import create_server


class Steel02ComparisonPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server('127.0.0.1',0)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.client=build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.worker.join();cls.server.server_close()

    def test_comparison_and_ordered_histories_are_available(self):
        with self.client.open(self.base+'/steel02-tmq/') as r:
            self.assertIn('Steel02 四分段',r.read().decode('utf-8'))
        with self.client.open(self.base+'/steel02-tmq/results/summary.json') as r:s=json.load(r)
        self.assertEqual(s['complete_cases'],46);self.assertFalse(s['physical_validation'])
        for name in ('tower_median_cyclic_steel02_4','long_demo_cyclic_tmq','long_demo_cyclic_forcebeam_16'):
            with self.client.open(self.base+f'/steel02-tmq/results/runs/{name}/history.csv') as r:
                self.assertEqual(len(r.read().decode().splitlines())-1,s['cases'][name]['accepted_substeps']+1)

    def test_literature_and_report_use_utf8_and_pdf_keeps_mime(self):
        for route in ('/steel02-tmq/results/REPORT.md','/steel02-tmq/literature/README.md','/download?key=steel02-tmq-report'):
            with self.client.open(self.base+route) as r:
                self.assertEqual(r.headers.get_content_charset(),'utf-8');self.assertIn('Steel02',r.read().decode('utf-8'))
        with self.client.open(self.base+'/steel02-tmq/literature/jeddi_2020_kns.pdf') as r:
            self.assertEqual(r.headers.get_content_type(),'application/pdf');self.assertTrue(r.read().startswith(b'%PDF'))

    def test_only_whitelisted_outputs_are_served(self):
        for route in ('/steel02-tmq/experiment.py','/steel02-tmq/results/../../Source/Z30103A6.s2k',
                      '/steel02-tmq/literature/../../Source/Z30103A6.s2k','/steel02-tmq/results/runs/missing/history.csv'):
            with self.subTest(route=route),self.assertRaises(HTTPError) as caught:self.client.open(self.base+route)
            self.assertEqual(caught.exception.code,404)


if __name__=='__main__':unittest.main()
