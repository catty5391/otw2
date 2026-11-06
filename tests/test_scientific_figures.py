"""Scientific integrity and export boundaries, using actual rendered data."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import numpy as np
from util.postprocess.scientific_figures import save_figure,prepare
from py_view.results_dashboard.figure_gallery import artifact,render,RELATIVE_ROOT


class ScientificFiguresTests(unittest.TestCase):
    def tearDown(self):plt.close('all')

    def test_series_identity_does_not_depend_on_old_color(self):
        fig,ax=plt.subplots()
        steel,=ax.plot([0,1],[0,2],color='#D55E00',label='Steel02 / forceBeamColumn 16')
        tmq,=ax.plot([0,1],[0,3],color='#D55E00',label='TMQ')
        ax.legend();prepare(fig)
        self.assertEqual(steel.get_color(),'#0072B2')
        self.assertEqual(tmq.get_color(),'#D55E00')

    def test_cyclic_order_nonfinite_gaps_and_stopping_marker_survive_export(self):
        # Nonmonotone x must never be sorted/smoothed. A NaN must remain a gap.
        x=np.array([0.,-2.,1.,-3.,np.nan,2.,0.]);y=np.array([0.,-4.,1.,-2.,np.nan,2.,.1])
        fig,ax=plt.subplots();line,=ax.plot(x,y,label='TMQ')
        end,=ax.plot(0,.1,'x');ax.legend();ax.set(xlabel='Displacement (mm)',ylabel='Force (kN)')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'OTW2_FIGURE_OUTPUT':temp,'OTW2_FIGURE_SKILL':''}):
            save_figure(fig,'cycle.png')
            np.testing.assert_equal(line.get_xdata(),x);np.testing.assert_equal(line.get_ydata(),y)
            self.assertEqual(end.get_marker(),'x');self.assertEqual(len(ax.lines),2)
            for ext in ('png','pdf','svg'):self.assertGreater((Path(temp)/('cycle.'+ext)).stat().st_size,100)
            qa=json.loads((Path(temp)/'cycle.qa.json').read_text())
            self.assertEqual(qa['data_before'],qa['data_after']);self.assertTrue(qa['data_unchanged'])
            self.assertEqual(qa['alignment']['status'],'not_run')
            self.assertIn('<text',(Path(temp)/'cycle.svg').read_text())

    def test_bar_geometry_and_all_scatter_points_survive(self):
        fig,(a,b)=plt.subplots(1,2);bars=a.barh(['Dry','Rain'],[12.,12.08]);a.set_xlabel('Displacement (mm)')
        x=np.linspace(-1,1,2001);scatter=b.scatter(x,x*x,s=1);b.set(xlabel='x',ylabel='y')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'OTW2_FIGURE_OUTPUT':temp,'OTW2_FIGURE_SKILL':''}):
            save_figure(fig,'data.png')
        self.assertEqual([p.get_width() for p in bars],[12.,12.08])
        np.testing.assert_equal(scatter.get_offsets(),np.column_stack([x,x*x]))

    def test_gallery_allowlist_and_symlink_boundary(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root=Path(temp);folder=root/RELATIVE_ROOT/'tower';folder.mkdir(parents=True)
            (folder/'capacity.png').write_bytes(b'PNG fixture')
            self.assertIsNotNone(artifact(root,'tower/capacity.png'))
            for name in ('../secret.png','tower/../capacity.png','tower/private.png','tower/capacity.qa.json'):
                self.assertIsNone(artifact(root,name))
            target=Path(outside)/'secret.pdf';target.write_bytes(b'private')
            (folder/'capacity.pdf').symlink_to(target)
            self.assertIsNone(artifact(root,'tower/capacity.pdf'))
            page=render(root);self.assertIn('1 幅图',page);self.assertIn('/scientific-figures/tower/capacity.png',page)

    def test_failed_export_does_not_replace_existing_result(self):
        from scripts.rebuild_scientific_figures import publish_exports
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);draft=root/'draft/tower';draft.mkdir(parents=True)
            existing=root/'existing';existing.mkdir();(existing/'capacity.png').write_bytes(b'previous result')
            (draft/'capacity.qa.json').write_text(json.dumps({'data_unchanged':False}))
            with patch('scripts.rebuild_scientific_figures.DESTINATIONS',{'tower':existing}),self.assertRaises(ValueError):
                publish_exports(root/'draft',['tower'])
            self.assertEqual((existing/'capacity.png').read_bytes(),b'previous result')

if __name__=='__main__':unittest.main()
