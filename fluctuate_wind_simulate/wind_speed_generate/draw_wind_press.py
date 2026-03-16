import pandas as pd
import numpy
import matplotlib.pyplot as plt
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

def plot_floor(num):
    t = pd.read_csv("t.csv", header=None)
    press = pd.read_csv(f"floor{num}_wind_press.csv", header=None)/1000
    plt.xlabel("time(s)", fontsize = 20)
    plt.ylabel(f"floor{num}_wind_press(kN)", fontsize = 20)
    plt.xticks(fontsize = 20)
    plt.yticks(fontsize = 20)
    plt.plot(t, press)
    plt.show()

plot_floor(10)