import pandas as pd
import numpy as py
import matplotlib.pyplot as plt
import os
import opstool as opst

# 应力 应变 折线图
df = pd.read_csv("pushover/.output/no_gravity/Node_disp.out", header = None, sep = " ")


stress = df.iloc[:, 0].values
strain = df.iloc[:, 1].values

plt.figure(figsize=(6, 5))
plt.plot(strain, stress)
plt.xticks(fontsize = 10)
plt.yticks(fontsize = 10)
plt.xlabel("strain", fontsize = 10)
plt.ylabel("stress", fontsize = 10)


plt.savefig("pushover/.output/no_gravity/plot_node_disp.png")