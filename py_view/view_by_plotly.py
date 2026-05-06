from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
from model import OpenSeesModelWithBuckling
from util.postprocess import PlotModel


model = OpenSeesModelWithBuckling(PROJECT_ROOT / "Source" / "Z30103A6.s2k")
viewer = PlotModel(model)
viewer.show(    
    element_hover="midpoint",
    node_size=2,
    element_width=1
)
