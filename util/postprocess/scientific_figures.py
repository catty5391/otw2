"""Shared scientific figure exports; styling never resamples plotted observations.

Set OTW2_FIGURE_SKILL to a nature-figure skill directory for its rendered QA.
Set OTW2_FIGURE_OUTPUT to redirect exports while reviewing a batch.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import textwrap

import matplotlib as mpl
from matplotlib.text import Text
import numpy as np

PALETTE = ('#0072B2', '#D55E00', '#009E73', '#CC79A7', '#666666', '#56B4E9')
RC = {'font.family':'sans-serif', 'font.sans-serif':['DejaVu Sans'], 'font.size':8, 'axes.labelsize':8,
      'axes.titlesize':8, 'xtick.labelsize':7.5, 'ytick.labelsize':7.5,
      'legend.fontsize':7.5, 'legend.frameon':False,
      'axes.spines.top':False, 'axes.spines.right':False, 'axes.linewidth':.65,
      'grid.alpha':.18, 'grid.linewidth':.4, 'axes.axisbelow':True,
      'svg.fonttype':'none', 'pdf.fonttype':42, 'savefig.dpi':300,
      'axes.prop_cycle':mpl.cycler(color=PALETTE), 'path.simplify':False}


def data_digest(fig):
    """Fingerprint complete line, scatter, image and patch geometry in draw order."""
    h=hashlib.sha256(); points=0
    def add(a):
        nonlocal points
        a=np.asarray(a);h.update(str((a.shape,a.dtype)).encode());h.update(a.tobytes());points+=a.size
    for ax in fig.axes:
        for line in ax.lines:add(line.get_xydata())
        for c in ax.collections:
            add(c.get_offsets())
            for path in c.get_paths():add(path.vertices)
            if c.get_array() is not None:add(c.get_array())
        for p in ax.patches:
            add(p.get_path().vertices)
            add(p.get_patch_transform().get_matrix())
        for im in ax.images:add(im.get_array())
    return {'sha256':h.hexdigest(),'coordinate_values':points}


def _skill_module(name, root):
    path=Path(root)/'scripts'/f'{name}.py'
    spec=importlib.util.spec_from_file_location('_otw2_'+name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


def _wrap(s,width):
    return '\n'.join(textwrap.fill(line,width,break_long_words=False,break_on_hyphens=False) for line in s.split('\n'))


def prepare(fig):
    """Style an existing data figure, preserving every data artist and its order."""
    axes=[a for a in fig.axes if a.get_visible()]
    grids=[a.get_subplotspec().get_gridspec() for a in axes if a.get_subplotspec() is not None]
    cols=max((g.ncols for g in grids),default=1);rows=max((g.nrows for g in grids),default=1)
    width=183 if cols>1 else 120
    height=max(70,rows*76+18)
    fig.set_size_inches(width/25.4,height/25.4)
    notes=[t for t in fig.texts if t is not fig._suptitle]
    if notes:
        heading=fig._suptitle.get_text() if fig._suptitle else ''
        fig.suptitle(heading+'\n'+'\n'.join(t.get_text() for t in notes))
        for t in notes:t.remove()
    for text in fig.findobj(Text):text.set_fontsize(7.5);text.set_fontfamily('DejaVu Sans')
    for i,ax in enumerate(axes):
        ax.spines['top'].set_visible(False);ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_linewidth(.65);ax.spines['left'].set_linewidth(.65)
        ax.tick_params(width=.65,length=3,labelsize=7.5)
        ax.xaxis.label.set_text(_wrap(ax.get_xlabel(),46 if cols<3 else 28))
        ax.yaxis.label.set_text(_wrap(ax.get_ylabel(),43))
        title=ax.get_title();ax.set_title('')
        ax.set_title((chr(97+i)+'  ' if len(axes)>1 else '')+_wrap(title,43 if cols<3 else 29),loc='left',fontsize=8,pad=8)
        encodings={};line_encodings={}
        for line in ax.lines:
            label=line.get_label().lower()
            encoding=None
            if 'straight' in label:encoding=('#666666',':')
            elif 'steel01' in label:encoding=('#666666','-.')
            elif 'steel02' in label:encoding=('#0072B2','--' if '16' in label else '-')
            elif 'tmq' in label or 'tian-ma-qu' in label:encoding=('#D55E00','--')
            elif 'curved' in label:encoding=('#CC79A7','-')
            if encoding:
                line_encodings[id(line)]=encoding
                old=mpl.colors.to_hex(line.get_color())
                encodings[old]=encoding if old not in encodings or encodings[old]==encoding else None
        encodings={key:value for key,value in encodings.items() if value is not None}
        for line in ax.lines:
            encoding=line_encodings.get(id(line),encodings.get(mpl.colors.to_hex(line.get_color())))
            if encoding:
                line.set_color(encoding[0])
                if line.get_linestyle() not in ('None','',' '):line.set_linestyle(encoding[1])
            line.set_linewidth(min(line.get_linewidth(),1.25))
            if line.get_markersize()>4:line.set_markersize(4)
            # PDF stroke auditing cannot reconstruct a clipped long path. Render
            # only genuinely zoom-clipped data strokes as a 300-dpi image; all
            # samples remain in the artist and the zoom is unchanged.
            if line.get_transform()==ax.transData:
                xy=line.get_xydata();lo,hi=sorted(ax.get_xlim());bottom,top=sorted(ax.get_ylim())
                if len(xy) and (np.any(xy[:,0]<lo) or np.any(xy[:,0]>hi) or np.any(xy[:,1]<bottom) or np.any(xy[:,1]>top)):
                    line.set_rasterized(True)
        for collection in ax.collections:
            for getter,setter in ((collection.get_edgecolors,collection.set_edgecolors),(collection.get_facecolors,collection.set_facecolors)):
                colors=getter()
                if len(colors):setter([encodings.get(mpl.colors.to_hex(c),(c,None))[0] for c in colors])
        for grid in ax.get_xgridlines()+ax.get_ygridlines():grid.set_alpha(.18);grid.set_linewidth(.4)
        leg=ax.get_legend()
        if leg:
            handles,labels=ax.get_legend_handles_labels();leg.remove()
            ax.legend(handles,[_wrap(t,42 if cols<3 else 27) for t in labels],
                      loc='upper center',bbox_to_anchor=(.5,-.30),ncol=1,
                      fontsize=7.5,frameon=False,handlelength=2.4,labelspacing=.35,borderaxespad=0)
    if fig._suptitle:
        fig._suptitle.set_text(_wrap(fig._suptitle.get_text(),95))
        fig._suptitle.set_fontsize(8.5)
    legends=[a.get_legend() for a in axes]
    labels=[a.get_legend_handles_labels()[1] for a in axes]
    if len(axes)>1 and all(legends) and all(l==labels[0] for l in labels):
        handles,_=axes[0].get_legend_handles_labels()
        for legend in legends:legend.remove()
        fig.legend(handles,[_wrap(t,45) for t in labels[0]],loc='outside lower center',
                   ncol=2,fontsize=7.5,frameon=False,handlelength=2.4)
    fig.set_layout_engine('constrained',h_pad=5/72,w_pad=5/72,hspace=.09,wspace=.07)
    fig.canvas.draw()


def save_figure(fig, filename):
    """Export PNG/PDF/SVG with geometry fingerprints and optional skill audits."""
    filename=Path(filename);base=filename.with_suffix('')
    redirect=os.environ.get('OTW2_FIGURE_OUTPUT')
    if redirect:
        # The batch runner sets one group per call; basename matches legacy URLs.
        base=Path(redirect)/base.name
    base.parent.mkdir(parents=True,exist_ok=True)
    before=data_digest(fig)
    with mpl.rc_context(RC):
        prepare(fig)
        after=data_digest(fig)
        if before!=after:raise RuntimeError('Figure styling changed data geometry')
        qa={'data_before':before,'data_after':after,'data_unchanged':True,
            'size_mm':(fig.get_size_inches()*25.4).tolist(),'dpi':300,'formats':['png','svg','pdf']}
        root=os.environ.get('OTW2_FIGURE_SKILL')
        if root:
            alignment=_skill_module('audit_panel_alignment',root)
            qa['alignment']=alignment.require_matplotlib_panel_alignment(fig,
                json_out=str(base)+'.alignment.json',strict=True,tolerance_pt=1.5,gutter_tolerance_pt=1.5)
        else:qa['alignment']={'status':'not_run','reason':'OTW2_FIGURE_SKILL is unset'}
        fig.savefig(base.with_suffix('.pdf'),dpi=300)
        fig.savefig(base.with_suffix('.svg'),dpi=300)
        fig.savefig(base.with_suffix('.png'),dpi=300)
        if root:
            qa['text']=_skill_module('audit_pdf_text',root).audit_pdf(base.with_suffix('.pdf').read_bytes(),minimum_pt=5)
            qa['collisions']=_skill_module('audit_figure_collisions',root).audit_pdf(base.with_suffix('.pdf'))
        (Path(str(base)+'.qa.json')).write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
        if root and (not qa['text']['auditable'] or qa['text']['below_minimum_count']):
            raise RuntimeError(f'PDF glyph audit failed: {base.name}')
        if root and (not qa['collisions']['auditable'] or qa['collisions']['summary']['fail']):
            raise RuntimeError(f'PDF collision audit failed: {base.name}')
    return base
