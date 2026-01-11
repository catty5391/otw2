# This file is created by opstool.tcl2py(), author:: Yexiang Yan

import openseespy.opensees as ops

ops.recorder('Element', '-file', 'Element1.out', '-time', '-ele', 3, 'section', 1, 'fiber', 0.1, 0.1, 'stressStrain')
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 0.0, -2000.0, 0.0)
ops.eleLoad('-ele', 1, '-type', '-beamUniform', 2000.0)
ops.eleLoad('-ele', 2, '-type', '-beamUniform', 0, 2000.0)
ops.eleLoad('-ele', 3, '-type', '-beamUniform', 0, 0, -2000.0)
ops.loadConst('-time', 0.0)
