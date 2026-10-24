"""B1 publication admits limited evidence and serves only explicitly public files."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urljoin, urlparse
from urllib.request import build_opener, ProxyHandler

from initial_imperfection_material.tian_ma_qu.publish_diagnostics import read_components, SCHEMAS
from py_view.results_dashboard.server import DashboardData, create_server, TMQ_B1_ROOT

ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/"initial_imperfection_material/tian_ma_qu"/TMQ_B1_ROOT


class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in {"href","src"} and value:self.urls.append(value)


class B1PublicationTests(unittest.TestCase):
    def test_malformed_or_out_of_scope_components_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for path,schema in SCHEMAS.items():
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps({"schema":schema,"new_FE_runs":0,"physical_validation":"unvalidated"}))
            self.assertEqual(len(read_components(root)),4)
            target=root/"modal/summary.json"
            target.write_text(json.dumps({"schema":SCHEMAS["modal/summary.json"],"new_FE_runs":1,"physical_validation":"unvalidated"}))
            with self.assertRaises(ValueError):read_components(root)
            target.write_text(json.dumps({"schema":SCHEMAS["modal/summary.json"],"new_FE_runs":0,"physical_validation":"validated"}))
            with self.assertRaises(ValueError):read_components(root)

    def test_summary_retains_pending_gates_and_unsupported_outputs(self):
        s=DashboardData(ROOT).tian_ma_qu()["b1_diagnostics"]
        self.assertEqual(s["schema"],"otw2.tmq_b1_diagnostics.v1")
        self.assertEqual(s["initial_state_matches"],s["initial_state_comparisons"])
        self.assertEqual(s["new_FE_runs"],0)
        self.assertEqual(s["physical_validation"],"unvalidated")
        self.assertTrue(s["gates"]["G1"].startswith("not_passed"))
        self.assertTrue(s["unsupported_outputs"])

    def test_actual_failed_main_direction_outputs_are_visible(self):
        s=json.loads((BATCH/"summary.json").read_text())
        rows=[r for r in s["static_observations"] if r["case"]=="coupled_80_checked"
              and int(r["angle_deg"])==45 and r["group"]=="attachment" and r["direction"]=="along"]
        self.assertEqual(len(rows),2)
        self.assertTrue(all(not r["passed"] and r["relative_error"]>.14 for r in rows))
        self.assertTrue(all(r["absolute_error_m"]>.0005 for r in rows))

    def test_bare_tower_combined_alias_is_not_duplicated(self):
        s=json.loads((BATCH/"summary.json").read_text())
        rows=[r for r in s["static_observations"] if r["case"]=="bare_checked"
              and int(r["angle_deg"])==45 and r["group"]=="control"]
        self.assertEqual(len(rows),5)
        self.assertEqual(len({r["direction"] for r in rows}),5)

    def test_publication_sources_and_copied_matrices_unchanged(self):
        s=json.loads((BATCH/"summary.json").read_text())
        for name,digest in s["source_sha256"].items():
            self.assertEqual(hashlib.sha256((BATCH/name).read_bytes()).hexdigest(),digest)
        source=ROOT/"initial_imperfection_material/tian_ma_qu/modal_results/runs"
        for key in ["bare_checked","coupled_20_checked","coupled_40_checked","coupled_80_checked"]:
            for name in ["summary.json","eigenvectors.npz","stiffness.npz","mass.npz"]:
                self.assertEqual(hashlib.sha256((source/key/name).read_bytes()).digest(),
                                 hashlib.sha256((BATCH/"modal_view/runs"/key/name).read_bytes()).digest())

    def test_new_schema_rejected_if_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"initial_imperfection_material/tian_ma_qu"/TMQ_B1_ROOT/"summary.json"
            p.parent.mkdir(parents=True);p.write_text('{"schema":"unknown"}')
            with self.assertRaises(ValueError):DashboardData(d).tian_ma_qu()

    def test_whitelist_rejects_source_and_unpublished_iteration(self):
        data=DashboardData(ROOT)
        self.assertIsNone(data.tmq_file("publish_diagnostics.py"))
        self.assertIsNone(data.tmq_file(f"{TMQ_B1_ROOT}/../../../Source/Z30103A6.s2k"))
        self.assertIsNone(data.tmq_file(f"{TMQ_B1_ROOT}/iterations/modal_view_first/index.html"))

    def test_http_page_links_figures_and_old_routes(self):
        server=create_server("127.0.0.1",0,project_root=ROOT)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f"http://127.0.0.1:{server.server_port}"
        opener=build_opener(ProxyHandler({}))
        try:
            for relative in [f"/tmq/{TMQ_B1_ROOT}/index.html",f"/tmq/{TMQ_B1_ROOT}/modal_view/index.html"]:
                page=base+relative; parser=Links()
                with opener.open(page) as response:parser.feed(response.read().decode())
                for url in parser.urls:
                    full=urljoin(page,url);parsed=urlparse(full)
                    if parsed.netloc!=urlparse(base).netloc or parsed.fragment:continue
                    with self.subTest(url=parsed.path),opener.open(full) as response:
                        self.assertEqual(response.status,200)
            for url in ["/tmq/modal_results/index.html","/tmq/wind_speed_results/index.html","/api/tian-ma-qu"]:
                with opener.open(base+url) as response:self.assertEqual(response.status,200)
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__=="__main__":unittest.main()
