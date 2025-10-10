# matplotlib 3D绘图

# 3D 轴（属于 Axes3D 类）是通过将 projection="3d" 关键字参数传递给 Figure.add_subplot 来创建的：
from mpl_toolkits.mplot3d import axes3d
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import time
import matplotlib.font_manager as fm
from matplotlib import rcParams
# 方法1: 设置全局字体为支持中文的字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']  # 使用黑体，如果系统没有则使用DejaVu Sans
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


#读取数据
node_df = pd.read_csv("Node.tcl", sep = ' ', header= None)
node_df = node_df.iloc[:, [1,2,3,4]]
node_df.columns = ['node', 'x', 'y', 'z']
element_df = pd.read_csv("Element.tcl", sep=' ', header = None)
element_df = element_df.iloc[:,[3, 4]]
element_df.columns = ['node1', 'node2']

x_coords = []
y_coords = []
z_coords = [] 

for index, element in element_df.iterrows():
    node1 = element['node1']
    node2 = element['node2']
    node1_cord = node_df[node_df['node'] == node1]
    node2_cord = node_df[node_df['node'] == node2]

    x_coords.append(node1_cord['x'].iloc[0])
    x_coords.append(node2_cord['x'].iloc[0])
    y_coords.append(node1_cord['y'].iloc[0])
    y_coords.append(node2_cord['y'].iloc[0])
    z_coords.append(node1_cord['z'].iloc[0])
    z_coords.append(node2_cord['z'].iloc[0])



# 设置图形大小和DPI以提高清晰度
plt.figure(figsize=(12, 10), dpi=100)
ax = plt.axes(projection='3d')

# 设置坐标轴标签和范围
ax.set_xlabel('X轴')
ax.set_ylabel('Y轴')
ax.set_zlabel('Z轴')
ax.set_xlim([-40, 40])
ax.set_ylim([-40, 40])
ax.set_zlim([-40, 40])
ax.set_title('大规模空间点连线可视化')
num_points = len(x_coords)
print(f"正在处理 {num_points} 个数据点...")
start_time = time.time()

# 优化1: 使用numpy数组操作替代循环
# 将所有点一次性绘制，而不是逐个添加
ax.scatter(x_coords, y_coords, z_coords, 
           c='blue', marker='o', s=2, alpha=0.6)

# 优化2: 批量绘制连线
# 假设我们按照数据顺序连接相邻的点
for i in range(0, num_points-1, 2):  # 每两个点连接一次，减少线段数量
    ax.plot([x_coords[i], x_coords[i+1]], 
            [y_coords[i], y_coords[i+1]], 
            [z_coords[i], z_coords[i+1]], 
            'r-', alpha=0.3, linewidth=0.5)

# 添加一些统计信息到图表
processing_time = time.time() - start_time
ax.text2D(0.05, 0.95, f"点数: {num_points}\n处理时间: {processing_time:.2f}秒", 
          transform=ax.transAxes, bbox=dict(facecolor='white', alpha=0.7))

print(f"数据处理完成，耗时: {processing_time:.2f}秒")

# 添加颜色条和标签
# 可以根据点的某个属性（如高度）着色
scatter = ax.scatter(x_coords, y_coords, z_coords, c=z_coords, 
                    cmap='viridis', marker='o', s=2, alpha=0.6)
plt.colorbar(scatter, ax=ax, label='Z坐标值')

plt.tight_layout()
plt.savefig('large_scale_3d_plot.png', dpi=150, bbox_inches='tight')
plt.show()