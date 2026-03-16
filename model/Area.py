import os
import re
from numpy import array
from numpy import cross
from numpy import linalg
from numpy import cos
from numpy import sin
from numpy import pi
from numpy import sqrt
from math import e
class Area:
    def get_area(self):
        #计算输电塔的风荷载输入

        os.chdir("./model")
        def SearchKeyword(keyword, lines):
            for index, line in enumerate(lines):
                if keyword in line:
                    # 目标关键字在文件的第index行（注意python中计数从0开始，即文件中第一行的index为0）
                    # 目标关键字所在行下一行的行号为index + 1
                    startline = index + 1
                    break
            else:
                # startline = f"未在文件中发现{key_word}"，返回-1，建模关键信息若返回-1则应报错
                startline = -1
            return startline
        # ------------------------------------------------------------------------------

        """
        node_dict形如[node_num_1:{X_1,Y_1,Z_1,0},
                        node_num_2:{X_2,Y_2,Z_2,0},...]
        """
        node_dict = {}
        with open('../Src/Node.tcl', 'r') as f:
            lines = f.readlines()
            for line in lines:
                if 'node' in line:
                    node_dict[line.split()[1]] = [line.split()[2],line.split()[3],line.split()[4],0]


        """
        element_dict形如[[element_num_1,node1_1,node2_1],
                        [element_num_2,node1_2,node2_2],...]
        """
        element_dict = []
        with open('../Src/Element.tcl', 'r') as f:
            lines = f.readlines()  
            for line in lines:
                    element_dict.append([line.split()[2],line.split()[3],line.split()[4]])


        """
        局部坐标轴geo_dict形如[[element_num_1,cos_x_1,cos_y_1,cos_z_1],
                                [element_num_2,cos_x_2,cos_y_2,cos_z_2],...]
        """
        geo_dict = []
        with open('../Src/geomtransf.tcl', 'r') as f:
            lines = f.readlines()
            for line in lines:
                geo_dict.append([line.split()[2],line.split()[3],line.split()[4],line.split()[5]])


        '''
        获取element的截面信息,section_dict形如[[element_num_1,section_num_1],
        '''
        section_dict = []
        with open("../Source/Z30103A6.s2k", "r") as f:
            lines = f.readlines()
            startline = SearchKeyword('FRAME SECTION ASSIGNMENTS', lines)
            for line in lines[startline:]:
                if not line.isspace():
                    section_dict.append([line.split()[0].split('=')[1],line.split()[3].split('=')[1]])
                else:
                    break
                
                
        # def Force(node_i,node_j,Geo_cood,section,theta):
        #     #计算风荷载
        #     #风荷载的计算公式为F = 0.5 * ρ * V^2 * A * C
        #     #ρ为空气密度，V为风速，A为受力面积，C为风荷载系数
        #     #空气密度ρ取1.225kg/m^3，风速V取30m/s，受力面积A取截面积，风荷载系数C取1.2
        #     #风荷载的方向与风速方向一致
        #     #风荷载的大小为F = 0.5 * 1.225 * 30^2 * A * 1.2
        #     #风荷载的方向为F = 0.5 * 1.225 * 30^2 * A * 1.2 * cos(θ) * cos(α) + 0.5 * 1.225 * 30^2 * A * 1.2 * sin(θ) * sin(α)
        #     #其中θ为风向与X轴的夹角，α为风向与Z轴的夹角
        #     #风向与X轴的夹角θ取0°，风向与Z轴的夹角α取0°
        #     #风荷载的大小为F = 0.5 * 1.225 * 30^2 * A * 1.2
        #     #风荷载的方向为F = 0.5 * 1.225 * 30^2 * A * 1.2 * cos(θ) * cos(α) + 0.5 * 1.225 * 30^2 * A * 1.2 * sin(θ) * sin(α)
        #     #其中θ为风向与X轴的夹角，α为风向与Z轴的夹角
        #     #风向与X轴的夹角θ取0°，风向与Z轴的夹角α取0°
        #     L = sqrt((node_i[0]-node_j[0])**2+(node_i[1]-node_j[1])**2+(node_i[2]-node_j[2])**2)
        #     #角钢d
        #     d = int(section.split('L')[1].split('x')[0])*0.001
        #     w_0 = 40**2/1600*1000    
        #     mu_s = 1.3
        #     mu_z = 1.2
        #     beta_z = 1.2
        #     w_k = mu_s * mu_z * beta_z * w_0
        #     Geo_cood = array([float(Geo_cood[0]),float(Geo_cood[1]),float(Geo_cood[2])])
        #     #计算两个直角面的投影面积(先计算两个面与风向垂直面的夹角,实际计算风向量与直角面法向量的夹角余弦)
        #     wind_vector = array([sin(theta),cos(theta),0])
        #     #直角面1
        #     mian1_vector = Geo_cood
        #     cos_theta_1 = abs(wind_vector.dot(mian1_vector)/(linalg.norm(wind_vector)*linalg.norm(mian1_vector)))
        #     #直角面2
        #     L_vector = array([node_j[0]-node_i[0],node_j[1]-node_i[1],node_j[2]-node_i[2]])
        #     mian2_vector = cross(Geo_cood,L_vector)
        #     cos_theta_2 = abs(wind_vector.dot(mian2_vector)/(linalg.norm(wind_vector)*linalg.norm(mian2_vector)))
        #     A_1 =  L * d * cos_theta_1
        #     A_2 =  L * d * cos_theta_2
        #     A = A_1 + A_2
        #     F = w_k * A
        #     Force_I = 0.5 * F
        #     Force_J = 0.5 * F
        #     return Force_I,Force_J

        def A_s(node_i,node_j,Geo_cood,section,theta):
            L = sqrt((node_i[0]-node_j[0])**2+(node_i[1]-node_j[1])**2+(node_i[2]-node_j[2])**2)
            #角钢d
            d = int(section.split('L')[1].split('x')[0])*0.001
            Geo_cood = array([float(Geo_cood[0]),float(Geo_cood[1]),float(Geo_cood[2])])
            #计算两个直角面的投影面积(先计算两个面与风向垂直面的夹角,实际计算风向量与直角面法向量的夹角余弦)
            wind_vector = array([sin(theta),cos(theta),0])
            #直角面1
            mian1_vector = Geo_cood
            cos_theta_1 = abs(wind_vector.dot(mian1_vector)/(linalg.norm(wind_vector)*linalg.norm(mian1_vector)))
            #直角面2
            L_vector = array([node_j[0]-node_i[0],node_j[1]-node_i[1],node_j[2]-node_i[2]])
            mian2_vector = cross(Geo_cood,L_vector)
            cos_theta_2 = abs(wind_vector.dot(mian2_vector)/(linalg.norm(wind_vector)*linalg.norm(mian2_vector)))
            A_1 =  L * d * cos_theta_1
            A_2 =  L * d * cos_theta_2
            As = A_1 + A_2
            return As

        #遍历element_dict,将风荷载施加到node上
        theta = 0

        #创建A_s的空字典，用来存储每个element的投影面积
        A_S = {}
        for i in range(12):
            A_S[i]=[]

        #为了计算塔架背面风荷载降低系数，需要统计每一段的迎风面的投影面积A，以及每一段迎风面构件的总投影面积A_s
        for element in element_dict:
            node_i_num = element[1]
            node_j_num = element[2]
            for node,node_value in node_dict.items():
                if node_i_num == node:
                    node_i = array([float(node_value[0]),float(node_value[1]),float(node_value[2])])
                if node_j_num == node:
                    node_j = array([float(node_value[0]),float(node_value[1]),float(node_value[2])])
            Geo_cood = geo_dict[int(element[0])-1][1:]
            section = section_dict[int(element[0])-1][1]
            #计算此单元投影面积
            As = A_s(node_i,node_j,Geo_cood,section,theta)
            #判断此单元在第几段，是否为迎风面构件
            #首先是判断通过z坐标判断在第几段
            if 0<node_i[2]<3.2 or 0<node_j[2]<3.2 or (node_i[2] == 3.2 and node_j[2] == 3.2):
                if node_i[1] < -3.2 and node_j[1] < -3.2:
                    A_S[0].append(As)
            if 3.2<node_i[2]<6.8 or 3.2<node_j[2]<6.8 or (node_i[2] == 6.8 and node_j[2] == 6.8):
                if node_i[1] < -2.9 and node_j[1] < -2.9:
                    A_S[1].append(As)
            if 6.8<node_i[2]<9 or 6.8<node_j[2]<9 or (node_i[2] == 9 and node_j[2] == 9):
                if node_i[1] <= -2.7 and node_j[1] <= -2.7:
                    A_S[2].append(As)
            if 9<node_i[2]<13.2 or 9<node_j[2]<13.2 or (node_i[2] == 13.2 and node_j[2] == 13.2):
                if node_i[1] <= -2.49 and node_j[1] <= -2.49:
                    A_S[3].append(As)
            if 13.2<node_i[2]<17.4 or 13.2<node_j[2]<17.4 or (node_i[2] == 17.4 and node_j[2] == 17.4):
                if node_i[1] <= -2.28 and node_j[1] <= -2.28:
                    A_S[4].append(As)
            if 17.4<node_i[2]<21.6 or 17.4<node_j[2]<21.6 or (node_i[2] == 21.6 and node_j[2] == 21.6):
                if node_i[1] <= -2.07 and node_j[1] <= -2.07:
                    A_S[5].append(As)
            if 21.6<node_i[2]<24 or 21.6<node_j[2]<24 or (node_i[2] == 24 and node_j[2] == 24):
                if node_i[1] <= -1.95 and node_j[1] <= -1.95:
                    A_S[6].append(As)
            if 24<node_i[2]<27 or 24<node_j[2]<27 or (node_i[2] == 27 and node_j[2] == 27):
                if node_i[1] <= -1.95 and node_j[1] <= -1.95:
                    A_S[7].append(As)
            if 27<node_i[2]<30 or 27<node_j[2]<30 or (node_i[2] == 27 and node_j[2] == 30):
                if node_i[1] <= -1.95 and node_j[1] <= -1.95:
                    A_S[8].append(As)
            if 30<node_i[2]<33 or 30<node_j[2]<33 or (node_i[2] == 33 and node_j[2] == 33):
                if node_i[1] <= -1.95 and node_j[1] <= -1.95:
                    A_S[9].append(As)
            if 33<node_i[2]<36.4 or 33<node_j[2]<36.4 or (node_i[2] == 36.4 and node_j[2] == 36.4):
                if node_i[1] <= -0.85 and node_j[1] <= -0.85:
                    A_S[10].append(As)
            if 37<node_i[2]<39.6 or 37<node_j[2]<39.6 or (node_i[2] == 39.6 and node_j[2] == 39.6):
                if node_i[1] <= -0.5 and node_j[1] <= -0.5:
                    A_S[11].append(As)
        with open("A_S.txt","w") as testa:
            for i in A_S.values():
                testa.write(str(i)+"\n")

        #对A_S每一个key对应所有的values求和
        for keys,values in A_S.items():
            sum = 0
            for i in values:
                sum += i
            A_S[keys] = sum 

        return A_S

if __name__ == "__main__":
    a = Area()
    for key,value in a.get_area().items():
        print(key,value)