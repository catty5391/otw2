# 给所有节点加上z向约束


import pandas as pd

nodeTags = pd.read_csv("Src/Node.tcl", header=None, sep = " ")

pass_list = [2430,2431, 2432,2433,141,140,160,162,430,432,431,433]

with open("Src/Fix_change.tcl","w") as f:
    for _,nodeTag in nodeTags.iterrows():
        if nodeTag.iloc[1] in pass_list:
            continue
        f.write(f"fix {nodeTag.iloc[1]} 1 1 1\n")