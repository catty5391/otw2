import pandas as pd
import numpy as py
import matplotlib.pyplot as plt
import os
import opstool as opst

# 应力 应变 折线图
df = pd.read_csv("opstool/.output/Element9_section1.out", header = None, sep = " ")

stress = df.iloc[:, 1].values
strain = df.iloc[:, 2].values

plt.figure(figsize=(6, 5))
plt.plot(strain, stress)
plt.xticks(fontsize = 10)
plt.yticks(fontsize = 10)
plt.xlabel("strain", fontsize = 10)
plt.ylabel("stress", fontsize = 10)


plt.savefig("opstool/.output/plot_element9_stress_strain.png")


# 最后一步 应力分布图
sec_resp = opst.post.get_element_responses(odb_tag=1, ele_type="FiberSection")  # odb_tag=1 as above

stress = sec_resp["Stresses"].sel(eleTags = 9, secPoints=1).isel(time=-1)
strain = sec_resp["Strains"].sel(eleTags = 9, secPoints=1).isel(time=-1)
y = sec_resp["ys"].sel(eleTags = 9, secPoints = 1)
z = sec_resp["zs"].sel(eleTags = 9, secPoints = 1)
mat = sec_resp["matTags"].sel(eleTags = 9, secPoints = 1)
cond = (mat == 3)
plt.figure(figsize=(6, 5))
scatter = plt.scatter(y[cond], z[cond], c=stress[cond], cmap="jet", s=50)
plt.xlabel("Y Coordinate")
plt.ylabel("Z Coordinate")
plt.title("Stress Distribution\n(Element 9, Section 1, matTag=3)")
plt.colorbar(scatter, label="Stress")
plt.axis("equal")
plt.grid(True, linestyle="--", alpha=0.5)
plt.tight_layout()
plt.savefig("opstool/.output/stress_Distribution.png")