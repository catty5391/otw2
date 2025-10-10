#封装一个类，用来读取element相关信息，包括（单元编号，单元两端节点编号）
#在构造类时，选择单元类型，沿单元方向积分点个数

#!! 暂时不能确定的是

  #element dispBeamColumn $eleTag $iNode $jNode $numIntgrPts $secTag $transfTag <-mass $massDens> <-cMass> <-integration $intType>



from Search_keyword import Search_keyword as sk
import os
import pandas as pd


class Element():
    def __init__(self, path, num_intgrPts):
        self.keyword = "CONNECTIVITY - FRAME"
        self.path = path
        self.num_intgrPts = num_intgrPts

    def startline(self):
        obj = sk(self.path, self.keyword)
        start_line, lines = obj.Search()
        return start_line, lines
    
    def write(self):
        start_line, lines = self.startline()
        if start_line == -1:
            print("缺少单元信息")
        else:
            with open('./Src/Element_temp.csv', 'w') as El:
                for line in lines[start_line:]:
                    # 如果不是空行就一直遍历下去
                    if not line.isspace():
                        result = line.split()
                        n = result[0].split('=')[1]
                        i = result[1].split('=')[1]
                        j = result[2].split('=')[1]
                        #写入信息包括element dispBeamColumn + 单元编号 + 左节点编号 + 右节点编号 + 积分点个数 + 转换坐标编号（还缺一个截面编号）
                        El.write(f'element dispBeamColumn {n} {i} {j} {self.num_intgrPts} {n}\n')
                    else:
                        print('单元信息部分读取完成')
                        break
    #将element_temp.csv 文件中部分信息提取出来，供后续使用


    #追加写入截面编号
    def add_write(self):
        ele_mat = pd.read_csv("./Src/Mat_Section_element_temp.csv", header=None, sep= " ")
        secTag_mat = pd.read_csv("./Src/sectionTag_section_temp.csv", header=None, sep= " ")
        ele_temp = pd.read_csv("./Src/Element_temp.csv", header=None, sep= " ")
        ele_temp.columns = ['element', 'nonlinearBeamColumn','eletag','nodei','nodej','internum','trantag']
        with open("./Src/Element.tcl", 'w') as ele:
            for _,each in ele_temp.iterrows():
                eleTag = each['eletag']

                mat = ele_mat[ele_mat.iloc[:,0] == eleTag].iloc[0].iloc[1]

                secTag = secTag_mat[secTag_mat.iloc[:,1] == mat].iloc[0].iloc[0]
 
                # #dispBeamColumn 建模
                # ele.write(f"element dispBeamColumn {each['eletag']} {each['nodei']} {each['nodej']} {each['internum']} {secTag} {each['eletag']}\n")

                # truss建模
                ele.write(f"element trussSection {each['eletag']} {each['nodei']} {each['nodej']} {secTag}\n")


    
    @staticmethod
    def output():
        if os.path.exists('./Src/Element_temp.csv'):
            ele_df = pd.read_csv("./Src/Element_temp.csv", header = None, sep = " ")
            ele_df = ele_df.iloc[:, [2,3,4]]
            ele_df.columns = ['eleTag', 'nodei', 'nodej']
            ele_df["eleTag"] = ele_df["eleTag"].astype('int64')
            ele_df["nodei"] = ele_df["nodei"].astype('int64')
            ele_df["nodej"] = ele_df["nodej"].astype('int64')
            return ele_df
        else:
            print("请先进行节点读取")
                    


if __name__ == "__main__":
    ele_test = Element("./Source/ZK3010A_rename.s2k", 4)
    ele_test.write()
    ele_test.output()
    ele_test.add_write()
