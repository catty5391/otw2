import pandas as pd
import numpy as py
import matplotlib.pyplot as plt
import os
import opstool as opst

# 应力 应变 折线图
df = pd.read_csv("fluctuate_wind_simulate/.output/opensees_simulate/Element9_section1.out", header = None, sep = " ")

stress = df.iloc[:, 1].values
strain = df.iloc[:, 2].values

plt.figure(figsize=(6, 5))
plt.plot(strain, stress)
plt.xticks(fontsize = 10)
plt.yticks(fontsize = 10)
plt.xlabel("strain", fontsize = 10)
plt.ylabel("stress", fontsize = 10)


plt.savefig("fluctuate_wind_simulate/.output/opensees_simulate/plot_element9_stress_strain_y=-0.05_z=0.15_force*20.png")