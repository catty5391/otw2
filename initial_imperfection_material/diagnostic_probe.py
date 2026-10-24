"""Event-selected stiffness diagnostics with explicit physical-state checks."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def physical_snapshot(ops):
    return {'time':float(ops.getTime()),
            'nodes':{str(n):{'disp':list(ops.nodeDisp(n)), 'vel':list(ops.nodeVel(n)),
                             'accel':list(ops.nodeAccel(n))} for n in ops.getNodeTags()},
            'elements':{str(e):{'basic':list(ops.eleResponse(e,'basicDeformation')),
                                'section':list(ops.eleResponse(e,'section',1,'deformation'))}
                        for e in ops.getEleTags()}}


def probe_tangent(ops, output: str | Path, *, event_id: str, modes: int=2):
    """Standard K eigenpairs, not vibration frequencies; never advances a step.

    Missing PythonSparse support is reported separately from an assembly/solver
    error. The physical before/after comparison also runs on failed probes.
    """
    from scipy.sparse import csr_matrix, save_npz
    from scipy.sparse.linalg import eigsh
    output=Path(output)
    if output.exists():
        raise FileExistsError(f'Probe output already exists: {output}')
    if isinstance(modes,bool) or not isinstance(modes,int) or modes<1:
        raise ValueError('modes must be a positive integer')
    output.mkdir(parents=True,exist_ok=False)
    before=physical_snapshot(ops)
    callback_called=False

    class Solver:
        def solve(self,**kw):
            nonlocal callback_called
            callback_called=True
            n=kw['num_eqn']
            matrix=csr_matrix((np.frombuffer(kw['k_values'],dtype=np.float64).copy(),
                               np.frombuffer(kw['indices'],dtype=np.int32).copy(),
                               np.frombuffer(kw['index_ptr'],dtype=np.int32).copy()),shape=(n,n))
            k=kw['num_modes']
            save_npz(output/'tangent.npz',matrix)
            if n<=40 or k>=n:
                values,vectors=np.linalg.eigh(matrix.toarray())
                indices=np.argsort(np.abs(values))[:k]
                values,vectors=values[indices],vectors[:,indices]
            else:
                values,vectors=eigsh(matrix,k=k,sigma=0,which='LM',v0=np.ones(n),tol=1e-10)
            order=np.argsort(values)
            values,vectors=values[order],vectors[:,order]
            np.frombuffer(kw['eigenvalues'],dtype=np.float64)[:]=values
            np.frombuffer(kw['eigenvectors'],dtype=np.float64)[:]=vectors.T.ravel()

    report={'schema':'otw2.tangent_probe.v1','event_id':str(event_id),
            'interpretation':'standard_stiffness_eigenvalues_not_vibration_frequencies'}
    try:
        report['eigenvalues']=list(ops.eigen('standard','PythonSparse',modes,{'solver':Solver(),'scheme':'CSR'}))
        report['status']='completed' if callback_called else 'capability_unavailable'
        if not callback_called:
            report['reason']='PythonSparse solver callback was not invoked'
    except (AttributeError,NotImplementedError) as error:
        report.update(status='capability_unavailable',reason=str(error))
    except Exception as error:
        report.update(status='probe_error',reason=f'{type(error).__name__}: {error}')
    after=physical_snapshot(ops)
    report['physical_state_unchanged']=before==after
    report['node_dofs']={str(n):list(ops.nodeDOFs(n)) for n in ops.getNodeTags()}
    report['physical_state_before']=before
    if not report['physical_state_unchanged']:
        report['status']='physical_state_changed'
    (output/'probe.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


def selected_event(stage_id: str, events, *, stages=(), kinds=()):
    """Select by explicit protocol stage or recorded local event kind."""
    return stage_id in set(stages) or any(e.get('kind') in set(kinds) for e in events)
