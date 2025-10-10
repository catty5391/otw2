# 封装一个用来划分角钢截面网格的类
# 创建角钢类，用来确定角钢的外轮廓线
# L型钢的命名 e.g. L100x7Q345
import openseespy.opensees as ops
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from SecMesh import SecPlain 
from SecMesh import ops_sec_vis
class L_steel_section():
    def __init__(self,Lsteel_name:str,num:int,matTags:int):
        self.Lsteel_name = Lsteel_name
        self.num = num
        self.matTags = matTags
    def outline(self):
        length = int(self.Lsteel_name.split('L')[1].split('x')[0])
        thickness= int(self.Lsteel_name.split('x')[1].split('Q')[0])
        length = float(length)*0.001
        thickness = float(thickness)*0.001
        point1 = (0., 0.)
        point2 = (length, 0.)
        point3 = (length, thickness)
        point4 = (thickness, thickness)
        point5 = (thickness, length)
        point6 = (0., length)
        self.outline = [point1, point2, point3, point4, point5, point6]
        return self.outline
    def mesh(self):
        points = self.outline
        sec =  SecPlain()
        sec.add_outline(points)
        sec.mesh(mesh_size = 0.006)
        sec.centring()
        
        output_dir = "./Src/Section.tcl"
        mat_Tags = self.matTags
        sec_tag = self.num
        sec.ops_cmds_tcl(output_dir, sec_tag, mat_Tags)

if __name__ == "__main__":
    test = L_steel_section("L100x7Q345",1,1)
    points = test.outline()
    sec =  SecPlain()
    sec.add_outline(points)
    sec.mesh(mesh_size = 0.006)
    sec.centring()
    sec.mesh_view()