import pandas as pd

mass = pd.read_csv("./Src/Mass.tcl", header = None, sep = " ")

with open("./normal_force/gravity_force.tcl", 'w') as f:
    #荷载施加编号
    i = 20
    for _, row in mass.iterrows():
        mass_ID = row.iloc[1]
        gravity = -row.iloc[2] * 9.8
        temp = "{"
        f.write(f"pattern Plain {i} Linear {temp}\n")
        f.write(f"load {mass_ID} 0 0 {gravity} 0 0 0\n")
        f.write("}\n")
        i += 1