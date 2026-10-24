import math
import unittest
from util.processing.directional_wind import (wind_unit_vector, nodal_resultant, merge_nodal_loads,
                                              apply_nodal_wind_loads)
from util.preprocess.tag_manager import TagManager


class FakeOps:
    def __init__(self):
        self.calls = []
    def getNodeTags(self): return [1, 2]
    def nodeDisp(self, tag): return (0.,)*6
    def getTime(self): return 0.
    def timeSeries(self, *args): self.calls.append(("ts", args))
    def pattern(self, *args): self.calls.append(("pattern", args))
    def load(self, *args): self.calls.append(("load", args))
    def remove(self, *args): self.calls.append(("remove", args))


class DirectionalWindTests(unittest.TestCase):
    def test_cardinals_and_invalid(self):
        for angle, expected in [(0,(1,0,0)),(90,(0,1,0)),(180,(-1,0,0)),(270,(0,-1,0)),(360,(1,0,0))]:
            self.assertEqual(wind_unit_vector(angle), expected)
        for a in (math.nan, math.inf):
            with self.assertRaises(ValueError): wind_unit_vector(a)

    def test_resultant_and_origin(self):
        nodes = {1:(0,2,3), 2:(0,-2,3)}
        loads = {1:(10,0,0,0,0,0), 2:(10,0,0,0,0,1)}
        r = nodal_resultant(nodes, loads)
        self.assertEqual(r["force_N"], [20,0,0])
        self.assertEqual(r["moment_Nm"], [0,60,1])
        shifted = {k:tuple(x+v for x,v in zip(p,(5,6,7))) for k,p in nodes.items()}
        self.assertEqual(nodal_resultant(shifted,loads,(5,6,7))["moment_Nm"],r["moment_Nm"])

    def test_merge_no_mutation(self):
        a = {1:(1,2,0,0,0,0)}
        self.assertEqual(merge_nodal_loads(a,a)[1],(2,4,0,0,0,0))
        self.assertEqual(a[1],(1,2,0,0,0,0))

    def test_synchronized_path_and_preflight(self):
        ops = FakeOps()
        r = apply_nodal_wind_loads({1:(3,4,0,0,0,0)},TagManager(),ops,
                                   time_series_type="Path",path_values=[0,1,.5],dt=.1)
        self.assertEqual(sum(c[0]=="ts" for c in ops.calls),1)
        self.assertEqual(r.applied_loads[1],(3,4,0,0,0,0))
        for loads in ({3:(1,0,0,0,0,0)}, {1:(1,0,0)}, {1:(math.nan,0,0,0,0,0)}):
            before = len(ops.calls)
            with self.assertRaises(ValueError): apply_nodal_wind_loads(loads,TagManager(),ops)
            self.assertEqual(len(ops.calls),before)

    def test_rollback_does_not_remove_other_patterns(self):
        class FailOps(FakeOps):
            def load(self,*args): raise RuntimeError("load failed")
        ops=FailOps()
        with self.assertRaises(RuntimeError):
            apply_nodal_wind_loads({1:(1,0,0,0,0,0)},TagManager(),ops)
        self.assertEqual([x[1][0] for x in ops.calls if x[0]=="remove"],["loadPattern","timeSeries"])

    def test_path_starts_at_current_domain_time_and_linear_rejects_nonzero(self):
        ops=FakeOps()
        ops.getTime=lambda: 7.
        apply_nodal_wind_loads({1:(1,2,0,0,0,0)},TagManager(),ops,
                              time_series_type="Path",path_values=[0,1],dt=.1,hold_last=True)
        args=ops.calls[0][1]
        self.assertEqual(args[args.index("-startTime")+1],7.)
        self.assertIn("-useLast",args)
        with self.assertRaises(ValueError):
            apply_nodal_wind_loads({1:(1,2,0,0,0,0)},TagManager(),ops)


if __name__ == "__main__": unittest.main()
