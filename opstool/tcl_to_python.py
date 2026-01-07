
import openseespy.opensees as ops
import os
import opstool as opst

os.chdir(os.path.dirname(os.path.abspath(__file__)))
opst.pre.tcl2py(input_file='../Src/Main.tcl',output_file='Openseespy_Main',prefix="ops")