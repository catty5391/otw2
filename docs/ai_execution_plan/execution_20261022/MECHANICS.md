# 力学执行线：步骤、结果与验收边界

批次：`execution_20261022`。任务：T01、T06，以及 T08 的局部参考与网格收敛证据。
执行角色：`execution_mechanics`。本角色没有改动现有两类塔模型、`material.py`、`experiment.py` 或全塔入口，没有启动全塔计算。
以下全塔边界由主 agent 的记录器烟测及新完整参考提供，局部试验采用独立 OpenSees 进程。

## 1. 最终结论

- **T01 审计完成**：完整参数、实际杆截面、角钢耦合、纯弹性 4×4/12×12 刚度和缺陷向量已有可复核结果。审计完成不表示现有等效模型已修复。
- **T06 基础接口与小幅验证完成**：同网格、初始态和完整重力、双端 6DOF 的小幅真实塔史重放通过；已补齐独立 pinned/clamped/转动弹簧边界、旧二维薄包装。完整往复和网格收敛放在 T08 验收，避免 T06/T07 循环依赖。
- **T08 部分完成**：前六个完整目标（±0.6% 范围）两关键杆同四段匹配，4/8/16 均完成，8→16 网格指标通过；完整九目标同网格验证、Fiber极值精度等仍有失败项，不能把运行完成写成验收完成。
- **完整G1未通过**：877全幅三组尝试后同网格路径仍不一致；825追加32段后全部提交点峰力/峰位达到网格门槛。前六目标的细Fiber端力敏感性很小，但纤维极值变化2.15%～3.46%，不能自动认定局部应力应变精度通过。
- 新增测试覆盖参数/坐标、真实矩阵、3D 明确边界、旧 2D 包装、6DOF 重放和 T08 工具；后文记录各轮实际数量。所有试验输出在新目录，旧证据未覆盖。
- 实质性发现是 **原等效梁遗漏角钢双向弯曲耦合**；不能在未处理这一差异时，仅更换轴向循环材料就宣称构件等效。

## 2. 实际执行步骤

1. 只读阶段完整阅读 `PLAN.md` 第 0～5 节、T01/T06/T08/T10/T11，以及单杆、分段塔、等效塔、截面生成和重力代码。
2. 等待主 agent 完成 G0 源码快照与 53/53 基线测试之后才写入。
3. 与配置 agent 统一 `Steel02Parameters` 字典字段：`E0, fy, b, R0, cR1, cR2, a1, a2, a3, a4, sig_init`，不建立相互冲突的第二套钢材类型。
4. 建集中机械配置与真实 S2K 读取适配器，复用原 `_l_section_rect_patches`，不另造第三套角钢几何。
5. 按实际塔数据选择 877、825、349、1：前两根为关键 Q235 杆；349 是实际 L125×8Q345 中间长度代表；1 是最大截面 Q420 类中编号最小代表，并非任意 3 m 演示杆。
6. 对每根杆构建真实 OpenSees 纯 `Elastic` 纤维梁，提取截面 4×4 与单元未凝聚 12×12 刚度；用独立 Hermite 应变矩阵积分核对，另检查刚体模态和轴伸、双向弯曲、扭转反力。
7. 用同坐标、同材料比较旧 `Aggregator` 的独立 P/Mz/My/T 通道；同时做 8×1→32×3 截面离散对照，不修改正式塔网格。
8. 按原 S2K 遍历和种子 30103 生成 **1528 根杆的显式全局缺陷向量**，供以后按杆号读取，避免加密/混合模型重排导致方向改变。
9. 实现三维单杆、半正弦缺陷/记录几何、实际完整 Steel02、双端 6DOF 历程重放和逐步纤维极值记录。
10. 用主 agent 的重力 + ±0.001% 漂移小幅往复烟测历史，重放 877/825。第一轮直接规定端位移出现局部 Newton 失败，保留原始失败产物。
11. 只进行三个有明确假设的小对照：纯 Elastic、删除重复阶段起点、显式分十个边界子步。前者及分子步可完成，单纯删除重复起点不能解决。
12. 采用显式 `--boundary-substeps 10` 后，两杆各 160/160 子步完成，原记录点端力与全塔误差远低于 1e-6。保存所有提交子步，不把它们冒充原全塔步数。
13. 主 agent 追加要求后，完成同一小幅历史 20 子步对照：两杆各 320/320，10→20 子步结果在原记录点处的相对差分别为 4.986e-11、3.349e-13。
14. 新增主轴旋转隔离原型：对纤维截面二阶矩求主轴，同时旋转 `geomTransf`，用主惯性独立弯曲通道恢复原全局耦合刚度；没有修改生产塔。
15. 新增三维 pinned/clamped/四弯曲转动弹簧边界，几何与所有分段方向一起旋入原杆坐标；旧 2D 仅薄包装，显式传钢材和不放宽容差的求解配置。
16. 新增 T08 顺序网格工具，源清单未完成拒绝运行；四段重放不匹配则停止该杆，不继续用加密掩盖错误。先用已完成烟测验工具，强非线性全协议须等待主 agent 采集完成。
17. 新增显式准静力共同平移消除选项：对每步两端同减端 i 的平移，保持所有相对位移、转角和截面方向，再给输出的所有节点补回该平移。以解析力/全局坐标恢复测试验证，原小幅历史无需子步也完成。
18. 全协议全塔仍在运行时，主 agent 导出从未加载初态开始、包含完整重力及前六个完整目标的独立前缀证据。新增清单校验：源 run ID、前缀及元数据 SHA256、提交步连续性、各目标进度完整性、末步及限定范围均须匹配，不允许把运行中的父计算标为完成。
19. 对这个截至 −0.6% 漂移的前缀先做 877/825 同四段匹配；两杆均复现原塔。随后做 4/8/16 段，并按事先限定的三组数值对照依次采用每原记录间隔 1、4、8 个显式边界子步，其他物理参数和容差保持不变。每组失败产物单独保留。
20. 新完整参考清单完成后，仅使用这一完整源做全幅网格。877按批准上限完成8子步、16子步、16子步显式三算法三个对照，最终数值完成但同网格路径不一致，停止加密；未继续试凑。
21. 825的全幅8→16未达网格门，于是复用既有证据仅追加32段。原点峰位指标受采样影响，进一步扫描已有全部提交子步定位峰，保留两种统计口径和原false表。
22. 在已通过的前六目标域，完成固定16段的32×3 Fiber敏感性以及878/828同四段重放；发现纤维极值仍有2%以上变化，镜像杆也不能无条件删除。
23. 本角色42项专项测试实际通过；主 agent 最终全仓264/264通过（16.440s）。所有本角色计算进程均已结束，没有留下后台重算。

## 3. 新增接口与文件

| 文件 | 实际提供的功能 |
|---|---|
| `model/mechanical_profile.py` | 不可变 Steel02 参数、legacy/aligned 配置、真实构件/纤维读取、局部坐标、完整耦合截面与解析梁刚度、缺陷向量 |
| `initial_imperfection_material/audit_mechanics.py` | 可运行的 T01 审计 CLI、JSON/CSV、刚度矩阵和图 |
| `initial_imperfection_material/member_reference_3d.py` | 3D 分段参考、完整端部历程导入、显式边界子步、pinned/clamped/弹簧、旧二维包装、已提交状态和同网格对比 |
| `initial_imperfection_material/member_reference_convergence.py` | T08 4/8/16 顺序研究、源清单门槛、阶段对齐指标、gzip 无损状态与图 |
| `initial_imperfection_material/member_reference_fiber_sensitivity.py` | 已验证 legacy 同网格后，仅改变 Fiber 的独立敏感性入口；固定分段、边界子步与缺陷 |
| `initial_imperfection_material/member_reference_extension.py` | 只追加未通过杆的一个新加密网格，引用既有同4段及16段证据，不重算已完成案例 |
| `initial_imperfection_material/state_archive.py` | 逐状态流式读取旧 gzip，避免为端力比较把全部详细截面展开到内存 |
| `tests/test_model_mechanical_parity.py` | 参数/截面/坐标/真实引擎一致性与主轴原型测试 |
| `tests/test_member_reference_3d.py` | 边界重放/缺陷/可逆性/明确释放/二维包装/紧凑状态测试 |
| `tests/test_member_reference_convergence.py` | 缺陷重建、往复阶段对齐、部分覆盖与未完成源拒绝测试 |
| `tests/test_member_state_archive.py` | 低内存流式读取、嵌套同名键/转义/截断拒绝 |
| `tests/test_member_reference_fallback.py` | 默认保持、真实失败恢复小模型、时间异常停止与显式算法校验 |
| `tests/test_member_reference_extension.py` | 源指纹、同网格门、前网格完整性和不必要加密的准入拒绝 |

钢材注册示例：

```python
from model.mechanical_profile import Steel02Parameters
parameters = Steel02Parameters.legacy_tower(E0=210e9, fy=235e6, b=0.03)
ops.uniaxialMaterial(*parameters.opensees_arguments(tag))
metadata = parameters.as_dict()
```

`aligned_v1` 使 member/tower 两类参数都显式采用原塔 Steel02 设置，但只是配置声明，没有悄悄改变旧单杆或旧塔默认值。

### 3.1 步号的明确映射：不能把同名字段混用

- 父全塔 JSONL 的 `accepted_step`：所有记录的连续序号，包含初态、重力和阶段起点；本完整源为0～606。
- 父全塔 JSONL 的 `source_step`：全塔循环分析提交步，**不是上面的连续记录序号**。
- `BoundaryPoint.source_step` 及局部 archive 的 `source_step`：本接口保存的是**父记录 accepted_step**，用于无歧义对齐；不能直接当成父循环步。
- 局部 archive 的 `accepted_step`：局部求解的已提交子步编号；例如8子步时完成4848步。

插值子步的局部 `source_step` 取它所趋近的右端父记录序号，因此同号可以出现多次；定位中间状态必须同时使用局部提交子步、stage和progress。

所有转换都应回查同一父行，不可全局减一个固定偏移，因为每个阶段起点都会增加记录。

| 事件 | 局部source_step / 父accepted_step | 父source_step（真实全塔循环步） |
|---|---:|---:|
| 六目标前缀终点 | 267 | 251 |
| 原塔877首次名义fy指示 | 371 | 354 |
| 原塔878首次名义fy指示 | 374 | 357 |
| 825细网格压峰所在原区间起点 | 512 | 494 |
| 同一区间终点 | 513 | 495 |
| 877首次单原点误差超过1e-6 | 524 | 506 |
| 877前两组最后成功原点 | 529 | 511 |
| 877前两组失败所趋近原点 | 530 | 512 |

因此文中“529→530”与“512→513”均指父记录序号，不是全塔循环步；主报告中的原事件354/357则是真正循环步。

## 4. T01 定量结果

### 4.1 实际构件与误差表

| 原杆 | 截面 | 长度 m | 8×1 弱主惯性误差 | 32×3 弱主惯性误差 | 独立弯曲通道相对纤维弯曲矩阵差 |
|---|---|---:|---:|---:|---:|
| 877 | L40×3 Q235 | 0.850000 | −1.9876% | −0.1544% | 51.4842% |
| 825 | L40×3 Q235 | 1.950000 | −1.9876% | −0.1544% | 51.4842% |
| 349 | L125×8 Q345 | 1.602379 | −1.8440% | −0.1370% | 51.5376% |
| 1 | L220×18 Q420 | 1.615921 | −2.0917% | −0.1670% | 51.4469% |

8×1 的单坐标 I22/I33 误差约 −0.74%～−0.85%，虽满足该单项 1% 门槛，弱主惯性误差却约 2%。不能用单坐标误差掩盖主轴精度。

真实 OpenSees 与独立解析 12×12 刚度的无量纲相对误差为 **1.32e-16～6.18e-16**；刚体模态相对残差不超过 **2.13e-17**。
说明当前纤维几何和本轮解析坐标转换相符，不存在本次审计中可见的轴向面积重复缩放或矩阵自由度错配。

### 4.2 I23 必须按同一符号约定理解

截面顺序为 `[P, Mz, My, T]`，纤维应变为 `eps0 - y*kappa_z + z*kappa_y`。
因此交叉切线是 `-E*sum(A*y*z)`。本项目角钢两个正向肢在形心坐标下 `sum(A*y*z)` 为负，
而 S2K 的正 `I23` 与相应正交叉刚度数值匹配；不能把两个字段符号不同直接认定为错误。
该约定已对照 [OpenSees 当前 FiberSection3d 源码](https://github.com/OpenSees/OpenSees/blob/master/SRC/material/section/FiberSection3d.cpp)，并由本机 3.8.0 引擎试验核对。

旧等效 `Aggregator` 将这项交叉刚度设为零。对四根代表杆，弯曲 2×2 矩阵的 Frobenius 相对差约 **51.45%～51.54%**；
其最弱主方向初始刚度比原 8×1 纤维截面高 **152.06%～152.72%**。
这只是截面/初始纯弹性差异，不等同于“全塔刚度高 152%”，也不是已证明的原不收敛卡点贡献率。

### 4.3 简单主轴旋转能否修复这一初始弹性差异

追加的**隔离纯弹性原型**使用原 Fiber 离散二阶矩求主轴，并将 `geomTransf` 的截面轴一起旋转；
随后在主轴系使用独立 Elastic My/Mz。返回同一个全局坐标下完整 12×12 矩阵，与 Fiber 比较：

| 原杆 | 全局矩阵相对误差 |
|---|---:|
| 877 | 6.5275e-16 |
| 825 | 5.9900e-16 |
| 349 | 5.0212e-16 |
| 1 | 8.6565e-16 |

因此，这一**初始弹性弯曲耦合遗漏**可以用正确的主轴变换解决，不需要为此立即开发 C++ 材料。
这不解决轴弯塑性耦合、实际端部屈曲边界或循环记忆，也没有将整塔新材料宣布通过。原型明确使用 Fiber 离散惯性匹配；
如果改用连续 S2K 主惯性，仍需单独保留纤维离散误差。

### 4.4 逐字段差异与处置

| 字段 | 单杆旧基准 | 分段塔 | 等效塔 | 处置 |
|---|---|---|---|---|
| E、fy、b | 当前 210 GPa/实际等级/0.03 | S2K/实际等级/0.03 | 标定构件中读取 | 当前值兼容；缓存仍必须纳入 |
| a1/a2/a3/a4 | 隐式 0/1/0/1 | .0005/.01/.0005/.01 | 轴向载体并非 Steel02 | 循环验证前明确统一或分别保留 |
| R0/cR1/cR2 | 20/.925/.15 | 相同 | 轴向载体不同 | 显式入配置 |
| 纤维 | 30×3 弱轴二维投影 | 8×1 空间角钢 | 无轴弯耦合 Fiber | 不能宣称完全同截面本构 |
| 梁积分 | Legendre6 | Legendre6 | Legendre3 | 初始弹性可核对，非线性仍需收敛证据 |
| 端部 | 二维铰接 | 空间节点共享 6DOF | 空间节点共享 6DOF | 同边界重放优先 |
| 初缺陷 | 确定弱轴平面半正弦 | 随机方向半正弦 | 已在轴向骨架内等效 | 保留向量，防止重复计入 |
| 质量/重力 | 单杆无塔重力史 | 原节点 S2K 集中质量 | 原节点同质量 | 原分点无质量；局部重放不另加自重 |

Steel02 省略参数的默认值来自 [官方 Steel02 说明](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html)，
不是依据报告中“没有显式写参数”自行猜测。

## 5. T06 小幅真实边界重放结果

输入是 `recorder_smoke_v1/segmented_reference/member_states.jsonl`：初始、10 个重力提交步，随后 ±0.001% 漂移并回零。
每根杆保留原四段坐标、局部轴、纤维网格、材料、积分方式；把原塔两端各 6DOF 规定给独立杆。
原端部外荷载不再加到局部试件，比较的是单元内部端力而非含外荷载的节点反力。

| 原杆 | 初次直接重放 | 显式 10 子步重放 | 端力历程无量纲相对误差 | 最大纤维应力 |
|---|---|---|---:|---:|
| 877 | 11/16 步后 Newton 失败 | 160/160，原点覆盖100% | 1.4932e-10 | 0.5753 MPa |
| 825 | 13/16 步后 Newton 失败 | 160/160，原点覆盖100% | 5.8826e-12 | 10.4085 MPa |

平动力误差最大约 1.08e-8 N，转动力矩误差最大约 2.51e-9 N·m。
这些应力远低于 fy，但仍只说明这段小幅协议；没有据此推断完整 ±1% 的局部纤维状态。

初次失败的定向对照显示：用 Elastic 可直接完成，Steel02 删除重复阶段起点仍失败，分细规定端位移后成功。
可以判断这是该局部规定边界求解设置需要处理的问题，不能将其标成真实杆件失稳。
端部大整体移动先于内部节点协调，可能让首轮非线性试算偏离实际小应变状态；本轮未记录每个失败试算的全部纤维，故不把该解释写成已逐纤维证明的因果结论。

已完成本小幅协议的 10/20 子步敏感性，两杆均通过：877 端力历程相对差 **4.9860e-11**，825 为 **3.3486e-13**。
正式强非线性重放仍须另做边界子步敏感性，不能用小幅结果代替。子步是实际提交状态，会影响有记忆材料的路径；不是只改变输出采样密度。

### 5.1 后续更合理的准静力共同平移处理

大端部规定平移会在内部节点尚未协调的首轮试算产生不必要的变形。局部杆没有中间外载，
准静力内力对所有节点相同的平移不敏感；因此新增可选 `--remove-rigid-translation`，
在求解时扣掉端 i 的全局平移，再将它补回全部输出节点。所有端部转角和相对位移保持不变，截面方向没有旋转。

该选项下原小幅历史 **不加子步**也使两杆各完成 16/16，端力历程相对误差为：877 **1.4557e-10**、825 **5.7861e-12**。
解析对照与输出节点全局坐标恢复测试通过。初始不收敛证据和旧 10/20 子步证据均保留，不作覆盖。
原未经共移处理的 877 十六段小幅重放仍曾数值失败；加入这一等价坐标处理后，4/8/16 段都完成。
这说明不能把上述局部求解失败当作物理屈曲。

这一选项限定准静力局部重放，**不能直接当成风振动力移动参考系**；动力情况下须显式处理惯性/阻尼及加速度转换。

### 5.2 T08 工具的小幅预验

`mesh_smoke_v2_comoving` 中两杆 4/8/16 均完成且四段与原塔匹配。
877 的 8→16 压力峰差为 **0.0022648%**，阶段进度加权 NRMSE 为 **0.0014968%**。
825 在这个小幅含重力协议内始终未形成受压峰，因此压力峰/峰位移验收不可评估；工具没有将“无峰”当作零误差通过。
这仅为工具和小幅参考预验，不代替 T08 完整 ±1% 协议。

紧凑保存不是丢弃失败或子步：每个提交步均保存端力、全部节点 DOF、分段内力/基本变形、纤维极值；
原全塔记录点和事件前后保留完整截面极值，其他子步采用较短字段。文件用 gzip 无损压缩，可用 `gzip.open(path, 'rt')` + `json.load` 读取。

### 5.3 六目标完整前缀：真实杆件状态与局部网格

源为 `reference_prefix_6_v1/member_states.jsonl`。它包含 **268 个提交样本**：初始态、完整重力及六个完整目标，依次为 ±0.1%、±0.3%、±0.6%。
最后 `accepted_step=267`，原循环 `source_step=251`；局部重放为保证一一对应，用全局唯一的 accepted_step 作为 BoundaryPoint.source_step。
父全塔还有后续 ±1% 及回零目标，本前缀不是完整九目标验收，也不是从中途恢复材料状态。

| 指标 | 877 | 825 |
|---|---:|---:|
| 前六目标最大绝对纤维应力 | 190.374 MPa（0.8101 fy） | 154.641 MPa（0.6580 fy） |
| 最大应力发生样本/阶段 | 178 / target5 | 267 / target6 |
| 任一端部转角分量最大绝对值 | 0.010981 rad | 0.010026 rad |
| target6 末，沿初始杆弦投影的端部轴力 | −31.557 kN | −23.604 kN |
| target6 末弦长应变 | −0.065299% | −0.049383% |
| 相对当步端弦的初始/最大杆内挠度 | 0.850 / 1.147 mm | 1.950 / 4.172 mm |
| 杆内挠度放大倍数 | 1.349 | 2.140 |

因此本限定范围内没有记录到这些杆的纤维达到 fy，也没有出现旧等效轴向骨架所对应的约 2.2% 深度压缩。
但 Steel02 有平滑转折，**低于 fy 不等于已证明严格弹性**；这张表不能单独给出塑性应变或稳定性判定。

`mesh_prefix6_v1`（每原间隔 1 子步、共同平移处理）：同四段原点端力历程误差 877 为 **4.9511e-10**、825 为 **1.9727e-10**，两者 267/267 均完成。
细分时 877 的 8 段在 164/267 后失败，未继续 16 段；825 的 8 段完成、16 段在 11/267 后失败。不能把这些失败点当作实际压屈承载力。

`mesh_prefix6_v2_sub4`（4 子步）使 825 的 4/8/16 段均完成 1068/1068：
4→8 峰值差 **1.0693%**，8→16 峰值差 **0.4991%**、有序阶段进度加权 NRMSE **0.02956%**，峰值缩短差为零。
877 的 4/8 段完成，4→8 峰值差 **0.02563%**；16 段在 634/1068 子步后失败，覆盖率 59.33%，不通过完整网格验收。
第三组 `mesh_prefix6_v3_sub8` 固定为 8 子步，**两杆三个网格均完整完成 2136/2136 子步**：

| 杆号 | 8→16 压峰差 | 8→16 有序 NRMSE | 峰值缩短差 | 该范围网格门槛 |
|---|---:|---:|---:|---|
| 877 | 0.007519% | 0.001115% | 0 | 通过 |
| 825 | 0.499080% | 0.029562% | 0 | 通过 |

三轮仅改变规定边界子步数，没有修改材料、Newton 算法或 1e-10 容差。1/4 子步局部失败不作为承载力证据，8 子步成功也不反向删除这些失败记录。
877 十六段只有 8 子步完整完成，不能因为其 4 子步部分历程很接近就声称全程步长敏感性通过；后续全协议仍需明确此项。
流式 4/8 子步后处理已经完成：877 的 4/8 段以及 825 的 4/8/16 段都覆盖全部 268 原点，端力矩按杆长无量纲化后相对差 **2.22e-14～1.28e-13**。
877 十六段共同覆盖 159/268 点，差为 4.56e-13，但明确记录 `full_coverage=false`，不算完整通过。

新增 Fiber 工具先要求源/历程 SHA256、同四段 legacy 匹配、固定细分网格通过，再单独改变 8×1→32×3。
因此不会把有意加密 Fiber 后的差异误判为同网格实现失败。工具本轮尚待完整源和算力释放后真实运行。
后处理曾尝试同时展开两份大 gzip；发现机器内存/调度压力后主动中断自己的只读进程，未删除或修改结果。
新网格算例另存小型原记录点索引，旧 gzip 改为逐状态流式读取，不重跑计算来取得后处理数据。

### 5.4 完整九目标：不能用前缀的通过代替全幅验收

主 agent 新采集的 `reference_legacy_v1` 已由清单确认完整完成：九目标、587 个循环提交步，含初态、重力及阶段起点共 607 条原记录。
局部完整输入为 606 个原间隔；8 子步对应 4848 个提交目标。没有拼接旧的 587 步结果。

`mesh_full_v1_sub8` 的结果：

| 原杆 | 同4段 | 8/16段 | 全幅结论 |
|---|---|---|---|
| 877 | 4232/4848 后失败；共同点端力误差 1.7736e-6 | 因同网格门失败而未运行 | 全幅局部参考尚未验收 |
| 825 | 4848/4848；端力误差 6.0719e-8，通过同实现门 | 两者都完整完成；8→16峰差 3.0069% | 全幅网格门不通过，需按计划追加32 |

825 的 4→8 压峰差 **10.3883%**、峰值缩短差 **8.0808%**；8→16 压峰差 **3.0069%**、阶段加权 NRMSE **0.4322%**、峰值缩短差零。
这与 ±0.6% 范围内 8→16 压峰差 0.4991% 并不矛盾：强幅协议进入了新的非线性范围，原四段不能作为已收敛真值。

877 的误差不是刚达到名义 fy 就增长：它在 target7（+1%）整个阶段的端力历程误差仍为 **2.1128e-9**。
首次单原点误差大于 1e-6 在 `accepted_step=524`（塔循环 `source_step=506`）、target8 进度 0.947802；
最后成功原点为 accepted529/source511，target8 进度 0.982143。
向下一个原点530/source512的第1/8试算子步失败。该杆未覆盖全塔随后出现的大塑性/大挠度部分。

第二组 `mesh_full_877_v2_sub16` 只将边界子步改为16，仍在 **8464/9696** 后、同一个529→530原区间的第1/16子步失败。
没有加密该杆，也没有提高容差。第三组按主 agent 批准，保持16子步及1e-10，仅加入显式固定序列 Newton→KrylovNewton→NewtonLineSearch(0.8)，这是本轮最后一组定向尝试。

新增回退不改变默认 Newton。逐尝试记录算法、返回码、迭代、范数、stage/progress/source及尝试前后时间，结束时恢复 Newton 和原 test。
失败时间回到上个提交值只是最小保护，**不等于全部内部变量回滚证明**；重试依赖 OpenSees StaticAnalysis 的失败步恢复机制。
三个专属测试通过，其中一个真实引擎小弹性算例故意以更严格的单迭代 test 触发 Newton 失败，后续 Krylov 恢复的端力与无失败控制一致；该控制不代表强塑性全状态认证。

第三组 `mesh_full_877_v3_sub16_fallback` 最终 **9696/9696 数值完成，但同四段端力历程误差 2.154462%，仍不通过 1e-6 门槛**。
target7 的误差仍为 2.11e-9，target8 上升到 **0.97065%**，最终回零 target9 达 **18.12114%**。
最大纤维应变为 0.06593611，原塔为 0.05836957（+12.963%）；最大纤维应力 648.399 MPa，原塔600.509 MPa（+7.975%）。
可以确定差异主要出现在后期强非线性及卸载路径，**不能据此宣称已证实某种分支/材料机制是唯一原因，或哪个数值解更物理**。
本轮三组已经用完，停止877全幅尝试，不加8/16、不改容差、不用前缀通过覆盖它。

### 5.5 825仅追加32段：区分原点采样与全部提交点峰值

`mesh_full_825_extension32_v1` 直接引用既有同四段和16段证据，仅计算新的32段，全幅 **4848/4848** 完成。
原记录点比较的16→32峰差 **0.74163%**、NRMSE **0.10410%**；峰缩短差 **2.27560%** 略大于2%，故原汇总仍保留 `passed=false`。

之后没有重算，而是流式扫描两份既有全部提交子步：

| 网格 | 压峰 N | 峰时缩短 mm | 局部提交子步 | 所属原区间 |
|---|---:|---:|---:|---|
| 16 | 26961.608 | 1.212699 | 4100 | accepted512→513 |
| 32 | 26757.098 | 1.205875 | 4098 | accepted512→513 |

全部提交点给出的峰差 **0.764323%**、峰缩短差 **0.565902%**，均满足原1%/2%门槛。
这是原点稀疏 argmin 跳过一个采样点的问题：两个更细采样的峰其实在同一个原区间内，只差两个1/8子步。
因此可记录“**825全幅16→32的峰力/峰位按全部提交点达到冻结网格门槛**”；不覆盖原稀点表、不修改阈值，也不把其他未完成项或877失败改成通过。
后续工具应同时报告全部提交点峰值及按共同原点对齐的曲线误差，不能只以稀疏采样的峰值索引作判据。

### 5.6 六目标范围的Fiber敏感性与镜像差异

仅在已经通过同网格和8→16的前六目标域，固定16段与8边界子步，改变8×1→32×3 Fiber。
两杆细Fiber均 **2136/2136** 完成，不重算 legacy 基线、不修改钢材或端部路径：

| 原杆 | 压峰变化 | 有序 NRMSE | 最大纤维应力变化 | 最大纤维应变变化 |
|---|---:|---:|---:|---:|
| 877 | 0.003299% | 0.000632% | 2.1503% | 2.3068% |
| 825 | 0.276877% | 0.016769% | 3.3618% | 3.4576% |

变化以细Fiber结果作分母。端力门通过，但两杆 `fiber_extrema_within_two_percent=false`。
细Fiber最大绝对应力分别194.862/172.596 MPa，仍未到235 MPa；但不能据此省略纤维精度问题。
两个网格的最外侧纤维形心位置不同，极值是在不同采样点上取得；报告同时给出力学响应变化及采样位置因素，而不是将它混为实现错误。

按原塔前六目标比较镜像对，沿各杆自身初始杆轴取轴力（未直接比较未作反射变换的全局向量）：

| 镜像对 | 压峰差 | 有序 NRMSE | 峰缩短差 | 两杆最大杆内挠度 mm |
|---|---:|---:|---:|---:|
| 877/878 | 2.4418% | 0.7234% | 2.0923% | 1.1466 / 0.8855 |
| 825/828 | 0.9630% | 0.3897% | 1.5523% | 4.1724 / 3.3892 |

因此877/878不能当可直接删去的重复案例。825/828虽轴力差更小，局部挠度、纤维应力仍有差异，也没有作完整域镜像等效认证。
这些差异同时包含实际随机缺陷方向和不同塔端部历程，本轮没有把两者贡献进一步分离。

随后独立四段重放878/828，两杆均 **2136/2136** 完成，端力历程误差分别 **3.8429e-10 / 1.1516e-11**，同实现门通过。
这里只做四段匹配，没有做这两根的网格收敛，故该工具汇总的 `mesh_thresholds_passed=false` 是未进行网格比较，不是同四段重放失败。

## 6. 实际命令与结果

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_model_mechanical_parity.py' -v
# 初版8 tests；追加主轴原型后9 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_member_reference_3d.py' -v
# 初版10 tests；追加明确释放/二维包装/紧凑记录后13 tests, OK

.venv/bin/python -m unittest discover -s tests -p 'test_member_reference*.py' -v
# 此轮 T06(15)+T08(6)=21 tests, OK；随后T08又新增3项并通过

.venv/bin/python -m unittest discover -s tests -p 'test_member_state_archive.py' -v
# 3 tests, OK（小分块、嵌套同名键、转义、空数组、截断）

.venv/bin/python -m unittest discover -s tests -p 'test_member_reference_convergence.py' -v
# 最终9 tests, OK；加 T01 9、T06 15、archive 3，共36项实际通过

.venv/bin/python -m unittest discover -s tests -p 'test_member_reference_fallback.py' -v
# 3 tests, OK；本角色累计39项。全仓计数以主agent最后一次discover为准。

.venv/bin/python -m unittest discover -s tests -p 'test_member_reference_extension.py' -v
# 3 tests, OK；源/历史、同实现门、前网格完整性与必要性拒绝；本角色累计42项。

.venv/bin/python -m initial_imperfection_material.audit_mechanics \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v1
# 四根代表杆；elastic_implementation_passed=true

.venv/bin/python -m initial_imperfection_material.member_reference_3d \
  --history initial_imperfection_material/results/followup/execution_20261022/recorder_smoke_v1/segmented_reference/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v2 \
  --members 877 825 --boundary-substeps 10
# 两杆各160/160；same_mesh_replay_tolerance_1e_minus_6_passed=true

.venv/bin/python -m initial_imperfection_material.member_reference_3d \
  --history initial_imperfection_material/results/followup/execution_20261022/recorder_smoke_v1/segmented_reference/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v3 \
  --members 877 825 --boundary-substeps 20
# 两杆各320/320；10/20子步在原记录点处吻合

.venv/bin/python -m initial_imperfection_material.member_reference_convergence \
  --history initial_imperfection_material/results/followup/execution_20261022/recorder_smoke_v1/segmented_reference/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_smoke_v2_comoving \
  --members 877 825 --divisions 4 8 16 --boundary-substeps 1 --remove-rigid-translation
# 全部数值完成；825压峰在此小幅协议内不可评估，未冒充通过

.venv/bin/python -m initial_imperfection_material.member_reference_convergence \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_prefix_6_v1/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v2_sub4 \
  --members 877 825 --divisions 4 8 16 --boundary-substeps 4 --remove-rigid-translation
# 前缀同四段匹配；825三网格完成，877十六段部分完成（不得算通过）
# v1使用1子步；v3_sub8使用8子步，均为独立输出目录。

.venv/bin/python -m initial_imperfection_material.member_reference_convergence \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1/segmented_reference/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_v1_sub8 \
  --members 877 825 --divisions 4 8 16 --boundary-substeps 8 --remove-rigid-translation
# 877同4失败停止；825同4匹配、三网格完整但8→16门未过。
# 877第二组仅改16子步，目录mesh_full_877_v2_sub16；第三组同16子步再显式加
# --algorithm-fallback，目录mesh_full_877_v3_sub16_fallback。结果见5.4。

.venv/bin/python -m initial_imperfection_material.member_reference_extension \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_legacy_v1/segmented_reference/member_states.jsonl \
  --verified-mesh initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_v1_sub8/mesh_study_summary.json \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_825_extension32_v1 \
  --member 825 --divisions 32
# 只追加32段；峰位另扫描既有全部提交子步，无额外求解。

.venv/bin/python -m initial_imperfection_material.member_reference_fiber_sensitivity \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_prefix_6_v1/member_states.jsonl \
  --verified-mesh initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v3_sub8/mesh_study_summary.json \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/fiber_prefix6_v1 \
  --members 877 825 --divisions 16 --long-edge-segments 32 --short-edge-segments 3
# 两杆完整；力响应差很小，但极值应力/应变变化超过2%。

.venv/bin/python -m initial_imperfection_material.member_reference_convergence \
  --history initial_imperfection_material/results/followup/execution_20261022/reference_prefix_6_v1/member_states.jsonl \
  --output initial_imperfection_material/results/followup/execution_20261022/mechanics/mirror_prefix6_v1 \
  --members 878 828 --divisions 4 --boundary-substeps 8 --remove-rigid-translation
# 仅镜像杆同实现重放核对，不将同4通过解释成两杆物理相同。
```

上述输出目录已存在，CLI 会拒绝覆盖；复算应换 `audit_v2` / `replay_smoke_v4` 等新目录。
`replay_smoke_v1` 是失败记录，必须保留，不能用成功输出覆盖。

## 7. 原始产物与图

- [审计 JSON：完整参数、矩阵、误差与坐标](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v1/mechanical_audit.json)
- [审计 CSV](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v1/mechanical_audit.csv)
- [截面/刚度对照图](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v1/mechanical_audit.png)
- [1528 根杆缺陷向量](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v1/imperfection_vectors.json)
- [失败重放汇总，保留停止与部分覆盖](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v1/replay_summary.json)
- [成功小幅重放汇总](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v2/replay_summary.json)
- [真实塔杆与独立试件端力叠合图](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v2/boundary_replay.png)
- [10/20 边界子步敏感性](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/boundary_substep_sensitivity.json)
- [主轴旋转原型完整矩阵](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/audit_v2_principal_axes/mechanical_audit.json)
- [不加子步的准静力共移重放](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/replay_smoke_v4_comoving/replay_summary.json)
- [共移 4/8/16 小幅预验](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_smoke_v2_comoving/mesh_study_summary.json)
- [六目标前缀：1 子步及失败保留](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v1/mesh_study_summary.json)
- [六目标前缀：4 子步网格结果](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v2_sub4/mesh_study_summary.json)
- [六目标前缀：4 子步网格对照图](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v2_sub4/mesh_study.png)
- [六目标前缀：8 子步完整网格结果](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v3_sub8/mesh_study_summary.json)
- [六目标前缀：8 子步完整网格对照图](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_prefix6_v3_sub8/mesh_study.png)
- [六目标前缀：4/8 边界子步敏感性](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/prefix6_boundary_substep_sensitivity.json)
- [完整协议：两杆4/8/16结果及失败门](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_v1_sub8/mesh_study_summary.json)
- [完整协议：877首次误差增长的定位](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/full_877_sub8_error_localization.json)
- [完整协议：877仅加密边界子步的第二组](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_877_v2_sub16/mesh_study_summary.json)
- [完整协议：877第三组数值完成但不等效](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/full_877_third_attempt_comparison.json)
- [完整协议：825仅追加32段](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mesh_full_825_extension32_v1/mesh_extension_summary.json)
- [825全部提交子步的峰值采样诊断](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/full_825_dense_peak_sampling.json)
- [六目标范围：固定16段的Fiber敏感性](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/fiber_prefix6_v1/fiber_study_summary.json)
- [Fiber敏感性对照图](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/fiber_prefix6_v1/fiber_study.png)
- [六目标范围：镜像杆物理响应差异](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/prefix6_mirror_physical_comparison.json)
- [六目标范围：878/828独立同四段重放](../../../initial_imperfection_material/results/followup/execution_20261022/mechanics/mirror_prefix6_v1/mesh_study_summary.json)

成功目录的 `member_877.json` / `member_825.json` 包含每一个提交子步、端力、完整端部位移、基本变形、截面曲率、最大纤维应力应变、输入指纹和原记录点索引。
网格试验采用 gzip 状态文件，没有另建全塔全纤维数据库。

## 8. 仍需完成，不能宣称已验收

1. T07 的完整采集已由主 agent 完成；本角色不将全塔数值完成当作物理建模精度的自动认证。
2. T08：877全幅同网格失败；825全幅原8→16未过，追加16→32按全部提交点峰值达到网格门槛。前六目标Fiber/镜像已完成限定试验，但Fiber极值变化超过2%，镜像不能无条件删减；完整域边界子步/纤维/镜像仍未认证。G1保持未过。
3. T09/T10：真实杆标定与循环留出数据，不能用这次纯弹性/小幅证据替代。
4. T11：有完整边界和收敛证据后选择 A/B/C。当前约 51% 截面弯曲差强烈要求先处理耦合与适用范围，但本轮未擅自最终选路。

因此：T01 可以登记“完成（审计）”；T06 可登记“完成基础接口与小幅边界验证”，完整强非线性验收归 T08，不能把 G1/G2/G3 自动改为通过。

下一批最值得优先研究的是877后期跳转区：复核全塔原步长下的局部路径/分支精度、规定端部插值路径和回退算法影响，再决定局部参考方法；本批没有擅自另跑新全塔或改变材料来消除差异。
