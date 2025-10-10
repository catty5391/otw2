

from Search_keyword import Search_keyword as sk
import os
import pandas

#从s2k文件中读取Node信息， 并写入/src/Node.tcl 文件夹中
class Node():
    def __init__(self, path):
        self.keyword = "JOINT COORDINATES"
        self.path = path

    def startline(self):
        obj = sk(self.path, self.keyword)
        start_line, lines = obj.Search()
        return start_line, lines
    
    def write(self):
        start_line, lines = self.startline()
        if start_line == -1:
            print("缺少节点信息")
        else:
            with open("./Src/Node.tcl", 'w') as N:
            
                for line in lines[start_line:]:
                    if not line.isspace():
                        result = line.split()
                        n = result[0].split('=')[1]
                        x = result[3].split('=')[1]
                        y = result[4].split('=')[1]
                        z = result[5].split('=')[1]
                        N.write('node ' + n + ' ' + x + ' ' + y + ' ' + z + '\n')
                    else:
                        print("节点信息已生成")
                        break

    #用来返回Node.tcl 输出的node_dataframe
    @staticmethod
    def dataframe():
        if os.path.exists('./Src/Node.tcl'):
            node_df = pandas.read_csv("./Src/Node.tcl", header = None, sep = " ")
            node_df = node_df.iloc[:, [1,2,3,4]]
            node_df.columns = ['num', 'x', 'y', 'z']
            node_df["num"] = node_df["num"].astype('int64')
            return node_df
        else:
            print("请先进行节点读取")
            



if __name__ == "__main__":
    node_test = Node("./Source/ZK3010A_rename.s2k")
    node_test.write()
    print(node_test.dataframe().iloc[1])