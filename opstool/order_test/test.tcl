# 此文件用来进行命令转化测试

# 纤维坐标应力应变提取
recorder Element -file Element1.out -time -ele 3 section 1 fiber 0.10 0.10 stressStrain

# Load 转化
pattern Plain 1 Linear {
   load 2 0. -2000. 0.;
   eleLoad -ele 1 -type -beamUniform 2000.;
   eleLoad -ele 2 -type -beamUniform 0 2000.;
   eleLoad -ele 3 -type -beamUniform 0 0 -2000.;
};