"""Run one fresh OpenSees tower: gravity -> dry wind -> additional rain.

This verifies integration of the rain load, not the calibrated tower wind
capacity. Both air and rain use the same explicit member breadth/normal-flow
proxy; this differs from the previous panel/yaw pushover load convention.
"""
from __future__ import annotations
import argparse,csv,json,math,time,hashlib
from pathlib import Path
import numpy as np
from .physics import (marshall_palmer,drop_velocity,cylinder_line_load,
                      dry_cylinder_line_load,distribute_members)

ROOT=Path(__file__).resolve().parents[1]


def tower_geometry(output):
    from model.tower_model_with_buckling import OpenSeesModelWithBuckling
    model=OpenSeesModelWithBuckling(ROOT/'Source/Z30103A6.s2k',output_dir=output,
        random_disp_ratio=.001,member_divisions=4,imperfection_seed=30103)
    nodes={n:tuple(r[k] for k in 'xyz') for n,r in model._parse_node_coordinates().items()}
    assignments=model._element_section_assignments()
    members=[]
    for tag,r in model._parse_element_connectivity().items():
        leg,_=model._l_section_dimensions(assignments[tag]['section_name'])
        members.append(dict(tag=tag,node_i=r['node_i'],node_j=r['node_j'],breadth_m=leg))
    return model,nodes,members


def save_json(path,obj):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    tmp.replace(path)


def run(output,angle,steps=10):
    import openseespy.opensees as ops
    from initial_imperfection_material.full_tower_cyclic import _apply_gravity
    from util.processing.nodal_loads import apply_nodal_loads,merge_nodal_loads,current_nodal_loads
    from util.processing.directional_wind import nodal_resultant
    from util.analysis.equilibrium_checks import static_equilibrium
    output=Path(output)
    if output.exists() and (output/'summary.json').exists():
        raise FileExistsError(f"Refuse to overwrite completed/attempted run: {output}")
    output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();ops.wipe()
    summary=dict(angle_deg=angle,wind_m_s=30.,rain_mm_h=100.,horizontal_velocity_ratio=1.,
        status='running',physical_validation=False,material='Steel02',divisions=4,
        imperfection_ratio=.001,imperfection_seed=30103,model='single tower only',
        source_sha256=hashlib.sha256((ROOT/'Source/Z30103A6.s2k').read_bytes()).hexdigest(),
        wind_model='uniform flow, member breadth normal-cylinder proxy, Cd=1',
        rain_model='rain-rate-closed MP, projected collector, gamma=1',
        limitations=['Angle leg breadth is an uncalibrated cylinder proxy; no shielding or wet Cd.',
          'Static load mapping, not tower-line transient analysis or a wet design capacity.'],states=[])
    save_json(output/'summary.json',summary)
    try:
        model,nodes,members=tower_geometry(output/'model_data')
        print(f'angle={angle}: building Steel02 tower',flush=True)
        model.model_tower()
        print(f'angle={angle}: gravity',flush=True)
        gravity=_apply_gravity(model,steps=10)
        base={n:np.array(ops.nodeDisp(n)[:3]) for n in nodes}
        direction=np.array([math.cos(math.radians(angle)),math.sin(math.radians(angle)),0.])
        u=30*direction;s=marshall_palmer(100,normalize_rain_rate=True);v=drop_velocity(s,u)
        dry,_,dryaudit=distribute_members(nodes,members,lambda a,b:dry_cylinder_line_load(u,a,b))
        wet,_,wetaudit=distribute_members(nodes,members,lambda a,b:cylinder_line_load(s,v,a,b))
        summary.update(original_nodes=len(nodes),physical_members=len(members),
            fe_nodes=len(ops.getNodeTags()),fe_elements=len(ops.getEleTags()),
            wind_resultant=dryaudit,rain_resultant=wetaudit,engine=ops.version())
        with (output/'loads.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['node','wind_Fx_N','wind_Fy_N','wind_Fz_N','rain_Fx_N','rain_Fy_N','rain_Fz_N'])
            for n in sorted(set(dry)|set(wet)):w.writerow([n,*dry.get(n,(0,)*6)[:3],*wet.get(n,(0,)*6)[:3]])

        def capture(label,external):
            ops.reactions()
            reactions={n:tuple(ops.nodeReaction(n)) for n in model.fix_map}
            current={n:np.array(ops.nodeCoord(n)[:3])+np.array(ops.nodeDisp(n)[:3]) for n in ops.getNodeTags()}
            er=nodal_resultant(current,external);rr=nodal_resultant(current,reactions)
            force_error=max(abs(a+b) for a,b in zip(er['force_N'],rr['force_N']))
            moment_error=max(abs(a+b) for a,b in zip(er['moment_Nm'],rr['moment_Nm']))
            ledger={(n,d):value for n,vec in external.items() for d,value in enumerate(vec,1)}
            constrained={(n,d) for n,fix in model.fix_map.items() for d,key in enumerate(('ux','uy','uz','rx','ry','rz'),1) if fix[key]}
            scale=max(1.,sum(abs(v) for (n,d),v in ledger.items() if d<=3))
            eq=static_equilibrium(ops,ledger,constrained_dofs=constrained,
                rotational_dofs={(n,d) for n in ops.getNodeTags() for d in (4,5,6)},
                force_scale=scale,moment_scale=scale*39.6,relative_tolerance=1e-6,
                force_absolute_tolerance=.001,moment_absolute_tolerance=.001)
            eq.pop('free_dof_residuals',None)
            dis=np.array(ops.nodeDisp(350)[:3])-base[350]
            row=dict(stage=label,rain_mm_h=0. if label=='wind_only' else 100.,
                ux_mm=float(dis[0]*1000),uy_mm=float(dis[1]*1000),uz_mm=float(dis[2]*1000),
                along_wind_mm=float(dis@direction*1000),control_node=350,control_height_m=36.4,
                external_force_N=er['force_N'],external_moment_Nm=er['moment_Nm'],
                reactions_force_N=rr['force_N'],reactions_moment_Nm=rr['moment_Nm'],
                force_balance_error_N=force_error,moment_balance_error_Nm=moment_error,
                equilibrium=eq,equilibrium_passed=bool(eq['passed'] and force_error<.1 and moment_error<1.))
            summary['states'].append(row);save_json(output/'summary.json',summary)
            if not row['equilibrium_passed']:raise RuntimeError(f'{label}: equilibrium check failed')

        def advance(loads,label):
            handle=apply_nodal_loads(loads,model.tag_manager,ops,name=label)
            ops.wipeAnalysis();ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
            ops.test('NormDispIncr',1e-9,80,0);ops.algorithm('Newton');ops.integrator('LoadControl',1./steps);ops.analysis('Static')
            for k in range(steps):
                code=ops.analyze(1)
                if code!=0:
                    summary.update(failed_stage=label,failed_increment=k+1,return_code=code)
                    raise RuntimeError(f'{label} increment {k+1}: {code}')
            return handle

        print(f'angle={angle}: dry wind',flush=True)
        wind_handle=advance(dry,'wind_only')
        capture('wind_only',merge_nodal_loads(gravity.node_loads,current_nodal_loads(wind_handle,ops_module=ops)))
        ops.loadConst('-time',0.)
        print(f'angle={angle}: add rain',flush=True)
        rain_handle=advance(wet,'wind_and_rain')
        capture('wind_and_rain',merge_nodal_loads(gravity.node_loads,current_nodal_loads(wind_handle,rain_handle,ops_module=ops)))
        a,b=summary['states'];summary['rain_displacement_increase_percent']=(b['along_wind_mm']/a['along_wind_mm']-1)*100
        summary['status']='completed'
    except Exception as exc:
        summary['status']='failed';summary['error']=repr(exc)
        raise
    finally:
        summary['runtime_seconds']=time.monotonic()-started;save_json(output/'summary.json',summary);ops.wipe()
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--angle',type=float,required=True)
    args=p.parse_args();run(args.output,args.angle)
