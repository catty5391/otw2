# 将风速转换为风压力
# 将每个节间的投影面积乘以风速时程
import sys
import os
sys.path.append("..")
from model.Area import Area

import pandas as pd
A = Area()
A_s = A.get_area()

column_name = ["t","n0","n1","n2","n3","n4","n5","n6","n7","n8","n9","n10","n11"]
print(os.getcwd())
wind_speed = pd.read_csv("results/wind_speed.csv", skiprows=0, header=None, names=column_name)

for i in range(12):
    area = A_s[i]
    wind_speed.iloc[:,i+1] = wind_speed.iloc[:,i+1].apply(lambda x: 0.5 * x**2 * area)

filename_t = f"wind_press/t.csv"
column_t = wind_speed.iloc[:,0]
column_t.to_csv(filename_t,header=None, index=False)
for i in range(12):
    filename = f"wind_press/floor{i}_wind_press.csv"
    column = wind_speed.iloc[:,i+1]
    column.to_csv(filename,header=None, index=False)