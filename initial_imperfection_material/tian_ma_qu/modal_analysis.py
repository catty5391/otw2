"""Gravity-equilibrated, undamped modal screening of the existing one-tower model."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import openseespy.opensees as ops

from model.tower_model_with_tian_ma_qu import OpenSeesModelWithTianMaQu
from initial_imperfection_material.full_tower_cyclic import _apply_gravity
from util.analysis.equilibrium_checks import static_equilibrium
from .directional_loading import attach_explicit_lines, verification_config
from .wind_angle_verification import write_json

ROOT=Path(__file__).resolve().parents[2]


class CheckedSparseSolver:
    """Official PythonSparse interface; no stiffness/mass perturbation.

    A larger Lanczos subspace handles the many nearly repeated cable modes.
    Save assembled equations to independently check K phi = lambda M phi.
    """
    def solve(self,**v):
        from scipy.sparse import csr_matrix
        from scipy.sparse.linalg import eigsh
        n,k=v["num_eqn"],v["num_modes"]
        pointers=np.frombuffer(v["index_ptr"],np.int32).copy()
        indices=np.frombuffer(v["indices"],np.int32).copy()
        self.K=csr_matrix((np.frombuffer(v["k_values"],float).copy(),indices,pointers),shape=(n,n))
        self.M=csr_matrix((np.frombuffer(v["m_values"],float).copy(),indices,pointers),shape=(n,n))
        self.settings={"method":"scipy eigsh shift-invert sigma=0","tol":1e-10,"maxiter":10000,
                       "ncv":min(n,max(4*k+1,40)),"v0_seed":20261023,"num_equations":n}
        values,vectors=eigsh(self.K,k=k,M=self.M,sigma=0,which="LM",tol=1e-10,maxiter=10000,
            ncv=self.settings["ncv"],v0=np.random.default_rng(20261023).normal(size=n))
        order=values.argsort();self.values=values[order];self.vectors=vectors[:,order]
        np.frombuffer(v["eigenvalues"],float)[:]=self.values
        np.frombuffer(v["eigenvectors"],float)[:]=self.vectors.T.ravel()
        kv=self.K@self.vectors;mv=(self.M@self.vectors)*self.values
        self.residuals=np.linalg.norm(kv-mv,axis=0)/(np.linalg.norm(kv,axis=0)+np.linalg.norm(mv,axis=0))


def modal_metrics(vectors,mass,fixed,tower_mass,line_mass):
    """Full nodal DOFs; all elements in this model have zero element mass.

    Effective masses are for uniform translational support excitation. They
    are not mode participation under the spatially distributed wind pattern.
    Component kinetic shares split actual mass, including shared hang nodes.
    """
    vectors=np.asarray(vectors,float);mass=np.asarray(mass,float)
    if vectors.ndim!=3 or vectors.shape[1:]!=mass.shape or mass.shape[1]!=6:
        raise ValueError("expected modes x nodes x 6 and nodal diagonal masses")
    if not np.isfinite(vectors).all() or not np.isfinite(mass).all() or np.any(mass<0):
        raise ValueError("finite vectors and nonnegative diagonal mass required")
    if np.any(np.asarray(tower_mass)+np.asarray(line_mass)>mass+1e-8):
        raise ValueError("component mass exceeds assembled mass")
    free=mass*np.logical_not(fixed)
    gm=np.einsum('mnd,nd,mnd->m',vectors,free,vectors)
    if np.any(gm<=0):raise ValueError("mode has no positive generalized mass")
    normalized=vectors/np.sqrt(gm)[:,None,None]
    gram=np.einsum('ind,nd,jnd->ij',normalized,free,normalized)
    directional=np.einsum('mnd,nd,mnd->md',normalized,free,normalized)[:,:3]
    participation=np.einsum('mnd,nd->md',normalized,free)[:,:3]
    effective=participation**2
    free_total=free.sum(axis=0)[:3]
    ratios=np.divide(effective,free_total,out=np.zeros_like(effective),where=free_total>0)
    tower=np.einsum('mnd,nd,mnd->m',normalized,np.asarray(tower_mass)*np.logical_not(fixed),normalized)
    cable=np.einsum('mnd,nd,mnd->m',normalized,np.asarray(line_mass)*np.logical_not(fixed),normalized)
    return {"vectors":normalized,"generalized_mass_raw":gm,"gram":gram,
        "directional_kinetic_share":directional,"participation":participation,
        "effective_mass":effective,"mass_ratios":ratios,"free_mass":free_total,
        "tower_kinetic_share":tower,"cable_kinetic_share":cable,"insulator_kinetic_share":1-tower-cable}


def weighted_mac(reference,candidate,mass):
    """Scale/sign invariant MAC on a common set of tower translational DOFs."""
    a,b,w=(np.asarray(v,float).ravel() for v in (reference,candidate,mass))
    aa,bb=np.dot(w*a,a),np.dot(w*b,b)
    return float(np.dot(w*a,b)**2/(aa*bb)) if aa>0 and bb>0 else 0.


def run_case(output,*,segments=0,modes=160,solver="scipy"):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError(output)
    if isinstance(modes,bool) or int(modes)!=modes or not 1<=modes<=300:
        raise ValueError("modes must be an integer in [1,300]")
    if isinstance(segments,bool) or int(segments)!=segments or segments not in (0,) and not 2<=segments<=200:
        raise ValueError("segments must be 0 for bare tower, or an integer in [2,200]")
    if solver not in {"scipy","arpack"}:raise ValueError("unknown eigen solver")
    output.mkdir(parents=True,exist_ok=True);started=time.monotonic();ops.wipe()
    s={"schema_version":1,"analysis":"gravity_tangent_modal_screening","status":"running",
       "segments_per_span":segments,"requested_modes":modes,"state":"zero wind; gravity equilibrated; conductor initial force retained",
       "validated_for_design":False,"engine_version":ops.version(),
       "mass_model":"nodal lumped translational mass only; no element mass or nodal rotational inertia",
       "source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
           Path(__file__),ROOT/"Source/Z30103A6.s2k",ROOT/"model/tower_model_with_tian_ma_qu.py",
           Path(__file__).with_name("directional_loading.py"),ROOT/"model/tower_line_system_model.py",
           ROOT/"model/.config/conductor_catalog.json",ROOT/"model/.config/tower_line_with_insulators.json")}}
    write_json(output/"summary.json",s)
    try:
        model=OpenSeesModelWithTianMaQu(ROOT/"Source/Z30103A6.s2k",output_dir=output/"model_data")
        model.model_tower();tower_nodes=set(model.node_map)
        original_mass={n:np.array(ops.nodeMass(n),float) for n in tower_nodes}
        system=None
        if segments:
            system,meta=attach_explicit_lines(model,output/"line_model",verification_config(0,mode="tower_line_explicit",line_segments=segments))
            s["line_model"]=meta
        tags=sorted(model.node_map);index={n:i for i,n in enumerate(tags)}
        mass=np.array([ops.nodeMass(n) for n in tags],float)
        tower_mass=np.array([original_mass.get(n,np.zeros(6)) for n in tags])
        line_mass=np.zeros_like(mass)
        if system:
            for line in system.transmission_line_map.values():
                ns=line["node_tags"];xyz=np.array([ops.nodeCoord(n) for n in ns])
                weights=np.linalg.norm(np.diff(xyz,axis=0),axis=1)*line["mass_per_length"]
                for a,b,w in zip(ns,ns[1:],weights):
                    line_mass[index[a],:3]+=w/2;line_mass[index[b],:3]+=w/2
        fixed=np.zeros_like(mass,dtype=bool)
        for n,record in model.fix_map.items():
            fixed[index[n]]=[bool(record[k]) for k in ("ux","uy","uz","rx","ry","rz")]
        gravity=_apply_gravity(model,steps=50 if system else 10)
        xyz=np.array([ops.nodeCoord(n) for n in tags],float)
        displacement=np.array([ops.nodeDisp(n) for n in tags],float)
        loads={(n,d):float(v) for n,values in gravity.node_loads.items() for d,v in enumerate(values,1)}
        constraints={(n,d+1) for n,row in zip(tags,fixed) for d,v in enumerate(row) if v}
        eq=static_equilibrium(ops,loads,constrained_dofs=constraints,
            rotational_dofs={(n,d) for n in tags for d in (4,5,6)},
            force_scale=gravity.total_mass*9.81,moment_scale=gravity.total_mass*9.81*39.6,
            relative_tolerance=1e-6,force_absolute_tolerance=.001,moment_absolute_tolerance=.001)
        eq.pop("free_dof_residuals");s["gravity_equilibrium"]=eq
        if not eq["passed"]:raise RuntimeError("gravity equilibrium audit failed")
        states=model.committed_member_states()
        s["gravity_buckled_members"]=sum(v["buckling_count"]>0 for v in states)
        s["gravity_tension_yield_members"]=sum(v["tension_yield_ever"] for v in states)
        s["gravity_total_mass_kg"]=gravity.total_mass
        s["node_count"]=len(tags);s["element_count"]=len(ops.getEleTags())
        tensions=[]
        if system:
            for name,line in system.transmission_line_map.items():
                forces=[float(ops.eleResponse(t,"axialForce")[0]) for t in line["element_tags"]]
                tensions.append({"line_id":name,"min_tension_N":min(forces),"max_tension_N":max(forces)})
        s["cable_gravity_tensions"]=tensions
        print(f"Gravity ready: segments={segments}, mass={gravity.total_mass:.3f} kg; eigen({modes})",flush=True)
        checked=CheckedSparseSolver() if solver=="scipy" else None
        eigenvalues=np.asarray(ops.eigen("PythonSparse",int(modes),{"solver":checked,"scheme":"CSR"}) if checked else ops.eigen("-genBandArpack",int(modes)),float)
        if len(eigenvalues)!=modes or np.any(eigenvalues<=0) or not np.isfinite(eigenvalues).all() or np.any(np.diff(eigenvalues)<-1e-10):
            raise RuntimeError("missing/nonpositive eigenvalues; do not publish as stable modal solution")
        raw=np.array([[ops.nodeEigenvector(n,m+1) for n in tags] for m in range(modes)])
        native=ops.modalProperties("-return","-file",str(output/"opensees_modal_properties.txt"))
        write_json(output/"opensees_modal_properties.json",native)
        metrics=modal_metrics(raw,mass,fixed,tower_mass,line_mass)
        normalized=metrics["vectors"];frequencies=np.sqrt(eigenvalues)/(2*math.pi)
        ratios=metrics["mass_ratios"];cum=ratios.cumsum(axis=0)
        orthogonal_error=float(np.max(np.abs(metrics["gram"]-np.eye(modes))))
        native_error=max(float(np.max(np.abs(100*ratios[:,d]-native[f"partiMassRatiosM{axis}"]))) for d,axis in enumerate("XYZ"))
        invariant=max(float(np.max(np.abs(np.array([ops.nodeDisp(n) for n in tags])-displacement))),
                      float(abs(ops.getTime())))
        s.update(solver="PythonSparse/SciPy" if checked else "genBandArpack",orthogonality_max_error=orthogonal_error,
                 participation_native_max_error_percentage_points=native_error,
                 eigen_analysis_displacement_or_time_change=invariant,
                 total_mass_XYZ_kg=mass.sum(axis=0)[:3].tolist(),free_mass_XYZ_kg=metrics["free_mass"].tolist(),
                 component_total_mass_kg={"tower":float(tower_mass[:,0].sum()),"cable":float(line_mass[:,0].sum()),
                                          "insulator":float((mass-tower_mass-line_mass)[:,0].sum())},
                 cumulative_mass_ratio_XYZ=cum[-1].tolist())
        mode_rows=[]
        for m,f in enumerate(frequencies):
            t,c=float(metrics["tower_kinetic_share"][m]),float(metrics["cable_kinetic_share"][m])
            kind="tower_dominated" if t>=.6 else "cable_attachment_dominated" if t<=.1 else "mixed"
            direction="XYZ"[int(np.argmax(metrics["directional_kinetic_share"][m]))]
            row=dict(mode=m+1,frequency_Hz=float(f),period_s=float(1/f),classification=kind,
                     dominant_translation=direction,tower_kinetic_share=t,cable_kinetic_share=c,
                     insulator_kinetic_share=float(metrics["insulator_kinetic_share"][m]),
                     native_effective_mass_ratio_RZ=float(native["partiMassRatiosRMZ"][m])/100)
            for d,axis in enumerate("XYZ"):
                row[f"effective_mass_{axis}_kg"]=float(metrics["effective_mass"][m,d])
                row[f"effective_mass_ratio_{axis}"]=float(ratios[m,d])
                row[f"cumulative_mass_ratio_{axis}"]=float(cum[m,d])
                row[f"kinetic_share_{axis}"]=float(metrics["directional_kinetic_share"][m,d])
            mode_rows.append(row)
        with (output/"modes.csv").open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(mode_rows[0]));w.writeheader();w.writerows(mode_rows)
        edges=[]
        for tag in ops.getEleTags():
            a,b=ops.eleNodes(tag)
            group="tower" if tag in model.element_map else "cable" if system and system.element_map[tag].get("component")=="transmission_line" else "insulator"
            edges.append([index[a],index[b],group])
        np.savez_compressed(output/"eigenvectors.npz",node_tags=tags,initial_coordinates=xyz,
            gravity_displacements=displacement,gravity_coordinates=xyz+displacement[:,:3],
            mass=mass,fixed=fixed,tower_mass=tower_mass,line_mass=line_mass,
            eigenvalues=eigenvalues,vectors=normalized,raw_vectors=raw)
        write_json(output/"geometry.json",{"nodes":[{"tag":n,"position":list(x),"tower":n in tower_nodes} for n,x in zip(tags,xyz+displacement[:,:3])],"edges":edges})
        s["modes"]=mode_rows
        s["checks_passed"]=orthogonal_error<1e-6 and native_error<1e-6 and invariant<1e-12 and bool(np.all(cum[-1]<=1+1e-6))
        if checked:
            from scipy.sparse import save_npz
            save_npz(output/"stiffness.npz",checked.K);save_npz(output/"mass.npz",checked.M)
            np.savez_compressed(output/"equation_modes.npz",values=checked.values,vectors=checked.vectors,
                node_dofs=np.array([ops.nodeDOFs(n) for n in tags]),node_tags=tags)
            s["solver_settings"]=checked.settings
            s["eigen_equation_relative_residual_max"]=float(checked.residuals.max())
            s["checks_passed"]=s["checks_passed"] and s["eigen_equation_relative_residual_max"]<1e-5
        s["status"]="complete" if s["checks_passed"] else "review_required"
        print(f"Frequencies first six={frequencies[:6]}; orthogonality={orthogonal_error:.3g}",flush=True)
    except Exception as e:
        s.update(status="error",error=f"{type(e).__name__}: {e}");raise
    finally:
        s["runtime_seconds"]=time.monotonic()-started;write_json(output/"summary.json",s);ops.wipe()
    return s


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--segments",type=int,default=20);p.add_argument("--modes",type=int,default=160)
    p.add_argument("--solver",choices=("scipy","arpack"),default="scipy")
    a=p.parse_args();s=run_case(a.output,segments=a.segments,modes=a.modes,solver=a.solver)
    raise SystemExit(0 if s["status"]=="complete" else 2)


if __name__=="__main__":main()
