from pathlib import Path
import sys
import os
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


from model import OpenSeesModel
from model import OpenSeesModelWithBuckling
from util import CorrectedStoryDriftTracker, NodeReactionGetter, PushoverWindLoadApplier, TagManager, GravityLoadApplier
import opstool as opst
import openseespy.opensees as ops
ops.wipe()
model = OpenSeesModel("Source/Z30103A6.s2k")
model.model_tower()
tag_manager = TagManager(
start_tag = {
    "timeSeries": 1,
    "pattern": 1,
}
)
config_drift_tracker_node = Path(os.getcwd()) / 'pushover' / '.config' / 'node_to_record_floor_disp.json'
drift_out_dir = Path(os.getcwd()) / 'pushover' / '.output' / 'no_buckling'
drift_out_dir.mkdir(parents=True, exist_ok=True)
drift_out_file = drift_out_dir / 'drift.csv'
# ops.timeSeries("Linear", 1)
# ops.pattern("Plain", 1, 1)
# node_loads = opst.pre.create_gravity_load(direction="Z", factor=-9.81)  # Create gravity loads in the pattern tag=1
gravity = GravityLoadApplier(
    tag_manager=tag_manager,
    direction="Z",
    factor=-9.81,
)

gravity_result = gravity.apply_from_model(model)

ops.constraints('Transformation')
ops.numberer('RCM')
ops.system('UmfPack')
ops.test('NormDispIncr', 0.00001, 80, 2)
ops.algorithm('KrylovNewton')
ops.integrator('LoadControl', 0.1)

for i in range(10):
    ops.analysis('Static')
    ops.analyze(1)
ops.loadConst('-time', 0.0)
ops.recorder('Node', '-file', f'pushover/.output/no_buckling/Node_disp.out', '-time', '-node', 350, '-dof', 2, 'disp')
ops.recorder('Element', '-file', f'pushover/.output/no_buckling/Element9_section1.out', '-time', '-ele', 9, 'section', 1, 'fiber', -0.05, 0.15, 'stressStrain')
ops.recorder('Element', '-file', f'pushover/.output/no_buckling/Element_all_section1.out', '-time', '-ele', *ops.getEleTags(), 'section', 1, 'fiber', -0.05, 1, 'stress')
# ops.timeSeries('Linear', 2)
# ops.pattern('Plain', 2, 2)
# ops.load(350, 0, 1, 0, 0, 0, 0)
# ops.constraints('Plain')
# ops.numberer('RCM')
# ops.system('SparseSYM')
# ops.test('NormDispIncr', 0.0001, 40, 2)
#   ops.algorithm('KrylovNewton')
wind = PushoverWindLoadApplier(
tag_manager = tag_manager,
)
result = wind.apply_from_model(model)

ops.integrator('DisplacementControl', 350, 2, 0.0025)
ops.analysis('Static')
track = CorrectedStoryDriftTracker(config_drift_tracker_node)
story_label = track.get_story_labels()

with drift_out_file.open('w', encoding='utf-8') as f:
    f.write('reaction,' + ','.join(story_label) + '\n')
    f.flush()
    os.fsync(f.fileno())
    for step in range(400):
        if ops.analyze(1) != 0:
            print(f"Analysis failed at step {step}")
            break

        drift_now = track.capture_step()
        reactions = NodeReactionGetter().get_batch([2510, 2511, 2512, 2513], dof=2)
        reactions_sum = sum(reactions.values())
        f.write(f"{reactions_sum}," + ",".join(str(v) for v in drift_now) + '\n')