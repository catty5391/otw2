#将每层风荷载分配到节间点上，同时生成相应的tcl文件

import json
import os
import pandas as pd

from pathlib import Path
script_dir = Path(__file__).parent
os.chdir(script_dir)
print(os.getcwd())
with open("../config.json", "r") as f:
    config = json.load(f)

dt = 1/12
#需要生成timeseries文件，timeseires命令行，pattern命令行
with open("../wind_force_tcl/timeseries.tcl","w") as ts:
    with open("../wind_force_tcl/pattern.tcl", "w") as pattern:
        for i in range(12):
            floor_name = f"floor{i}"
            Node_list = config[floor_name]
            Node_num = len(Node_list)
            read_filename = f"../floor{i}_wind_press.csv"
            floor_wind = pd.read_csv(read_filename, header=None) /Node_num
            write_filename = f"../wind_force_tcl/floor{i}.tcl"
            floor_wind.to_csv(write_filename, header=False, index=False)
            ts.write(f"timeSeries Path {i} -dt {dt} -filePath ../fluctuate_wind_simulate/wind_press/wind_force_tcl/floor{i}.tcl\n")
            for Node_Tag in Node_list:
                pattern.write(f"pattern Plain {(i+1) * Node_Tag} {i} " + "{" + "\n")
                pattern.write(f"load {Node_Tag} 0 1 0 0 0 0\n")
                pattern.write("}\n")
