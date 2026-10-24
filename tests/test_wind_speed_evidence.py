"""Acceptance of actual saved wind ramps and publication boundaries."""
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import build_opener, ProxyHandler

from py_view.results_dashboard.server import DashboardData, create_server
from tests.test_directional_dashboard import Links

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/"initial_imperfection_material/tian_ma_qu/wind_speed_results"
PREFIX="/tmq/wind_speed_results/"


@unittest.skipUnless((RESULTS/"summary.json").is_file(),"wind ramp evidence not generated")
class WindSpeedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.publication=json.loads((RESULTS/"summary.json").read_text())

    def test_matrix_and_no_nonconvergence_as_collapse(self):
        s=self.publication
        self.assertEqual(s["coarse_case_count"],8)
        self.assertTrue(s["all_saved_evidence_valid"])
        self.assertFalse(s["engineering_ultimate_wind_speed_established"])
        for c in s["cases"]:
            self.assertTrue(c["evidence_valid"],c["key"])
            self.assertIsNone(c["true_ultimate_wind_speed_m_s"])
            if c["run"].get("stop_reason")=="minimum_increment" and not c["sampled_path_peak_with_decline"]:
                self.assertEqual(c["classification"],"numerical_boundary_not_collapse")
            for name,digest in c["artifacts_sha256"].items():
                self.assertEqual(hashlib.sha256((RESULTS/"runs"/c["key"]/name).read_bytes()).hexdigest(),digest)

    def test_all_committed_tower_forces_are_present(self):
        for c in self.publication["cases"]:
            with self.subTest(case=c["key"]):
                path=RESULTS/"runs"/c["key"]/"internal_forces.sqlite"
                with sqlite3.connect(f"file:{path}?mode=ro",uri=True) as db:
                    self.assertEqual(db.execute("select count(*) from force_history").fetchone()[0],
                                     (c["run"]["accepted_steps"]+1)*1528)
                    self.assertEqual(db.execute("select count(*) from force_history where p_i is null or mz_j is null").fetchone()[0],0)
                self.assertTrue(c["path_audit"]["support_states_complete"])
                self.assertLess(c["path_audit"]["global_XYZ_reaction_balance_max_N"],.02)
                if c["mode"]=="tower_line_explicit":
                    self.assertTrue(c["path_audit"]["all_recorded_cables_in_tension"])

    def test_positive_load_factor_mapping_and_monotonic_ramps(self):
        for c in self.publication["cases"]:
            factors=[float(r["wind_load_factor"]) for r in c["history"]]
            for r in c["history"]:
                factor=float(r["wind_load_factor"])
                if factor>=0:self.assertAlmostEqual(r["equivalent_wind_speed_m_s"]**2,400*factor,places=7)
            if c["continuation_target_control_drift"] is None:
                self.assertTrue(all(b>a for a,b in zip(factors,factors[1:])))
            self.assertTrue(c["run"]["gravity_equilibrium_passed"])


@unittest.skipUnless((RESULTS/"summary.json").is_file(),"wind ramp evidence not generated")
class WindSpeedDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server("127.0.0.1",0,project_root=ROOT)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}";cls.http=build_opener(ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=5)
    def get(self,url):
        with self.http.open(self.base+url,timeout=20) as response:return response.read()
    def test_homepage_api_and_limits(self):
        self.assertIn(b'id="tmqSpeedPanel"',self.get("/"))
        data=json.loads(self.get("/api/tian-ma-qu"))["wind_speed"]
        self.assertEqual(data["coarse_case_count"],8)
        self.assertFalse(data["engineering_ultimate_wind_speed_established"])
        self.assertTrue(data["all_saved_evidence_valid"])
    def test_report_links_and_figures_are_published(self):
        body=self.get(PREFIX+"index.html").decode();parser=Links();parser.feed(body)
        self.assertIn("不收敛不等于",body)
        data=DashboardData(ROOT)
        for link in parser.links:
            absolute=urlparse(urljoin(self.base+PREFIX+"index.html",link))
            with self.subTest(link=link):
                if absolute.path.startswith("/tmq/"):
                    file=data.tmq_file(absolute.path.removeprefix("/tmq/"))
                    self.assertIsNotNone(file)
                    self.assertGreater(file.stat().st_size,0)
                    # Large archives are checked through the same server resolver;
                    # do not transfer a complete database to test a report link.
                    if file.stat().st_size<500_000:self.get(absolute.path)
    def test_unpublished_sources_and_unknown_runs_not_exposed(self):
        for path in ("/tmq/wind_speed_exploration.py",PREFIX+"runs/unknown/history.csv",
                     PREFIX+"configs/single_0.json",PREFIX+"../material.py"):
            with self.subTest(path=path),self.assertRaises(HTTPError) as caught:self.get(path)
            self.assertEqual(caught.exception.code,404)


if __name__=="__main__":unittest.main()
