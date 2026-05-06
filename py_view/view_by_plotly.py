
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
from util.postprocess import PlotModel
from model import OpenSeesModelWithBuckling


model = OpenSeesModelWithBuckling("Source/Z30103A6.s2k")
viewer = PlotModel(model)
viewer.write_html("plotly.html")