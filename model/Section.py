from Search_keyword import Search_keyword as sk
from L_steel_secmesh import L_steel_section as lss
from SecMesh import SecPlain 
from SecMesh import ops_sec_vis
import openseespy.opensees as ops
import pandas as pd
class Section():

    def __init__(self,path):
        self.path = path
        self.keyword = "FRAME SECTION ASSIGNMENTS" 
    #此方法用来生成单元，截面，材料的对应关系，同时生成section.tcl文件
    def Element_Section(self):
        keyword = self.keyword
        path = self.path
        startline, lines = sk(self.path, keyword).Search()
        section_set = set()
        with open("./Src/Mat_Section_element_temp.csv",'w') as f_temp:
            for line in lines[startline:]:
                if not line.isspace():
                    each = line.split()
                    eleTag = each[0].split('=')[1]
                    section = each[3].split('=')[1].split('Q')[0]
                    material = each[3].split('=')[1].split('Q')[1]
                    f_temp.write(f"{eleTag} {section}Q{material}\n")
                    if material == '235':
                        mat_tag = 1
                    elif material == '345':
                        mat_tag = 2
                    elif material == '420':
                        mat_tag = 3
                    elif material == '460':
                        mat_tag = 4
                    else:
                        mat_tag = 0
                    section_set.add(f"{section}Q{material}@{mat_tag}")
                else:
                    "材料，截面，单元编号对应关系写入完成"
        
                    break
        return section_set

    def mesh(self):
        section_set = self.Element_Section()
        sectionTag = 1
        #保存截面编号和截面形状信息，方便后续单元配对截面编号
        with open("./Src/sectionTag_section_temp.csv", 'w') as f:
            for section in section_set:
                instance = lss(section.split('@')[0], sectionTag, int(section.split('@')[1]))
                instance.outline()
                instance.mesh()
                f.write(f"{sectionTag} {section.split('@')[0]}\n")
                sectionTag += 1
                



if __name__ == "__main__":
    sec = Section("./Source/ZK3010A_rename.s2k")
    sec.mesh()