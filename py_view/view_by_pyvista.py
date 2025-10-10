import pyvista as pv
import pandas as pd
import numpy as np

# 读取数据
node_df = pd.read_csv("Src/Node.tcl", sep=' ', header=None)
node_df = node_df.iloc[:, [1, 2, 3, 4]]
node_df.columns = ['node', 'x', 'y', 'z']

element_df = pd.read_csv("Src/Element.tcl", sep=' ', header=None)
element_df = element_df.iloc[:, [3, 4]]
element_df.columns = ['node1', 'node2']

# 创建字典存储节点坐标
node_coord_dict = {}
for _, row in node_df.iterrows():
    node_coord_dict[row['node']] = (row['x'], row['y'], row['z'])

# 准备连线数据：每条线需要两个点（起点和终点）
lines = []
points = []

for _, element in element_df.iterrows():
    node1 = element['node1']
    node2 = element['node2']
    _,_,z_1 = node_coord_dict[node1]
    _,_,z_2 = node_coord_dict[node2]
    if z_1 > 25.7 or z_2 >25.7:
        continue
    if node1 in node_coord_dict and node2 in node_coord_dict:
        x1, y1, z1 = node_coord_dict[node1]
        x2, y2, z2 = node_coord_dict[node2]
        
        # 记录点的索引（PyVista中连线通过点的索引序列定义）
        start_idx = len(points)
        points.append([x1, y1, z1])
        points.append([x2, y2, z2])
        # 每条线定义为 [2, start_index, end_index]
        lines.append([2, start_idx, start_idx+1]) 

# 将点和线转换为PyVista的PolyData对象
points_array = np.array(points)
mesh = pv.PolyData(points_array, lines=np.array(lines).flatten()) # lines需要展平

# 创建一个绘制器
plotter = pv.Plotter()

# 添加连线模型到绘制器
plotter.add_mesh(mesh, color='red', line_width=2, label='Elements', opacity=0.6)

# 添加节点模型（可选，大规模数据时可考虑省略）
# 创建一个只包含点的PolyData对象
nodes_mesh = pv.PolyData(points_array)
# 添加点的标量数据（例如Z坐标）
nodes_mesh['Z值'] = points_array[:, 2] 
plotter.add_mesh(nodes_mesh, scalars='Z值', point_size=3.0, opacity=0.8, 
                 render_points_as_spheres=True, label='Nodes', cmap='viridis')

# 添加图例
plotter.add_legend()

# 设置坐标轴范围和标签

plotter.add_axes(xlabel='X轴', ylabel='Y轴', zlabel='Z轴')

# 显示图形
plotter.show()




