from Node import Node
from Mass import Mass
from Element import Element
from GeometricTransf import GeometricTransf as gmt
from Section import Section
import os



if (os.path.exists("./Src/Section.tcl")):
    os.remove("./Src/Section.tcl")

nodes = Node("./Source/ZK3010A_rename.s2k")
nodes.write()

mass = Mass("./Source/ZK3010A_mass.s2k")
mass.generate_mass()

ele = Element("./Source/ZK3010A_rename.s2k", 8)
ele.write()

gm = gmt()
gm.transf()

sec = Section("./Source/ZK3010A_rename.s2k")
sec.mesh()

ele.add_write()




