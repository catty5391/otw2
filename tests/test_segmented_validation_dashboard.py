"""Publication preserves actual spatial-member results and serves only artifacts."""
import csv
import io
import json
import math
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from py_view.results_dashboard.server import create_server, PROJECT_ROOT


RESULTS=PROJECT_ROOT/'initial_imperfection_material/segmented_member_validation/results'


class SegmentedValidationPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=create_server('127.0.0.1',0)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.worker.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.client=build_opener(ProxyHandler({}))
        cls.summary=json.loads((RESULTS/'summary.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.worker.join();cls.server.server_close()

    def test_independent_page_and_directory_show_actual_completed_scope(self):
        with self.client.open(self.base+'/segmented-validation/') as response:
            self.assertTrue(response.geturl().endswith('/results/index.html'))
            page=response.read().decode('utf-8')
        self.assertIn('63/63',page)
        self.assertIn('全塔17纤维',page)
        self.assertIn('L/1000',page)
        self.assertIn('/modules/materials/',page)
        self.assertIn('实际端部历史',page)
        with self.client.open(self.base+'/modules/materials/') as response:
            self.assertIn('/segmented-validation/results/index.html',response.read().decode())

    def test_published_histories_preserve_order_and_match_solver_summaries(self):
        with self.client.open(self.base+'/segmented-validation/results/histories.csv') as response:
            rows=list(csv.DictReader(io.StringIO(response.read().decode())))
        by_case={key:[] for key in self.summary['cases']}
        for row in rows:by_case[row.pop('case')].append(row)
        self.assertEqual(self.summary['complete_cases'],63)
        self.assertFalse(self.summary['physical_validation'])
        self.assertFalse(self.summary['full_tower_validation'])
        self.assertEqual(sum(c['failed_attempts'] for c in self.summary['cases'].values()),2)
        for key,history in by_case.items():
            with self.subTest(case=key):
                case=self.summary['cases'][key]
                self.assertEqual(len(history),case['accepted_substeps']+1)
                self.assertEqual([int(r['sequence']) for r in history],list(range(len(history))))
                self.assertTrue(all(math.isfinite(float(row['force_N'])) for row in history))
                self.assertAlmostEqual(min(float(row['force_N']) for row in history)/-1000,
                                       case['peak_compression_kN'],places=7)
                self.assertAlmostEqual(float(history[-1]['strain']),case['targets_strain'][-1],places=11)
                self.assertLess(max(float(row['reaction_balance_N']) for row in history),1e-5)
                if case['loading']=='cyclic':
                    self.assertTrue(any(float(a['displacement_m'])>float(b['displacement_m']) for a,b in zip(history,history[1:])))
                    self.assertTrue(any(float(a['displacement_m'])<float(b['displacement_m']) for a,b in zip(history,history[1:])))
        for tag in (349,920,292):
            grid=by_case[f'convergence/m{tag}_d16_f32x4_monotonic']
            direction=by_case[f'direction/member_{tag}_weak_plus_r1000']
            self.assertEqual(len(grid),len(direction))
            for a,b in zip(grid,direction):
                self.assertAlmostEqual(float(a['force_N']),float(b['force_N']),delta=1e-5)

    def test_report_encoding_figures_and_downloads(self):
        for path in ('/segmented-validation/results/REPORT.md','/download?key=segmented-validation-report'):
            with self.client.open(self.base+path) as response:
                self.assertEqual(response.headers.get_content_charset(),'utf-8')
                report=response.read().decode()
                self.assertIn('L/1000下',report)
                self.assertIn('轴向反力平衡',report)
        for name in ('mesh_curves','cyclic_curves','direction_curves','direction_peaks','section_directions'):
            for ext,expected in [('png','image/png'),('svg','image/svg+xml'),('pdf','application/pdf')]:
                with self.subTest(figure=name,extension=ext),self.client.open(self.base+f'/segmented-validation/results/{name}.{ext}') as response:
                    self.assertEqual(response.headers.get_content_type(),expected)
                    self.assertGreater(len(response.read()),1000)

    def test_method_parameters_and_source_evidence_are_accessible(self):
        for route in ('/segmented-validation/README.md','/segmented-validation/results/convergence/plan.json',
                      '/segmented-validation/results/convergence/mesh_summary.csv',
                      '/segmented-validation/results/convergence/fiber_summary.csv',
                      '/segmented-validation/results/direction/direction_geometry_audit.csv',
                      '/steel02-tmq/literature/supplement_20261029/du_ssrc_2022.pdf'):
            with self.subTest(route=route),self.client.open(self.base+route) as response:
                self.assertEqual(response.status,200)
                self.assertGreater(len(response.read()),100)

    def test_unpublished_sources_and_path_traversal_are_rejected(self):
        for route in ('/segmented-validation/mechanics.py','/segmented-validation/results/../../Source/Z30103A6.s2k',
                      '/segmented-validation/results/runs/unknown/history.csv'):
            with self.subTest(route=route),self.assertRaises(HTTPError) as error:
                self.client.open(self.base+route)
            self.assertEqual(error.exception.code,404)


if __name__=='__main__':unittest.main()
