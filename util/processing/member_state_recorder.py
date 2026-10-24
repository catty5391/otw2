"""Read-only, committed local states alongside the existing force SQLite database.

Displacements are global [ux,uy,uz,rx,ry,rz] in m/rad. Element forces
remain explicitly labelled local/global; no averaging of rotated segments.
The protocol coordinate is not physical time in a static analysis.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CRITICAL_MEMBERS = (825, 828, 877, 878, 917, 920)


def _finite(values: Iterable[float]) -> list[float]:
    values = [float(value) for value in values]
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Non-finite committed state; cannot record as valid history')
    return values


class MemberStateRecorder:
    def __init__(self, model: Any, path: str | Path, *, members=DEFAULT_CRITICAL_MEMBERS,
                 include_neighbors: bool = False, record_fibers: bool = True):
        self.model, self.ops = model, model.ops
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.record_fibers = record_fibers
        self._sequence = 0
        groups = {}
        for tag, entry in model.element_map.items():
            member = int(entry.get('original_element_tag', tag))
            groups.setdefault(member, []).append(dict(entry, element_tag=int(tag)))
        requested = set(map(int, members))
        missing = requested - groups.keys()
        if missing:
            raise ValueError(f'Unknown physical members: {sorted(missing)}')
        if include_neighbors:
            ends = {int(e.get(key, e[fallback])) for m in requested for e in groups[m]
                    for key, fallback in [('parent_node_i','node_i'),('parent_node_j','node_j')]}
            requested.update(m for m, entries in groups.items() if any(
                int(e.get(key, e[fallback])) in ends for e in entries
                for key, fallback in [('parent_node_i','node_i'),('parent_node_j','node_j')]))
        self.groups = {m: sorted(groups[m], key=lambda e:e.get('segment_index',0)) for m in sorted(requested)}
        self.nodes = sorted({int(e[key]) for entries in self.groups.values() for e in entries for key in ('node_i','node_j')})
        self.coordinates = {str(n):_finite(self.ops.nodeCoord(n)) for n in self.nodes}
        self.metadata = {
            'schema':'otw2.member_states.v1', 'axis_semantics':'quasi_static_protocol_not_seconds',
            'units':{'translation':'m','rotation':'rad','force':'N','moment':'N*m','strain':'1','stress':'Pa'},
            'node_coordinates': self.coordinates, 'members':self.groups,
            'fibers':getattr(model,'section_fiber_map',{}),
            'material_parameters':getattr(model,'material_tag_map',{}),
            'node_masses':{str(n):getattr(model,'mass_map',{}).get(n) for n in self.nodes},
        }
        metadata_path=self.path.with_suffix('.metadata.json')
        if self.path.exists() or metadata_path.exists():
            raise FileExistsError(f'Refusing to overwrite local evidence: {self.path}')
        # Exclusive creation makes accidental re-use fail before writing a sample.
        self.stream=self.path.open('x',encoding='utf-8')
        try:
            with metadata_path.open('x',encoding='utf-8') as stream:
                json.dump(self.metadata,stream,ensure_ascii=False,indent=2,allow_nan=False)
        except BaseException:
            self.stream.close()
            raise

    def _response(self, element: int, *query) -> list[float] | None:
        response=self.ops.eleResponse(element,*query)
        return _finite(response) if response is not None and len(response) else None

    def capture(self, *, stage_id: str, step: int, progress: float,
                direction: int=0, cycle_id: int=0, committed: bool=True,
                loads: dict | None=None) -> dict:
        if not committed:
            raise ValueError('Trial states belong in attempts, not committed member history')
        if direction not in (-1,0,1) or not math.isfinite(progress):
            raise ValueError('Invalid protocol coordinate')
        node_states={str(n):_finite(self.ops.nodeDisp(n)) for n in self.nodes}
        members=[]
        for member_id, entries in self.groups.items():
            first,last=entries[0],entries[-1]
            ni=int(first.get('parent_node_i',first['node_i']))
            nj=int(last.get('parent_node_j',last['node_j']))
            a,b=self.coordinates[str(ni)],self.coordinates[str(nj)]
            initial=math.dist(a,b)
            current=math.dist([a[i]+node_states[str(ni)][i] for i in range(3)],
                              [b[i]+node_states[str(nj)][i] for i in range(3)])
            segments=[]
            for entry in entries:
                tag=entry['element_tag']
                sections=[]
                fibers=getattr(self.model,'section_fiber_map',{}).get(entry.get('section_tag'),[])
                for index in range(1,int(entry.get('num_intgr_pts',3))+1):
                    section={'section_id':index,
                             'deformation':self._response(tag,'section',index,'deformation'),
                             'force':self._response(tag,'section',index,'force'),
                             'stiffness':self._response(tag,'section',index,'stiffness')}
                    extrema=[]
                    if self.record_fibers and fibers:
                        for fiber in fibers:
                            ss=self._response(tag,'section',index,'fiber',fiber['y'],fiber['z'],'stressStrain')
                            if ss and len(ss)==2:
                                extrema.append({'y':fiber['y'],'z':fiber['z'],'stress':ss[0],'strain':ss[1]})
                        section['fiber_probes']=len(extrema)
                        section['fiber_status']='available' if len(extrema)==len(fibers) else 'incomplete'
                        if extrema:
                            section['max_abs_stress']=max(extrema,key=lambda x:abs(x['stress']))
                            section['max_abs_strain']=max(extrema,key=lambda x:abs(x['strain']))
                    else:
                        section['fiber_status']='disabled' if not self.record_fibers else 'not_applicable'
                    sections.append(section)
                segments.append({'element_tag':tag,'segment_id':entry.get('segment_index',0),
                    'local_force':self._response(tag,'localForce'),
                    'global_force':self._response(tag,'globalForce'),
                    'basic_deformation':self._response(tag,'basicDeformation'), 'sections':sections})
            members.append({'original_member_id':member_id,'node_i':ni,'node_j':nj,
                            'initial_chord_m':initial,'current_chord_m':current,
                            'chord_strain':(current-initial)/initial,'segments':segments})
        row={'accepted_step':self._sequence,'source_step':int(step),'stage_id':str(stage_id),
             'cycle_id':int(cycle_id),'direction':direction,'stage_progress':float(progress),
             'committed':True,'domain_time':float(self.ops.getTime()),'node_displacements':node_states,
             'loads':loads or {},'members':members}
        text=json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        self.stream.write(text+'\n')
        self.stream.flush()
        self._sequence+=1
        return row

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self,*exc):
        self.close()


def iter_member_states(path: str | Path):
    """Missing old history explicitly needs a new run, never inverse reconstruction."""
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Boundary history unavailable; a new instrumented run is required: {path}')
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('committed') is not True:
                raise ValueError('Noncommitted row in member state history')
            yield row
