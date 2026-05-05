from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


from model import OpenSeesModel
from model import OpenSeesModelWithBuckling
import opstool as opst
import openseespy.opensees as ops


model = OpenSeesModelWithBuckling("Source/Z30103A6.s2k")
model.model_tower()
ops.recorder('Node', '-file', 'pushover/.output/with_gravity/Node_accel.out', '-time', '-node', 350, '-dof', 2, 'accel')
ops.recorder('Node', '-file', 'pushover/.output/with_gravity/Node_velocity.out', '-time', '-node', 350, '-dof', 2, 'vel')
ops.recorder('Node', '-file', 'pushover/.output/with_gravity/Node_disp.out', '-time', '-node', 350, '-dof', 2, 'disp')
ops.recorder('Element', '-file', 'pushover/.output/with_gravity/Element9_section1.out', '-time', '-ele', 9, 'section', 1, 'fiber', -0.05, 0.15, 'stressStrain')
ops.recorder('Element', '-file', 'pushover/.output/with_gravity/Element_all_section1.out', '-time', '-ele', *ops.getEleTags(), 'section', 1, 'fiber', -0.05, 1, 'stress')


ODB = opst.post.CreateODB(odb_tag=1, save_fiber_sec_resp = True, fiber_ele_tags = [9])
ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
node_loads = opst.pre.create_gravity_load(direction="Z", factor=-9.81)  # Create gravity loads in the pattern tag=1

ops.constraints('Plain')
ops.numberer('RCM')
ops.system('BandGeneral')
ops.test('NormDispIncr', 0.01, 40, 2)
ops.algorithm('KrylovNewton')
ops.integrator('LoadControl', 0.1)
ops.analysis('Static')
for i in range(10):
    ops.analyze(1)
    ODB.fetch_response_step()
ops.loadConst('-time', 0.0)

ops.timeSeries('Linear', 2)
ops.pattern('Plain', 2, 2)
ops.load(350, 0, 1, 0, 0, 0, 0)
# ops.constraints('Plain')
# ops.numberer('RCM')
# ops.system('BandGeneral')
# ops.test('NormDispIncr', 0.01, 40, 2)
# ops.algorithm('KrylovNewton')
ops.integrator('DisplacementControl', 350, 2, 0.01)
ops.analysis('Static')

for i in range(120):
    ops.analyze(1)
    ODB.fetch_response_step()
ODB.save_response()
print('over')
