# T02 配置与缓存：步骤和结果

本任务由execution_config实现，服务容量错误中断其报告阶段后，主agent接管集成和独立复验。

## 实施步骤

1. 审计v1缓存，只校验缺陷幅值、长度分组、步数、分段等少量字段，无法识别实际材料、方法、源文件和算法变化。
2. 新增config.py六个配置块：model、steel、boundary、protocol、solver、calibration。完整Steel02参数与源码/S2K/引擎指纹均进入配置身份。
3. 加入actual_length/representative_length和分组误差记录，保留Python旧round规则并测试分组边界。
4. 新增v2缓存格式。完整内容和各组有指纹；不完整/损坏/不同身份的库明确拒绝，不能默默重用或重标定。
5. 缓存临时文件写完并fsync后，用同文件系统原子发布且不覆盖已有目标；独占锁防止竞争写入。
6. v1库仅在allow_legacy_calibration_cache=True时只读；标legacy_unknown，不能把本次请求配置的指纹冒充其生成配置。
7. 新增ReferenceNonconvergence携带部分计算的真实AnalysisResult。只有显式perry_exploratory才允许该类型失败进入探索性回退；输入或程序异常直接传播。
8. 新失败证据另存唯一文件，保存实际已完成步数、终点和失败原因，不清零假装未计算。
9. 主agent在experiment.py接入ReferenceSolverConfig。严格配置所有算法保持1e-8容差；legacy显式保留旧1e-7回退并记录relaxes_tolerance。
10. 主agent接全塔缓存参数、CLI、experiment/实际缓存指纹和非空输出目录保护；诊断复现明确使用legacy只读授权。

## 文件

- initial_imperfection_material/config.py
- initial_imperfection_material/calibration_cache.py
- model/tower_model_with_equivalent_imperfection.py
- initial_imperfection_material/experiment.py
- initial_imperfection_material/full_tower_cyclic.py
- initial_imperfection_material/diagnose_tower_convergence.py
- tests/test_calibration_config.py
- tests/test_member_state_recorder.py（严格回退/目录保护集成测试）

## 实际测试

主agent执行：`.venv/bin/python -m unittest discover -s tests -p 'test_calibration_config.py' -v`。
21/21通过，0.436秒。另7项记录及入口测试通过，包含回退异常后恢复算法与原容差、不覆盖已有运行目录。

覆盖内容：配置序列化、物理字段/方法/边界/源码等身份变化、负/零/NaN输入、组边界、半写入JSON、内容篡改、未完成库、竞争锁、原子发布失败、旧库授权、错误方法、程序错误传播、部分参考失败和显式探索性回退。

agent另外对实际旧库做只读冒烟：194组，其中1组为Perry回退（对应4根原杆），未重标定、未建立全塔域，原缓存SHA256保持不变。正式保护目录最终还由baseline_snapshot复核。

## 最后结果与范围

配置和缓存的工程能力已落地，仍保留既有物理参数，不能据此宣布二维铰接骨架已适用于空间全塔。
新库显式记录耦合未保留和边界类别；缓存命中只证明身份相同，不证明物理验证。
T09后实际关键杆重标定仍须使用通过参考收敛的设置；不运行194组来替代T08。

现有等效构造器默认标定回退策略变为error，旧缓存需要显式授权；旧调用应使用新增参数或选择新的独立库路径。
