import openseespy.opensees as ops


ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)

ops.node(1, 0, 0, 0)
ops.node(2, 0, 2, 0)
ops.node(3, 0, 1, -1)

ops.uniaxialMaterial('Elastic', 1, 3000)
ops.uniaxialMaterial('InitStressMaterial', 2, 1, 5000)


ops.element('corotTruss', 1, 1, 3, 0.01, 2)
ops.element('corotTruss', 2, 2, 3, 0.01, 2)

ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.fix(2, 1, 1, 1, 1, 1, 1)
ops.fix(3, 0, 0, 0, 1, 1, 1)

ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(3, 0, 0, -1000, 0, 0, 0)

ops.system('BandGeneral')
ops.numberer('RCM')
ops.test('NormDispIncr', 0.0001, 40, 2)
ops.algorithm('KrylovNewton')
ops.constraints('Plain')
ops.integrator('LoadControl', 0.1)
ops.analysis('Static')
for i in range(10):
    ops.analyze(1)
    print(ops.nodeDisp(3, 3))