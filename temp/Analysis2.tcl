# 或其它求解器
system BandGeneral
# 约束处理器
constraints Transformation
# 自由度编号器   
numberer RCM
# 收敛测试
test NormDispIncr 1.0e-6 10 
# 求解算法（非线性分析常用）
algorithm KrylovNewton     
# 2. 设置积分器：采用荷载控制，每步荷载增量为0.1（即分10步施加完总重力）
integrator LoadControl 0.1
# 3. 定义分析类型
analysis Static
# 4. 执行分析，进行10步
analyze 10