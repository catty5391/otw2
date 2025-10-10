import pandas as pd
import numpy as py
import matplotlib.pyplot as plt


df = pd.read_csv("./output/Node_disp.out", header = None, sep = " ")

time = df.iloc[:,1].values
force = df.iloc[:, 1].values


plt.plot(time, force)
plt.show()