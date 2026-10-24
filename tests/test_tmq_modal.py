"""Modal mass invariance, saved eigen-equation evidence and public viewer contracts."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urljoin,urlparse
from urllib.request import build_opener,ProxyHandler
import numpy as np
from scipy.sparse import load_npz

from initial_imperfection_material.tian_ma_qu.modal_analysis import modal_metrics,weighted_mac,run_case
from initial_imperfection_material.tian_ma_qu.publish_modal import CASES
from py_view.results_dashboard.server import create_server,DashboardData
from tests.test_directional_dashboard import Links

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/"initial_imperfection_material/tian_ma_qu/modal_results"


class ModalMetricTests(unittest.TestCase):
    def test_scaling_free_mass_and_shared_component_mass(self):
        mass=np.zeros((3,6));mass[:,0]=[1000,2,6]
        fixed=np.zeros((3,6),bool);fixed[0,:]=True
        tower=mass*.5;line=mass*.25
        modes=np.zeros((2,3,6));modes[0,1,0]=3;modes[1,2,0]=-8
        v=modal_metrics(modes,mass,fixed,tower,line)
        np.testing.assert_allclose(v["mass_ratios"][:,0],[.25,.75])
        np.testing.assert_allclose(v["tower_kinetic_share"],[.5,.5])
        np.testing.assert_allclose(v["cable_kinetic_share"],[.25,.25])
        np.testing.assert_allclose(v["insulator_kinetic_share"],[.25,.25])
        np.testing.assert_allclose(v["gram"],np.eye(2),atol=1e-14)
        other=modal_metrics(modes*np.array([-7,2])[:,None,None],mass,fixed,tower,line)
        np.testing.assert_allclose(v["effective_mass"],other["effective_mass"],atol=1e-12)
    def test_zero_modes_and_duplicate_component_mass_rejected(self):
        mass=np.ones((2,6));fixed=np.zeros_like(mass,bool);zero=np.zeros((1,2,6))
        with self.assertRaisesRegex(ValueError,"positive generalized mass"):
            modal_metrics(zero,mass,fixed,mass*0,mass*0)
        with self.assertRaisesRegex(ValueError,"component mass"):
            modal_metrics(zero+1,mass,fixed,mass,mass)
    def test_mac_sign_scale_and_orthogonal_shapes(self):
        a=np.array([1.,2.,0]);w=np.array([2.,1.,3.])
        self.assertAlmostEqual(weighted_mac(a,-3*a,w),1)
        self.assertAlmostEqual(weighted_mac(a,[1,-1,0],w),0)
        self.assertEqual(weighted_mac(a,a*0,w),0)
    def test_invalid_input_and_existing_evidence_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"new"
            with self.assertRaises(ValueError):run_case(out,segments=1)
            self.assertFalse(out.exists())
            out.mkdir();p=out/"keep";p.write_text("keep")
            with self.assertRaises(FileExistsError):run_case(out)
            self.assertEqual(p.read_text(),"keep")


@unittest.skipUnless((RESULTS/"summary.json").is_file(),"modal results not generated")
class ModalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.s=json.loads((RESULTS/"summary.json").read_text())
    def test_cases_gravity_checks_and_mass_partition(self):
        self.assertFalse(self.s["wind_load_applied"])
        self.assertFalse(self.s["validated_for_design"])
        self.assertEqual(set(self.s["cases"]),set(CASES))
        for case in self.s["cases"].values():
            self.assertEqual(case["status"],"complete");self.assertTrue(case["checks_passed"])
            self.assertTrue(case["gravity_equilibrium"]["passed"])
            self.assertEqual(case["gravity_buckled_members"],0);self.assertEqual(case["gravity_tension_yield_members"],0)
            self.assertAlmostEqual(sum(case["component_total_mass_kg"].values()),case["gravity_total_mass_kg"],places=7)
            self.assertLess(case["orthogonality_max_error"],1e-6)
            self.assertLess(case["participation_native_max_error_percentage_points"],1e-6)
            self.assertEqual(case["eigen_analysis_displacement_or_time_change"],0)
    def test_saved_matrices_independently_verify_vectors_and_node_mapping(self):
        for key in CASES:
            with self.subTest(case=key):
                root=RESULTS/"runs"/key;K=load_npz(root/"stiffness.npz");M=load_npz(root/"mass.npz")
                with np.load(root/"equation_modes.npz") as q,np.load(root/"eigenvectors.npz") as n:
                    V=q["vectors"];lam=q["values"];kv=K@V;mv=(M@V)*lam
                    relative=np.linalg.norm(kv-mv,axis=0)/(np.linalg.norm(kv,axis=0)+np.linalg.norm(mv,axis=0))
                    self.assertLess(relative.max(),1e-8)
                    np.testing.assert_allclose(V.T@(M@V),np.eye(len(lam)),atol=1e-8)
                    dofs=q["node_dofs"];valid=dofs>=0
                    np.testing.assert_allclose(n["raw_vectors"][:,valid],V[dofs[valid],:].T,atol=1e-12)
                    np.testing.assert_allclose(M.diagonal()[dofs[valid]],n["mass"][valid],atol=1e-10)
    def test_shape_matching_and_refinement_do_not_confuse_global_ranks(self):
        for rows in self.s["tower_matches"].values():
            self.assertEqual(len(rows),3)
            for row in rows:
                self.assertGreater(row["tower_MAC"],.99)
                self.assertGreater(row["mode"],50)
        for value in self.s["native_solver_frequency_crosscheck"].values():self.assertLess(value,1e-8)
        primary=self.s["cases"][self.s["primary_case"]]
        self.assertLess(primary["modes"][0]["tower_kinetic_share"],1e-4)
        self.assertGreater(primary["modes"][0]["frequency_Hz"],.18)
        self.assertLess(primary["modes"][0]["frequency_Hz"],.21)
        self.assertLess(primary["cumulative_mass_ratio_XYZ"][0],.9)
        self.assertEqual(self.s["excluded_attempt"]["case"],"coupled_40")


@unittest.skipUnless((RESULTS/"summary.json").is_file(),"modal results not generated")
class ModalDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server("127.0.0.1",0,project_root=ROOT)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}";cls.http=build_opener(ProxyHandler({}))
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=5)
    def get(self,path):
        with self.http.open(self.base+path,timeout=20) as response:return response.read()
    def test_actual_homepage_api_and_all_viewer_cases(self):
        self.assertIn(b'id="tmqModalPanel"',self.get("/"))
        s=json.loads(self.get("/api/tian-ma-qu"))["modal_analysis"]
        self.assertEqual(s["primary_case"],"coupled_80_checked")
        for key in CASES:
            viewer=json.loads(self.get(f"/tmq/modal_results/runs/{key}/viewer_data.json"))
            self.assertEqual(len(viewer["modes"]),len(viewer["display_shapes"]))
            self.assertEqual(len(viewer["geometry"]["nodes"]),len(viewer["display_shapes"][0]))
    def test_links_and_protected_unconverged_attempt(self):
        body=self.get("/tmq/modal_results/index.html").decode();parser=Links();parser.feed(body);data=DashboardData(ROOT)
        for link in parser.links:
            path=urlparse(urljoin(self.base+"/tmq/modal_results/index.html",link)).path
            if path.startswith("/tmq/"):
                self.assertIsNotNone(data.tmq_file(path.removeprefix("/tmq/")),path)
        for path in ("/tmq/modal_results/runs/coupled_40/summary.json","/tmq/modal_analysis.py"):
            with self.assertRaises(HTTPError) as caught:self.get(path)
            self.assertEqual(caught.exception.code,404)


if __name__=="__main__":unittest.main()
