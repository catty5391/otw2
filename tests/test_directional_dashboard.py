import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import ProxyHandler,build_opener
from html.parser import HTMLParser
from py_view.results_dashboard.server import DashboardData,create_server

ROOT=Path(__file__).resolve().parents[1]
PREFIX="/tmq/directional_results_v2/"


class Links(HTMLParser):
    def __init__(self): super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if (tag=="img" and key=="src") or (tag=="a" and key=="href"): self.links.append(value)


@unittest.skipUnless((ROOT/"initial_imperfection_material/tian_ma_qu/directional_results_v2/summary.json").is_file(),"matrix not yet generated")
class DirectionalDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server("127.0.0.1",0,project_root=ROOT)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}"
        cls.http=build_opener(ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=5)
    def get(self,url):
        with self.http.open(self.base+url,timeout=20) as response: return response.read()
    def test_homepage_and_actual_api(self):
        self.assertIn(b'id="tmqWindPanel"',self.get("/"))
        s=json.loads(self.get("/api/tian-ma-qu"))["directional_wind"]
        self.assertEqual(s["case_count"],8);self.assertTrue(s["passed"])
        self.assertFalse(s["capacity_or_collapse_evaluated"])
    def test_report_links_images_and_all_case_evidence(self):
        parser=Links();parser.feed(self.get(PREFIX+"index.html").decode())
        self.assertGreater(len(parser.links),25)
        for link in parser.links:
            with self.subTest(link=link):
                with self.http.open(urljoin(self.base+PREFIX+"index.html",link),timeout=20) as response:
                    self.assertEqual(response.status,200);response.read()
    def test_source_and_unpublished_cases_remain_private(self):
        for url in ("/tmq/directional_loading.py","/tmq/directional_results/index.html",
                    PREFIX+"runs/unknown/history.csv",PREFIX+"runs/single_0/model_data/nodes.csv"):
            with self.subTest(url=url),self.assertRaises(HTTPError) as caught: self.get(url)
            self.assertEqual(caught.exception.code,404)
    def test_support_reaction_download_is_not_tower_only_total(self):
        text=self.get(PREFIX+"runs/tower_line_45/support_reactions.csv").decode()
        self.assertIn("tower_base",text);self.assertIn("remote_anchor",text)
        self.assertIn("Rz_N",text)


if __name__=="__main__":unittest.main()
