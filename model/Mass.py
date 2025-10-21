from Search_keyword import Search_keyword as sk

class Mass():
    def __init__(self, path):
        self.path = path
    def generate_mass(self):
        path = self.path
        keyword = "ASSEMBLED JOINT MASSES"
        with open("./Src/Mass.tcl",'w') as mass:
            startline, lines = sk(path, keyword).Search()
            for line in lines[startline:]:
                if not line.isspace():
                    each = line.split()
                    nodeTag = each[0].split('=')[1]
                    x_mass = each[2].split('=')[1]
                    y_mass = each[3].split('=')[1]
                    z_mass = each[4].split('=')[1]
                    mass.write(f"mass {nodeTag} {x_mass} {y_mass} {z_mass} 0 0 0\n")
                else:
                    print("节点质量写入完成")
                    break

if __name__ == "__main__":
    m = Mass("./Source/ZK3010A_mass.s2k")
    m.generate_mass()
