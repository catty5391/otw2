# N07/N08 瞬态适配实施规格（本批尚未实现）

1. 在TMQ模块建立专用runner，或向旧runner注入明确的wind_loader/analysis配置/observer；旧API目前只含model_factory与initialize_model等已有钩子，不接受这些拟议参数。
2. 每样本独立进程/域：建塔线→重力一次→平衡检查→冻结恒载→需要时平均风平衡→设定时程基点→定义阻尼→加载真实空间时变节点向量。保留初应力，禁止继承前次推覆状态。
3. 载荷schema：physical_time_s、node_tag、Fx/Fy/Fz/Mx/My/Mz、group_id、source_field_id、mean_or_fluctuating、units。独立空间组不同Path；负公共压力系数不是反风向。
4. solver schema：constraints、numberer、system、test（带单位/尺度）、algorithm、Newmark、dt/min_dt、尝试/时长上限。旧Plain/BandGeneral/NormDispIncr0.001不直接作为小扰动默认。
5. damping schema：scheme_id、目标来源、DOF覆盖、每种单元flag、节点/region、alphaM/betaK/betaKInit/betaKcomm及设置时机；候选K_gravity不能直接用betaKInit替代。
6. 输出真实accepted子步时刻、u/v/a、风/重力完整账本、惯性与阻尼、塔脚/远端反力、1528塔杆端力、导线/绝缘子轴力和TMQ历史分支。失败尝试另表，partial不补尾。
7. 观察坐标：沿风(cosα,sinα)、横风(-sinα,cosα)、RZ；控制X/H独立。旧漂移器Y平动/X转角约定需替换为显式截面运动，改变control_dof并不够。
8. 单元/小结构测试：解析振子幅值与相位、线性动力平衡、无质量转动、输入插值/起终点、标签清理、重复重力防护、A→B与独立B一致、失败回滚和记录关闭。
9. 全塔6主例：两模型各零扰动、自由衰减、谐波；最多2重试，先冻结幅值保持弹性。低频检验覆盖足够的5.126s周期，近重根通过投影/辨识分离拍振。
10. N08把实测C实现与候选C匹配；不匹配先回检N06离线截断，G2/G3不得通过。每步动态平衡Fext−Fint−Ma−Cv，平动与转动独立，含远端反力。
11. 能量完整检查只用于已知线性储能的小模型；非线性TMQ未知储能/耗散填null及原因。外功不能冒充滞回耗能。
12. 所有成果区分execution_status、assessment、physical_validation。候选谱、数值接入、真实角钢/气动的物理验证各自独立。
