"""Isolated TMQ identification: explicit ordered data, real GA, bounded evidence.

No production material defaults are changed. A synthetic recovery check is
not experimental validation; a peak-only fit identifies phi, not a cyclic law.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from .material import TMQParameters, TianMaQuPrototype
from .cases import literature_cases

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = MODULE/"followup_results/parameter_identification_20261026"
KIP_N = 4448.2216152605
KSI_PA = 6894757.293168


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def write_csv(path, rows):
    if not rows: raise ValueError("Cannot publish an empty evidence table")
    with Path(path).open("w", newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


@dataclass(frozen=True)
class Bound:
    name: str
    lower: float
    upper: float
    scale: str = "linear"

    def __post_init__(self):
        if self.scale not in {"linear","log"} or not all(map(math.isfinite,(self.lower,self.upper))) or self.lower>=self.upper:
            raise ValueError("Finite increasing bounds and linear/log scale required")
        if self.scale=="log" and self.lower<=0:raise ValueError("Log bounds must be positive")

    def value(self, normalized):
        if not math.isfinite(normalized) or not 0<=normalized<=1:raise ValueError("Normalized gene outside [0,1]")
        if self.scale=="log":return math.exp(math.log(self.lower)+normalized*math.log(self.upper/self.lower))
        return self.lower+normalized*(self.upper-self.lower)

    def coordinate(self, value):
        if not self.lower<=value<=self.upper:raise ValueError("Value outside frozen bounds")
        return math.log(value/self.lower)/math.log(self.upper/self.lower) if self.scale=="log" else (value-self.lower)/(self.upper-self.lower)


def decode(template, bounds, genes):
    if len(bounds)!=len(genes) or len({b.name for b in bounds})!=len(bounds):raise ValueError("Distinct parameter names and matching genes required")
    allowed=set(TMQParameters.__dataclass_fields__)-{"provenance"}
    if any(b.name not in allowed for b in bounds):raise ValueError("Unknown fit parameter")
    return replace(template, **{b.name:b.value(float(g)) for b,g in zip(bounds,genes)})


def ordered_data(manifest):
    """Validate actual time order; never sort a loop by displacement or force."""
    if manifest.get("schema")!="otw2.tmq_ordered_history.v1":raise ValueError("Unsupported ordered-history schema")
    if manifest.get("ordered") is not True or not manifest.get("ordering_evidence"):
        raise ValueError("A labelled loading order is mandatory; an unordered loop image is not a time history")
    if manifest.get("data_kind") not in {"experiment","numerical_reference","synthetic_same_model"}:
        raise ValueError("Explicit evidence kind required")
    for key in ("source","specimen_id","geometry_basis","material_property_basis"):
        if not isinstance(manifest.get(key),str) or not manifest[key].strip():raise ValueError(f"Missing {key}")
    for key in ("elastic_modulus_Pa","yield_stress_Pa"):
        value=float(manifest[key])
        if not math.isfinite(value) or value<=0:raise ValueError(f"Positive finite {key} required")
    if manifest.get("initial_state")!="virgin_zero_load":raise ValueError("Only independently initialized zero-load histories are supported")
    length=float(manifest["length_m"]);area=float(manifest["area_m2"])
    if not math.isfinite(length+area) or min(length,area)<=0:raise ValueError("Positive finite measured/declared geometry required")
    units=manifest["units"];uf={"m":1.,"mm":.001};ff={"N":1.,"kN":1000.,"kip":KIP_N}
    if units.get("displacement") not in uf or units.get("force") not in ff or units.get("sign")!="tension_positive":
        raise ValueError("Explicit supported units and tension-positive convention required")
    samples=manifest["samples"]
    if len(samples)<3:raise ValueError("At least three ordered samples required")
    seq=np.array([r["sequence"] for r in samples],float)
    if not np.isfinite(seq).all() or np.any(np.diff(seq)<=0):raise ValueError("Sequence IDs must increase strictly")
    displacement=np.array([r["displacement"] for r in samples],float)*uf[units["displacement"]]
    force=np.array([r["force"] for r in samples],float)*ff[units["force"]]
    if not np.isfinite(displacement).all() or not np.isfinite(force).all() or abs(displacement[0])>1e-12:
        raise ValueError("Finite histories starting at undeformed displacement zero required")
    force_tolerance=float(manifest.get("initial_force_tolerance_N",1e-3))
    if not math.isfinite(force_tolerance) or force_tolerance<0 or abs(force[0])>force_tolerance:
        raise ValueError("Initial force incompatible with declared virgin zero-load state")
    if "time" in samples[0]:
        t=np.array([r["time"] for r in samples],float)
        if not np.isfinite(t).all() or np.any(np.diff(t)<=0):raise ValueError("Physical time must increase")
    segment=np.array([r.get("segment",0) for r in samples])
    weights=np.zeros(len(samples))
    for label in np.unique(segment):weights[segment==label]=1./np.count_nonzero(segment==label)
    weights/=weights.sum()
    return {"manifest":manifest,"length_m":length,"area_m2":area,"displacement_m":displacement,
            "strain":displacement/length,"force_N":force,"weights":weights,"sequence":seq}


def response(parameters, strains):
    material=TianMaQuPrototype(parameters);stress=[]
    for strain in strains:
        material.set_trial_strain(float(strain));stress.append(material.get_stress());material.commit_state()
    return np.array(stress)


def normalized_residual(parameters, data):
    calculated=response(parameters,data["strain"])*data["area_m2"]
    scale=max(float(max(abs(data["force_N"]))),1.)
    return (calculated-data["force_N"])*np.sqrt(data["weights"])/scale


def identification_provenance(manifest, fitted_names):
    """Label fitted parameters by their evidence, not the starting template."""
    return (f"GA + least_squares identification; data_kind={manifest['data_kind']}; "
            f"specimen_id={manifest['specimen_id']}; source={manifest['source']}; "
            f"fitted_parameters={','.join(fitted_names)}; non-production candidate; "
            "independent physical validation not completed")


def publish_history_fit(output, data, fit):
    """Export complete ordered observations/predictions without trimming failures."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output=Path(output);parameters=TMQParameters(**fit['best_parameters'])
    force=response(parameters,data['strain'])*data['area_m2']
    write_csv(output/'ordered_predictions.csv',[
        {'sequence':int(i),'displacement_m':float(u),'observed_force_N':float(o),'fitted_force_N':float(f)}
        for i,u,o,f in zip(data['sequence'],data['displacement_m'],data['force_N'],force)])
    write_csv(output/'ga_history.csv',[{'seed':run['ga']['seed'],**row} for run in fit['runs'] for row in run['ga']['history']])
    fig,axes=plt.subplots(1,2,figsize=(12,4.5))
    axes[0].plot(data['displacement_m']*1000,data['force_N']/1000,'k-',label='Declared ordered observations')
    axes[0].plot(data['displacement_m']*1000,force/1000,'--',label='GA + local refinement')
    axes[0].set(xlabel='End displacement (mm)',ylabel='Axial force (kN)',title='Complete ordered hysteresis')
    axes[1].plot(data['sequence'],data['force_N']/1000,'k-',label='Declared ordered observations')
    axes[1].plot(data['sequence'],force/1000,'--',label='GA + local refinement')
    axes[1].set(xlabel='Original sequence',ylabel='Axial force (kN)',title='Preserved loading order')
    for axis in axes:axis.grid(alpha=.25);axis.legend(fontsize=8)
    fig.suptitle(f"{fit['data_kind']} | fitted history; independent physical validation still required")
    fig.tight_layout()
    for ext in ('png','svg','pdf'):fig.savefig(output/f'ordered_history_fit.{ext}',dpi=160,bbox_inches='tight')
    plt.close(fig)


def genetic_minimize(objective, dimension, *, seed, population=32, generations=40,
                     elite=2, mutation_probability=.25, timeout_seconds=120., initial_genes=None):
    """Real-coded GA: tournament selection, blend crossover, Gaussian mutation.

    Unit-cube genes enforce fixed bounds. Elites survive without mutation.
    This is not differential evolution and is not claimed to reproduce the
    original authors' undisclosed optimizer settings.
    """
    if dimension<1 or population<6 or not 1<=elite<population or generations<1:
        raise ValueError("Invalid GA dimensions/population/generations")
    if not 0<=mutation_probability<=1 or timeout_seconds<=0:raise ValueError("Invalid GA controls")
    rng=np.random.default_rng(seed);pool=rng.random((population,dimension))
    if initial_genes is not None:
        initial_genes=np.asarray(initial_genes,float)
        if initial_genes.shape!=(dimension,) or not np.isfinite(initial_genes).all() or np.any((initial_genes<0)|(initial_genes>1)):
            raise ValueError("Initial candidate must satisfy frozen bounds")
        pool[0]=initial_genes
    started=time.monotonic();cache={};history=[];best_value=float("inf");best_genes=None;timed_out=False
    for generation in range(generations+1):
        scores=[]
        for genes in pool:
            if time.monotonic()-started>timeout_seconds:timed_out=True;break
            key=tuple(genes)
            if key not in cache:
                try:value=float(objective(genes))
                except (ValueError,ArithmeticError,RuntimeError):value=float("inf")
                cache[key]=value if math.isfinite(value) else float("inf")
            scores.append(cache[key])
        if not scores:break
        evaluated=pool[:len(scores)];scores=np.asarray(scores);order=np.argsort(scores)
        if scores[order[0]]<best_value:best_value=float(scores[order[0]]);best_genes=evaluated[order[0]].copy()
        if not math.isfinite(best_value):raise ValueError("No admissible finite candidate in population")
        history.append({"generation":generation,"best_objective":best_value,"evaluations":len(cache),"elapsed_seconds":time.monotonic()-started})
        if timed_out or generation==generations:break
        ranked=evaluated[order];children=[g.copy() for g in ranked[:elite]]
        def select():
            ids=rng.integers(0,len(scores),3);return evaluated[ids[np.argmin(scores[ids])]]
        sigma=.12*(1-generation/generations)+.015
        while len(children)<population:
            left,right=select(),select();blend=rng.uniform(-.15,1.15,dimension)
            child=blend*left+(1-blend)*right
            mask=rng.random(dimension)<mutation_probability
            child[mask]+=rng.normal(0,sigma,int(mask.sum()))
            children.append(np.clip(child,0.,1.))
        pool=np.array(children)
    if best_genes is None:raise TimeoutError("GA budget exhausted before any admissible evaluation")
    return {"genes":best_genes.tolist(),"objective":best_value,"seed":seed,"history":history,
            "evaluations":len(cache),"timed_out":timed_out,"elapsed_seconds":time.monotonic()-started,
            "algorithm":"real-coded genetic algorithm; tournament-3, blend crossover, Gaussian mutation, elitism"}


def fit_ordered_history(data, template, bounds, *, seeds=(17,29,43), population=28, generations=35, timeout_seconds=100.):
    from scipy.optimize import least_squares
    bounds=tuple(bounds);runs=[]
    if not bounds or not seeds:raise ValueError("At least one parameter and one independent seed required")
    for parameter,key in (("elastic_modulus","elastic_modulus_Pa"),("yield_stress","yield_stress_Pa")):
        if parameter not in {b.name for b in bounds} and not math.isclose(getattr(template,parameter),data['manifest'][key],rel_tol=1e-9):
            raise ValueError(f"Fixed {parameter} differs from declared data properties")
    # Rectangular search bounds must preserve coupled constraints, including
    # finite-difference steps during the separately labelled local refinement.
    limits={b.name:(b.lower,b.upper) for b in bounds}
    mu=limits.get('mu',(template.mu,template.mu));nu=limits.get('nu',(template.nu,template.nu))
    residual_limit=limits.get('residual_compression_ratio',(template.residual_compression_ratio,)*2)
    gamma=limits.get('gamma',(template.gamma,template.gamma))
    if mu[1]>=nu[0] or residual_limit[1]>=gamma[0]:
        raise ValueError("Search rectangle must preserve nu > mu and residual_compression_ratio < gamma")
    def residual(g):return normalized_residual(decode(template,bounds,g),data)
    def objective(g):
        value=residual(g);return float(np.dot(value,value))
    for seed in seeds:
        ga=genetic_minimize(objective,len(bounds),seed=seed,
                            population=population,generations=generations,timeout_seconds=timeout_seconds)
        # Local refinement is separately labelled; GA-only results remain visible.
        polished=least_squares(residual,ga["genes"],bounds=(np.zeros(len(bounds)),np.ones(len(bounds))),
                               max_nfev=100,ftol=1e-10,xtol=1e-10,gtol=1e-10)
        p=replace(decode(template,bounds,polished.x),
                  provenance=identification_provenance(data['manifest'],[b.name for b in bounds]))
        runs.append({"ga":ga,"local_refinement":{"algorithm":"scipy least_squares after GA", "success":bool(polished.success),
                    "nfev":int(polished.nfev),"objective":float(np.dot(polished.fun,polished.fun)),"genes":polished.x.tolist()},
                    "parameters":p.to_dict()})
    best=min(runs,key=lambda r:r["local_refinement"]["objective"])
    genes=np.array(best["local_refinement"]["genes"]);columns=[]
    for i in range(len(bounds)):
        low=genes.copy();high=genes.copy();low[i]=max(0.,genes[i]-1e-4);high[i]=min(1.,genes[i]+1e-4)
        columns.append((residual(high)-residual(low))/(high[i]-low[i]))
    J=np.column_stack(columns);singular=np.linalg.svd(J,compute_uv=False)
    rank=int(np.count_nonzero(singular>singular[0]*1e-6)) if len(singular) and singular[0]>0 else 0
    result={"schema":"otw2.tmq_parameter_fit.v1","data_kind":data["manifest"]["data_kind"],
            "experimental_validation_complete":False,"whole_tower_applicable":False,
            "bounds":[b.__dict__ for b in bounds],"fitted_parameters":[b.name for b in bounds],
            "template_provenance":template.provenance,
            "fixed_parameters":{k:v for k,v in template.to_dict().items() if k not in {b.name for b in bounds}|{'provenance'}},
            "runs":runs,"best_parameters":best["parameters"],"best_objective":best["local_refinement"]["objective"],
            "local_identifiability":{"normalized_gene_jacobian_singular_values":singular.tolist(),"rank":rank,
                "number_parameters":len(bounds),"condition_number":float(singular[0]/singular[-1]) if rank==len(bounds) else None,
                "scope":"local sensitivity under this protocol, not proof of global uniqueness or physical validity"},
            "parameter_ranges_across_starts":{b.name:[min(r['parameters'][b.name] for r in runs),max(r['parameters'][b.name] for r in runs)] for b in bounds},
            "objective":"segment-balanced mean squared force error / fixed observed peak force squared",
            "source":data["manifest"]["source"],"specimen_id":data["manifest"]["specimen_id"]}
    return result


def identify_peak(feature, *, seed=17):
    """One measured first-compression peak can identify only conditional phi."""
    if feature.get("feature_type")!="first_buckling_peak":
        raise ValueError("A whole-test compression maximum is not automatically the first buckling peak")
    for name in ("specimen_id","source","geometry_basis","yield_basis"):
        if not feature.get(name):raise ValueError(f"Peak feature needs {name}")
    area,fy,peak=(float(feature[k]) for k in ("area_m2","yield_stress_Pa","compression_peak_N"))
    if not all(map(math.isfinite,(area,fy,peak))) or min(area,fy,peak)<=0:raise ValueError("Positive finite feature values required")
    phi=peak/(area*fy)
    if not 0<phi<=1:raise ValueError("Observed peak incompatible with phi in (0,1]; review geometry, units, or model")
    bound=Bound("phi",.01,1.)
    ga=genetic_minimize(lambda g:((area*fy*bound.value(float(g[0]))-peak)/peak)**2,1,seed=seed,population=20,generations=45,timeout_seconds=15.)
    return {**feature,"identified_phi":phi,"ga_phi":bound.value(ga["genes"][0]),"ga_relative_peak_error":math.sqrt(ga["objective"]),
            "ga":ga,"fit_scope":"first buckling peak only; conditional on declared A and fy",
            "unidentified_parameters":["elastic_modulus","rho","alpha","beta","gamma","tau","mu","nu","zeta","eta","theta","kappa"],
            "experimental_full_hysteresis_validation":False,"whole_tower_applicable":False}


def protocol(targets, steps=12):
    strain=[0.];segments=[0]
    if targets[0]!=0:raise ValueError("Protocol must start at zero")
    for index,(a,b) in enumerate(zip(targets,targets[1:]),1):
        if a==b:raise ValueError("Repeated protocol target")
        strain.extend(np.linspace(a,b,steps+1)[1:]);segments.extend([index]*steps)
    return np.array(strain),np.array(segments)


def synthetic_manifest(parameters, targets, *, key, steps=12):
    case=literature_cases()[0];strain,segments=protocol(targets,steps)
    force=response(parameters,strain)*case.area
    return {"schema":"otw2.tmq_ordered_history.v1","data_kind":"synthetic_same_model","ordered":True,
            "ordering_evidence":"explicit saved sequence of an independently initialized declared synthetic protocol",
            "initial_state":"virgin_zero_load","source":"current TMQ prototype synthetic algorithm check; not physical experiment",
            "specimen_id":key,"length_m":case.length,"area_m2":case.area,
            "geometry_basis":"nominal geometry copied from P102 example; synthetic, not a measured new specimen",
            "elastic_modulus_Pa":parameters.elastic_modulus,"yield_stress_Pa":parameters.yield_stress,
            "material_property_basis":"explicit synthetic generating parameters; no independent coupon test",
            "units":{"displacement":"m","force":"N","sign":"tension_positive"},
            "samples":[{"sequence":i,"segment":int(s),"displacement":float(e*case.length),"force":float(f)} for i,(s,e,f) in enumerate(zip(segments,strain,force))]}


def run_synthetic(output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    template=literature_cases()[0].parameters
    truth=replace(template,phi=.74,alpha=.39,beta=.017,gamma=.43,eta=.49)
    train_targets=[0.,.0022,-.0038,.0045,-.006,.0065,-.008,.007,0.]
    holdout_targets=[0.,-.0004,.0003,0.,.003,-.0048,.0058,-.009,.0085,-.003,.002,0.]
    bounds=[Bound('phi',.55,.9),Bound('alpha',.25,.7),Bound('beta',.008,.035,'log'),Bound('gamma',.3,.65),Bound('eta',.35,.65)]
    frozen={'schema':'otw2.tmq_synthetic_identification_plan.v1','data_kind':'synthetic_same_model','physical_validation':'unvalidated',
            'training_targets_strain':train_targets,'heldout_targets_strain':holdout_targets,'truth':truth.to_dict(),
            'bounds':[b.__dict__ for b in bounds],'seeds':[17,29,43],'population':28,'generations':35,
            'local_refinement':'least_squares max_nfev=100; reported separately from GA-only',
            'maximum_seconds_per_GA':100,'new_FE_runs':0,'production_parameters_changed':False,
            'identification_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'material_sha256':hashlib.sha256(Path(__file__).with_name('material.py').read_bytes()).hexdigest()}
    write_json(output/'frozen_plan.json',frozen)
    train=synthetic_manifest(truth,train_targets,key='synthetic_training');held=synthetic_manifest(truth,holdout_targets,key='synthetic_protocol_holdout')
    write_json(output/'training.json',train);write_json(output/'holdout.json',held)
    fit=fit_ordered_history(ordered_data(train),template,bounds)
    best=TMQParameters(**fit['best_parameters']);hd=ordered_data(held)
    residual=normalized_residual(best,hd)
    fit['heldout_protocol']={'kind':'same constitutive implementation, unseen loading protocol; not independent physical evidence',
        'weighted_force_nrmse':float(np.linalg.norm(residual)),'maximum_force_error_N':float(max(abs(response(best,hd['strain'])*hd['area_m2']-hd['force_N'])))}
    fit['truth_parameter_relative_errors']={b.name:abs(getattr(best,b.name)/getattr(truth,b.name)-1) for b in bounds}
    write_json(output/'summary.json',fit)
    histories=[]
    for run in fit['runs']:
        histories.extend({'seed':run['ga']['seed'],**row} for row in run['ga']['history'])
    write_csv(output/'ga_history.csv',histories)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(15,4.5))
    for axis,manifest,label in zip(axes[:2],[train,held],['Synthetic training','Unseen synthetic loading protocol']):
        data=ordered_data(manifest);prediction=response(best,data['strain'])*data['area_m2']
        axis.plot(data['displacement_m']*1000,data['force_N']/1000,color='black',label='Synthetic target')
        axis.plot(data['displacement_m']*1000,prediction/1000,'--',color='#1b799e',label='GA + local refinement')
        axis.set(xlabel='End displacement (mm)',ylabel='Axial force (kN)',title=label);axis.grid(alpha=.25);axis.legend(fontsize=8)
    for run in fit['runs']:
        h=run['ga']['history'];axes[2].semilogy([v['generation'] for v in h],[max(v['best_objective'],1e-16) for v in h],label=f"Seed {run['ga']['seed']}")
    axes[2].set(xlabel='GA generation',ylabel='Normalized force MSE',title='GA-only optimization history');axes[2].legend();axes[2].grid(alpha=.25)
    fig.suptitle('Algorithm recovery check only — same-model synthetic data, NOT experimental calibration');fig.tight_layout()
    for ext in ('png','svg','pdf'):fig.savefig(output/f'synthetic_recovery.{ext}',dpi=160,bbox_inches='tight')
    plt.close(fig)
    return fit


def black_peak_features():
    """Original Black Table 2 peaks; explicitly nominal, not measured, areas."""
    source="https://nehrpsearch.nist.gov/static/files/NSF/PB81154312.pdf"
    double_area=2*.009525*(.1524+.0889-.009525)
    rows=[(8,'double_angle_PP',197.,40.8,double_area,'2L6x3.5x3/8 in; doubled sharp-corner nominal gross area, fillets omitted','Table 2 note b: average coupon yield'),
          (20,'double_angle_PF',180.,40.8,double_area,'2L6x3.5x3/8 in; doubled sharp-corner nominal gross area, fillets omitted','Table 2 note b: average coupon yield'),
          (14,'pipe4_PP',114.,47.5,math.pi*.00602*(.1143-.00602),'nominal standard pipe OD114.3mm,t6.02mm; not measured specimen area','Table 2 note c: first yield in strut test, not independent coupon'),
          (15,'pipe4_PP',110.,47.5,math.pi*.00602*(.1143-.00602),'nominal standard pipe OD114.3mm,t6.02mm; not measured specimen area','Table 2 note c: first yield in strut test, not independent coupon'),
          (24,'pipe3p5_PF',85.,46.3,math.pi*.00574*(.1016-.00574),'nominal standard pipe OD101.6mm,t5.74mm; not measured specimen area','Table 2 note c: first yield in strut test, not independent coupon')]
    return [{'specimen_id':f'Black_1980_{i}_{label}','feature_type':'first_buckling_peak','source':source,
        'source_pages':'Table 1 printed45/PDF59; Table2 printed47/PDF61 (1-based)',
        'original_peak_kip':peak,'original_yield_ksi':fy,'area_m2':area,'yield_stress_Pa':fy*KSI_PA,
        'compression_peak_N':peak*KIP_N,'geometry_basis':geometry,'yield_basis':yield_basis,
        'unit_conversion':'1kip=4448.2216152605N;1ksi=6894757.293168Pa; exact SI, not original rounded conversion',
        'angle_transfer_permitted':False,'measurement_uncertainty':'not supplied; nominal area uncertainty is not quantified'}
        for i,label,peak,fy,area,geometry,yield_basis in rows]


def run_peak_evidence(output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True)
    features=black_peak_features();write_json(output/'features.json',features)
    results=[identify_peak(feature,seed=17) for feature in features]
    result={'schema':'otw2.tmq_peak_identification.v1','cases':results,'physical_validation':'first_peak_feature_only',
            'full_hysteresis_validation':False,'production_parameters_changed':False,
            'area_limitation':'Nominal sharp-angle/annulus areas, not newly measured specimen areas',
            'original_table_conversion':'Original rounded6.89MPa/ksi and4.45kN/kip deliberately not mixed with exact SI'}
    write_json(output/'summary.json',result)
    rows=[{k:r[k] for k in ['specimen_id','original_peak_kip','original_yield_ksi','area_m2','compression_peak_N','yield_stress_Pa','identified_phi','ga_phi','ga_relative_peak_error']} for r in results]
    write_csv(output/'identified_peak_parameters.csv',rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=[str(f['specimen_id']).replace('Black_1980_','') for f in features];x=np.arange(len(features))
    fig,axes=plt.subplots(1,2,figsize=(12,4.5))
    axes[0].bar(x-.18,[r['compression_peak_N']/1000 for r in results],.36,label='Original reported first peak')
    axes[0].bar(x+.18,[r['ga_phi']*r['area_m2']*r['yield_stress_Pa']/1000 for r in results],.36,label='One-parameter GA fit')
    axes[0].set(ylabel='First buckling load (kN)',title='Independent scalar experimental feature');axes[0].legend(fontsize=8)
    axes[1].bar(x,[r['identified_phi'] for r in results],color='#1b799e');axes[1].set(ylabel='phi = Pcr / (nominal A * declared fy)',ylim=(0,1),title='Conditional phi only; no cyclic calibration')
    for axis in axes:axis.set_xticks(x,labels,rotation=18);axis.grid(axis='y',alpha=.2)
    fig.suptitle('Black et al. 1980 | nominal geometry, original force/yield units converted consistently');fig.tight_layout()
    for ext in ('png','svg','pdf'):fig.savefig(output/f'peak_identification.{ext}',dpi=160,bbox_inches='tight')
    plt.close(fig)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('synthetic-check');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('black-peaks');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('fit-history');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('fit-peaks');p.add_argument('--features',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    try:
        if args.command=='synthetic-check':result=run_synthetic(args.output)
        elif args.command=='black-peaks':result=run_peak_evidence(args.output)
        else:
            args.output.mkdir(parents=True)
            if args.command=='fit-history':
                manifest=json.loads(args.manifest.read_text());settings=json.loads(args.settings.read_text())
                write_json(args.output/'input_manifest.json',manifest);write_json(args.output/'input_settings.json',settings)
                data=ordered_data(manifest)
                result=fit_ordered_history(data,TMQParameters(**settings['fixed_and_initial_parameters']),[Bound(**b) for b in settings['bounds']])
                publish_history_fit(args.output,data,result)
            else:
                features=json.loads(args.features.read_text());write_json(args.output/'input_features.json',features)
                result={'schema':'otw2.tmq_peak_identification.v1','cases':[identify_peak(f) for f in features],
                        'physical_validation':'first_peak_feature_only','full_hysteresis_validation':False,'production_parameters_changed':False}
            write_json(args.output/'summary.json',result)
    except Exception as error:
        args.output.mkdir(parents=True,exist_ok=True)
        write_json(args.output/'failure.json',{'schema':'otw2.tmq_identification_failure.v1','command':args.command,
                   'error_type':type(error).__name__,'message':str(error),'production_parameters_changed':False})
        raise
    print(json.dumps({'complete':True,'output':str(args.output),'physical_full_hysteresis_validation':False}))


if __name__=='__main__':main()
