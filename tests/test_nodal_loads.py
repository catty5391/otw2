"""Load installation contracts and real OpenSees equilibrium/dynamics checks."""
import math
import unittest
import numpy as np
from scipy.linalg import expm
import openseespy.opensees as ops
from util.preprocess.tag_manager import TagManager
from util.processing.nodal_loads import (apply_nodal_loads,apply_nodal_load_history,
    current_nodal_loads,remove_nodal_loads,merge_nodal_loads)


class FakeOps:
    def __init__(self,fail_load=None):
        self.calls=[];self.patterns=set();self.series=set();self.factor={};self.current=0.;self.load_count=0;self.fail_load=fail_load
    def getNodeTags(self):return [1,2]
    def nodeDisp(self,n):return (0.,)*3
    def getTime(self):return self.current
    def getPatterns(self):return sorted(self.patterns)
    def getLoadFactor(self,p):return self.factor.get(p,0.)
    def timeSeries(self,*args):
        if args[1] in self.series:raise RuntimeError('duplicate time series')
        self.series.add(args[1]);self.calls.append(('ts',args))
    def pattern(self,*args):self.patterns.add(args[1]);self.calls.append(('pattern',args))
    def load(self,*args):
        self.load_count+=1
        if self.load_count==self.fail_load:raise RuntimeError('injected load failure')
        self.calls.append(('load',args))
    def remove(self,kind,tag):
        (self.patterns if kind=='loadPattern' else self.series).discard(tag)
        self.calls.append(('remove',(kind,tag)))


class NodalLoadContractTests(unittest.TestCase):
    def test_all_preflight_errors_leave_domain_untouched(self):
        bad=[lambda o:apply_nodal_loads({3:(1,0,0)},TagManager(),o),
             lambda o:apply_nodal_loads({1:(1,0)},TagManager(),o),
             lambda o:apply_nodal_loads({1:(1,0,math.nan)},TagManager(),o),
             lambda o:apply_nodal_load_history({1:[[0,0,0],[1,0,0]],2:[[0,0,0]]},TagManager(),o,dt=.1),
             lambda o:apply_nodal_load_history({1:[[0,0,0],[1,0,0]]},TagManager(),o,times=[0,0]),
             lambda o:apply_nodal_load_history({1:[[0,0,0],[1,0,0]]},TagManager(),o,dt=.1,times=[0,.1]),
             lambda o:apply_nodal_load_history({1:[[0,0,0],[1,0,0]]},TagManager(),o,times=[0,.1,.2]),
             lambda o:apply_nodal_loads({1:(1,0,0)},TagManager(),o,time_series_type='Path',path_values=[1,2],dt=.1)]
        for make in bad:
            o=FakeOps()
            with self.subTest(make=make),self.assertRaises(ValueError):make(o)
            self.assertEqual(o.calls,[])

    def test_zero_rain_creates_no_engine_objects(self):
        o=FakeOps();h=apply_nodal_load_history({1:[[0,0,0],[0,0,0]]},TagManager(),o,dt=.1)
        self.assertEqual(h.pattern_tags,());self.assertEqual(o.calls,[])
        self.assertEqual(current_nodal_loads(h,ops_module=o),{1:(0,0,0)})

    def test_exact_proportional_channels_group_and_independent_do_not(self):
        o=FakeOps();h=apply_nodal_load_history({1:[[0,0,0],[2,-4,0],[4,-8,1]]},TagManager(),o,dt=.1)
        self.assertEqual(len(h.components),2)
        self.assertEqual(h.components[0].applied_loads[1],(4,-8,0))
        self.assertEqual(h.components[1].applied_loads[1],(0,0,1))

    def test_history_failure_removes_previous_components_only(self):
        o=FakeOps(fail_load=3);tm=TagManager()
        gravity=apply_nodal_loads({1:(0,0,-10)},tm,o,time_series_type='Constant')
        with self.assertRaises(RuntimeError):
            apply_nodal_load_history({1:[[0,0,0],[1,0,0],[0,2,0]]},tm,o,dt=.1)
        self.assertEqual(o.patterns,{gravity.pattern_tag});self.assertEqual(o.series,{gravity.time_series_tag})

    def test_foreign_series_collision_is_not_removed(self):
        o=FakeOps();o.series.add(1)
        with self.assertRaises(RuntimeError):apply_nodal_loads({1:(1,0,0)},TagManager(),o)
        self.assertEqual(o.series,{1});self.assertFalse(o.patterns)
        self.assertFalse(any(c[0]=='remove' for c in o.calls))

    def test_foreign_pattern_collision_is_preflighted(self):
        o=FakeOps();o.patterns.add(1)
        with self.assertRaises(ValueError):apply_nodal_loads({1:(1,0,0)},TagManager(),o)
        self.assertEqual(o.calls,[]);self.assertEqual(o.patterns,{1})

    def test_pattern_budget_does_not_truncate_or_partially_apply(self):
        o=FakeOps()
        with self.assertRaises(ValueError):apply_nodal_load_history({1:[[0,0,0],[1,0,0],[0,2,0]]},TagManager(),o,dt=.1,max_patterns=1)
        self.assertEqual(o.calls,[])
        with self.assertRaises(ValueError):apply_nodal_load_history({1:[[0,0,0],[1,0,0]]},TagManager(),o,times=[0,.1],hold_last=True,max_patterns=1)
        self.assertEqual(o.calls,[])

    def test_no_mutation_and_dimension_mismatch(self):
        loads={1:[1.,2.,3.]};o=FakeOps();h=apply_nodal_loads(loads,TagManager(),o)
        loads[1][0]=999
        self.assertEqual(h.applied_loads[1],(1,2,3))
        self.assertEqual(merge_nodal_loads(h.applied_loads,h.applied_loads),{1:(2,4,6)})
        with self.assertRaises(ValueError):merge_nodal_loads({1:(1,2,3)},{1:(1,2)})


def spring_domain(ndf=6,stiffness=1000.,mass=2.):
    ops.wipe();ops.model('basic','-ndm',3 if ndf>1 else 1,'-ndf',ndf)
    zero=(0.,0.,0.) if ndf>1 else (0.,)
    ops.node(1,*zero);ops.node(2,*zero);ops.fix(1,*([1]*ndf));ops.mass(2,*([mass]*ndf))
    for d in range(1,ndf+1):ops.uniaxialMaterial('Elastic',d,stiffness*d)
    ops.element('zeroLength',1,1,2,'-mat',*range(1,ndf+1),'-dir',*range(1,ndf+1))


def static_setup(increment):
    ops.wipeAnalysis();ops.constraints('Plain');ops.numberer('Plain');ops.system('BandGeneral')
    ops.test('NormDispIncr',1e-12,20);ops.algorithm('Newton');ops.integrator('LoadControl',increment);ops.analysis('Static')


def transient_spring(wind,rain,dt,*,mode='both',explicit_times=False):
    """A known 1-DOF model, entirely separate from the tower validation."""
    spring_domain(1,200.,2.);tm=TagManager()
    gravity=apply_nodal_loads({2:(-20.,)},tm,ops,name='preload')
    static_setup(1.);assert ops.analyze(1)==0
    ops.loadConst('-time',0.)
    base=ops.nodeDisp(2,1);handles=[]
    time_options={'times':np.arange(len(wind))*dt} if explicit_times else {'dt':dt}
    if mode in ('wind','both'):handles.append(apply_nodal_load_history({2:[[v] for v in wind]},tm,ops,name='wind',hold_last=True,**time_options))
    if mode in ('rain','both'):handles.append(apply_nodal_load_history({2:[[v] for v in rain]},tm,ops,name='rain',hold_last=True,**time_options))
    ops.rayleigh(.2,0.,0.,0.)
    ops.wipeAnalysis();ops.constraints('Plain');ops.numberer('Plain');ops.system('BandGeneral')
    ops.test('NormDispIncr',1e-12,20);ops.algorithm('Newton');ops.integrator('Newmark',.5,.25);ops.analysis('Transient')
    values=[0.];ledger_error=0.;dynamic_error=0.
    for i in range(1,len(wind)):
        assert ops.analyze(1,dt)==0
        expected=(wind[i] if mode in ('wind','both') else 0)+(rain[i] if mode in ('rain','both') else 0)
        ledger=current_nodal_loads(gravity,*handles,ops_module=ops)[2][0]
        ledger_error=max(ledger_error,abs(ledger-(-20.+expected)))
        residual=ledger-200*ops.nodeDisp(2,1)-.4*ops.nodeVel(2,1)-2*ops.nodeAccel(2,1)
        dynamic_error=max(dynamic_error,abs(residual))
        values.append(ops.nodeDisp(2,1)-base)
    ops.wipe()
    return np.array(values),ledger_error,dynamic_error


def exact_ramp_response(forces,dt):
    # Exact exp(A dt) response to each linearly interpolated force interval.
    # State = displacement, velocity, force, force derivative.
    A=np.array([[0,1,0,0],[-100,-.2,.5,0],[0,0,0,1],[0,0,0,0]],dtype=float)
    transition=expm(A*dt);uv=np.zeros(2);values=[0.]
    for a,b in zip(forces,forces[1:]):
        state=transition@np.array([*uv,a,(b-a)/dt]);uv=state[:2];values.append(uv[0])
    return np.array(values)


class RealNodalLoadTests(unittest.TestCase):
    def tearDown(self):ops.wipe()

    def test_static_wind_rain_moments_and_remove_rain_keep_gravity(self):
        spring_domain();tm=TagManager()
        gravity=apply_nodal_loads({2:(0,0,-100,0,0,0)},tm,ops,name='gravity')
        static_setup(1.);self.assertEqual(ops.analyze(1),0);ops.loadConst('-time',0.)
        wind=apply_nodal_loads({2:(30,40,0,1,2,3)},tm,ops,name='wind')
        rain=apply_nodal_loads({2:(2,-3,-7,0,1,-2)},tm,ops,name='rain')
        static_setup(1.);self.assertEqual(ops.analyze(1),0);ops.reactions()
        actual=current_nodal_loads(gravity,wind,rain,ops_module=ops)[2]
        expected=(32,37,-107,1,3,1)
        np.testing.assert_allclose(actual,expected)
        np.testing.assert_allclose(ops.nodeDisp(2),np.array(expected)/(1000*np.arange(1,7)),atol=1e-13)
        np.testing.assert_allclose(ops.nodeReaction(1),-np.array(expected),atol=1e-9)
        # loadConst must be reflected in the receipt ledger after time reset.
        ops.loadConst('-time',0.);remove_nodal_loads(rain,ops);remove_nodal_loads(rain,ops)
        static_setup(0.);self.assertEqual(ops.analyze(1),0)
        np.testing.assert_allclose(current_nodal_loads(gravity,wind,rain,ops_module=ops)[2],(30,40,-100,1,2,3))
        self.assertIn(gravity.pattern_tag,ops.getPatterns())
        with self.assertRaises(ValueError):current_nodal_loads(wind,wind,ops_module=ops)

    def test_nonuniform_vector_histories_nonzero_time_offset_and_vertical_load(self):
        spring_domain();ops.setTime(7.);tm=TagManager()
        history=[[0,0,0,0,0,0],[10,2,-3,0,0,4],[-10,6,-9,0,1,0]]
        h=apply_nodal_load_history({2:history},tm,ops,times=[0,.2,.6],hold_last=True)
        for step,expected in ((.1,np.array(history[1])*.5),(.3,(np.array(history[1])+history[2])/2),(.3,np.array(history[2]))):
            static_setup(step);self.assertEqual(ops.analyze(1),0);ops.reactions()
            np.testing.assert_allclose(current_nodal_loads(h,ops_module=ops)[2],expected,atol=1e-10)
            np.testing.assert_allclose(-np.array(ops.nodeReaction(1)),expected,atol=1e-10)

    def test_three_translation_dof_model_is_supported(self):
        spring_domain(3);h=apply_nodal_loads({2:(4,5,-6)},TagManager(),ops,time_series_type='Constant')
        static_setup(1.);self.assertEqual(ops.analyze(1),0)
        np.testing.assert_allclose(ops.nodeDisp(2),np.array([4,5,-6])/[1000,2000,3000])

    def test_two_nodes_can_have_different_time_histories(self):
        spring_domain(3);ops.node(3,0.,0.,0.)
        ops.element('zeroLength',2,1,3,'-mat',1,2,3,'-dir',1,2,3)
        h=apply_nodal_load_history({2:[[0,0,0],[10,0,-2],[0,4,-1]],
            3:[[0,0,0],[0,5,-6],[8,0,-9]]},TagManager(),ops,dt=.1,hold_last=True)
        static_setup(.1);self.assertEqual(ops.analyze(1),0)
        ledger=current_nodal_loads(h,ops_module=ops)
        np.testing.assert_allclose(ledger[2],(10,0,-2));np.testing.assert_allclose(ledger[3],(0,5,-6))
        np.testing.assert_allclose(ops.nodeDisp(2),np.array([10,0,-2])/[1000,2000,3000])
        np.testing.assert_allclose(ops.nodeDisp(3),np.array([0,5,-6])/[1000,2000,3000])

    def test_scalar_nonuniform_hold_tail_and_removal(self):
        spring_domain(1);tm=TagManager()
        h=apply_nodal_loads({2:(10.,)},tm,ops,time_series_type='Path',path_values=[0,1,2],times=[0,.2,.6],hold_last=True)
        self.assertEqual(len(h.pattern_tags),2)
        static_setup(.7);self.assertEqual(ops.analyze(1),0)
        self.assertAlmostEqual(current_nodal_loads(h,ops_module=ops)[2][0],20.)
        static_setup(.8);self.assertEqual(ops.analyze(1),0)
        self.assertAlmostEqual(current_nodal_loads(h,ops_module=ops)[2][0],20.)
        remove_nodal_loads(h,ops);self.assertEqual(list(ops.getPatterns()),[])

    def test_path_end_policy_is_explicit(self):
        for use_last in (False,True):
            spring_domain(1);h=apply_nodal_load_history({2:[[0],[10],[20]]},TagManager(),ops,dt=.1,hold_last=use_last)
            static_setup(.25);self.assertEqual(ops.analyze(1),0)
            self.assertAlmostEqual(current_nodal_loads(h,ops_module=ops)[2][0],20 if use_last else 0)

    def test_wind_rain_transient_superposition_and_exact_ramp_reference(self):
        dt=.002;t=np.arange(501)*dt
        wind=10*np.sin(2*np.pi*t);rain=3*t+2*np.sin(np.pi*t)
        both,ledger,residual=transient_spring(wind,rain,dt)
        w,_,_=transient_spring(wind,rain,dt,mode='wind');r,_,_=transient_spring(wind,rain,dt,mode='rain')
        np.testing.assert_allclose(both,w+r,atol=1e-12)
        self.assertLess(ledger,1e-10);self.assertLess(residual,1e-8)
        exact=exact_ramp_response(wind+rain,dt)
        self.assertLess(np.max(np.abs(exact-both)),2e-5)

    def test_explicit_time_tail_decomposition_preserves_transient_initial_balance(self):
        dt=.005;t=np.arange(101)*dt
        wind=10*t;rain=2*np.sin(np.pi*t)
        uniform,_,_=transient_spring(wind,rain,dt)
        explicit,ledger,residual=transient_spring(wind,rain,dt,explicit_times=True)
        np.testing.assert_allclose(explicit,uniform,atol=1e-12)
        self.assertLess(ledger,1e-10);self.assertLess(residual,1e-8)


if __name__=='__main__':unittest.main()
