import opstool as opst
import matplotlib.pyplot as plt
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
plt.savefig("fluctuate_wind_simulate/.output/opensees_simulate/stress_Distribution_y=-0.05_z=0.15_force*20.png")