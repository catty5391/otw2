#用来生成坐标变换向量
from Element import Element as Ele
from Node import Node
from numpy import array,cross,cos,pi,sin,linalg
import pandas as pd

class GeometricTransf():
    # 计算坐标转换向量(局部轴旋转角默认为0)
# 其中a为i节点的节点编号，b为j节点的节点编号,degree为用户指定的局部轴（默认为0）
# ------------------------------------------------------------------------------    
    def get_info(self):
        ele = Ele.output()
        node = Node.dataframe()
        return ele, node
    def GeomTransfVector(self, i, j ,deg='0'):


        d_x = i['x'].iloc[0] - j['x'].iloc[0]
        d_y = i['y'].iloc[0] - j['y'].iloc[0]
        d_z = i['z'].iloc[0] - j['z'].iloc[0]
        # 局部1轴由节点I指向节点J
        l_x = array([d_x, d_y, d_z])
        # 整体z轴
        g_z = array([0, 0, 1])
        # Sap2000中如果单元竖直，则局部y轴与整体x轴相同，局部z轴则可由局部x轴叉乘局部y轴得到
        if d_x == 0 and d_y == 0:
            l_y = array([1, 0, 0])
            l_z = cross(l_x, l_y)
        # 其他情况下局部x轴与局部y轴组成的平面为竖直平面（即法向量水平），这时局部z轴可由局部x轴与整体z轴叉乘得到
        else:
            l_z = cross(l_x, g_z)
        # 建模时还可能对局部轴进行旋转，这里用到了罗德里格旋转公式
        l_z_rot = l_z * cos(float(deg) / 180 * pi) + cross(l_x, l_z) * sin(float(deg) / 180 * pi)
        # 最后返回标准化后的局部z轴
        return l_z_rot / linalg.norm(l_z_rot)

    def transf(self):
        with open("./Src/geomtransf.tcl", 'w') as geo:
            ele, node = self.get_info()
            for _, item in ele.iterrows():
                eletag = item['eleTag']
                nodei = item['nodei']
                nodej = item['nodej']
                i_coord = node[node['num'] == nodei]
                j_coord = node[node['num'] == nodej] 
                z_axis = self.GeomTransfVector(i_coord, j_coord)
                geo.write(f"geomTransf Linear {eletag} {z_axis[0]} {z_axis[1]} {z_axis[2]}\n")

if __name__ == "__main__":
    geo_test = GeometricTransf()
    geo_test.transf()
    