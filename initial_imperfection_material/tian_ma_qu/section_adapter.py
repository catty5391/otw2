"""Scale member stress to section P (N), with observable independent FE copies."""
from itertools import count
from math import isfinite
from weakref import WeakValueDictionary

from .material import TianMaQuPrototype


class CopyRegistry:
    def __init__(self):
        self.instances = WeakValueDictionary()
        self.serial = count(1)

    def attach(self, material):
        material.instance_id = next(self.serial)
        self.instances[material.instance_id] = material

    def committed(self):
        return [m for m in self.instances.values() if m.commits > 0]


class AxialSectionMaterial:
    """OpenSees Aggregator receives N vs axial strain, NOT Pa vs strain.

    Observers never drive state. Original material and every native getCopy have
    independent committed/trial histories. Registry uses weak refs so temporary
    section prototypes are not retained. Instance IDs are NOT integration IDs.
    """
    def __init__(self, parameters, area, registry=None):
        if not isfinite(area) or area <= 0:
            raise ValueError("area must be finite and positive")
        self.material = TianMaQuPrototype(parameters)
        self.area = area
        self.registry = registry if registry is not None else CopyRegistry()
        self.commits = 0
        self.tension_yield_ever = False
        self.registry.attach(self)

    def set_trial_strain(self, strain, strain_rate=0):
        return self.material.set_trial_strain(strain, strain_rate)

    def get_strain(self):
        return self.material.get_strain()

    def get_stress(self):
        return self.area * self.material.get_stress()

    def get_tangent(self):
        return self.area * self.material.get_tangent()

    def get_initial_tangent(self):
        return self.area * self.material.get_initial_tangent()

    def commit_state(self):
        state = self.material.get_state()
        self.tension_yield_ever = self.tension_yield_ever or state["stage"] == "tension_hardening" or any(
            e.get("to_stage") == "tension_hardening" for e in state["events"])
        result = self.material.commit_state()
        self.commits += 1
        return result

    def revert_to_last_commit(self):
        return self.material.revert_to_last_commit()

    def revert_to_start(self):
        self.commits = 0
        self.tension_yield_ever = False
        return self.material.revert_to_start()

    def get_copy(self):
        result = object.__new__(type(self))
        result.material = self.material.get_copy()
        result.area, result.registry = self.area, self.registry
        result.commits = self.commits
        result.tension_yield_ever = self.tension_yield_ever
        self.registry.attach(result)
        return result
