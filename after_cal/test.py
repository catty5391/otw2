import pandas as pd
import numpy as py
import matplotlib.pyplot as plt
import os

script_dir = os.path.dirname(os.path.abspath(__file__))

os.chdir(script_dir)

df = pd.read_csv("../output/Node_accel.out", header = None, sep = " ")

time = df.iloc[:,0].values
disp = df.iloc[:, 1].values


plt.plot(time, disp)
plt.xticks(fontsize = 20)
plt.yticks(fontsize = 20)
plt.xlabel("time(s)", fontsize = 20)
plt.ylabel("accelerate(m/s^2)", fontsize = 20)


plt.show()