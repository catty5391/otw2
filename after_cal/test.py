import pandas as pd
import numpy as py
import matplotlib.pyplot as plt
import os

script_dir = os.path.dirname(os.path.abspath(__file__))

os.chdir(script_dir)

df = pd.read_csv("../output/Node_accel.out", header = None, sep = " ")

time = df.iloc[:,0].values
force = df.iloc[:, 1].values


plt.plot(time, force)
plt.show()