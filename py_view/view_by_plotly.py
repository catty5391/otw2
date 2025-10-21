import plotly.graph_objects as go
import pandas as pd
import numpy as np

# 读取数据
node_df = pd.read_csv("./Src/Node.tcl", sep=' ', header=None)
node_df = node_df.iloc[:, [1, 2, 3, 4]]
node_df.columns = ['node', 'x', 'y', 'z']

element_df = pd.read_csv("./Src/Element.tcl", sep=' ', header=None)
element_df = element_df.iloc[:, [3, 4]]
element_df.columns = ['node1', 'node2']

# 创建字典存储节点坐标，方便快速查询
node_coord_dict = {}
for _, row in node_df.iterrows():
    node_coord_dict[row['node']] = (row['x'], row['y'], row['z'])

# 准备连线数据
x_lines = []
y_lines = []
z_lines = []

# 收集所有点用于散点图（可选，如果你也想显示点的话）
all_x = []
all_y = []
all_z = []
nodes = []

for _, element in element_df.iterrows():
    node1 = element['node1']
    node2 = element['node2']
    
    if node1 in node_coord_dict and node2 in node_coord_dict:
        x1, y1, z1 = node_coord_dict[node1]
        x2, y2, z2 = node_coord_dict[node2]
        
        # 为每条线添加起点和终点坐标，中间插入None以防止连线错误
        x_lines.extend([x1, x2, None]) 
        y_lines.extend([y1, y2, None])
        z_lines.extend([z1, z2, None])
        
        # 收集所有点坐标
        nodes.extend([node1, node2])
        all_x.extend([x1, x2])
        all_y.extend([y1, y2])
        all_z.extend([z1, z2])

# 创建图表
fig = go.Figure()

# 添加连线（使用scatter3d的line模式）
fig.add_trace(go.Scatter3d(
    x=x_lines,
    y=y_lines,
    z=z_lines,
    mode='lines',
    line=dict(color='red', width=2), # 设置连线颜色和粗细
    name='Elements', # 图例名称
    hoverinfo='none' # 悬停时不显示信息
))

# 添加节点散点（可选，如果数据量很大，可以考虑省略点只显示线）
fig.add_trace(go.Scatter3d(
    x=all_x,
    y=all_y,
    z=all_z,
    mode='markers',
    marker=dict(
        size=2,
        color=all_z,  # 根据Z坐标值着色
        colorscale='Viridis', # 颜色方案
        opacity=0.8
    ),
    name='Nodes',
    text=[f'Node: {node}<br>X: {x}<br>Y: {y}<br>Z: {z}' for i,(node, x, y, z) in enumerate(zip(nodes, all_x, all_y, all_z))], # 悬停信息
    hoverinfo='text'
))

# 更新布局设置
fig.update_layout(
    title='空间结构可视化 (Plotly)',
    scene=dict(
        xaxis_title='X轴',
        yaxis_title='Y轴',
        zaxis_title='Z轴',
        xaxis=dict(range=[-80, 80]), # 设置坐标轴范围
        yaxis=dict(range=[-80, 80]),
        zaxis=dict(range=[-80, 80]),
    ),
    width=1000, # 图形宽度
    height=800, # 图形高度
)

# 显示图形
fig.show()

# 可以保存为独立的HTML文件，方便分享和后续查看
# fig.write_html("3d_visualization_plotly.html")