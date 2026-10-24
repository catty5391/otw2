# T10 前置：循环协议、证据绑定与独立留出

日期：2026-10-22。执行角色：第3角色后续任务。**本轮完成软件前置和预冻结试验设计；T10 的参考循环计算、参数识别和物理验证均未完成。** 未启动任何有限元任务，未改动已冻结的 quality、sample admission 或 fragility 入口。

## 1. 步骤与产物

1. 阅读 `PLAN.md` 的 T10 与第7节 C0–C6 矩阵，落实 T08/G1、T09 的前置条件。
2. 只读现有 `fine_sparse/member_metadata.json`，确认实际 `L40x3Q235` 的0.85 m及1.95 m两组；源 SHA256 为 `f274ce6b1fa4f51d6891cd537caa4950257a4bea874757bc47fbac83dc22fbbb`。
3. 将试验设计与未来参考计算结果拆成两个文件：前者预冻结，后者保持空待绑定；禁止填入假设的材料等效应变幅值。
4. 实现设计、数据来源、幅值依据和训练／留出泄漏检查，不导入 OpenSees。
5. 运行16项轻量单元测试及两项 CLI 验证，不运行公共回归或重 FE。
6. 核查已有文献及官方实现；只新增一份机构公开 PEER 报告，注明部分阅读范围。

新增代码与数据：

- [cyclic_protocol_contract.py](../../../initial_imperfection_material/cyclic_protocol_contract.py)：设计验证、证据绑定和只读 CLI。
- [t10_pre_frozen_v1.json](../../../initial_imperfection_material/protocols/t10_pre_frozen_v1.json)：机器可读设计包。
- [t10_reference_bindings_template.json](../../../initial_imperfection_material/protocols/t10_reference_bindings_template.json)：未解锁的参考绑定模板。
- [test_cyclic_protocol_contract.py](../../../tests/test_cyclic_protocol_contract.py)：16项快速测试，全部使用明确的合成契约数据，不是 FE 结果。
- [机制比较与来源](../../../literature/transmission_tower_wind/cyclic_member_material_mechanisms.md)：已读范围、机制限制、合法下载来源。

设计包规范化 JSON 指纹：`cef191cf7111125dcfd2ec461c8bbc206a3050089ac068bae24d724b5d647e7a`。这是 `fingerprint()` 对排序、紧凑 JSON 的哈希，不是带缩进文件字节哈希。修改设计需新版本并重新绑定，不得保留旧指纹冒充同一设计。

## 2. 首批矩阵与划分

| 实际组 | 主要诊断／训练杆 | 独立未来路径预留杆 | 其他实际杆 |
|---|---:|---:|---|
| L40x3Q235，0.85 m | 877 | 878 | 无 |
| L40x3Q235，1.95 m | 825 | 828 | 917、920暂不纳入首批拟合 |

每组8个用例，共16个：training 8、diagnostic 4、holdout 4。

| 用例 | 钢材／边界 | 划分 | 幅值及用途 |
|---|---|---|---|
| C0 | Elastic／三维铰接 | diagnostic | 纯几何可恢复检查；正反小幅，参考最大纤维应力比上限0.10 |
| C1 | Steel02／三维铰接 | training | 远离名义强度的低、高两级，各3次；纤维应力比上限分别0.25、0.50 |
| C2 | Steel02／三维铰接 | training | 参考峰值附近的嵌套卸载／再加载 |
| C3 | Steel02／三维铰接 | training | 已观测峰后的卸载／再加载；无峰值证据不得构造峰后点 |
| C4 | Steel02／三维铰接 | training | 压缩—拉伸反向；拉伸幅值也须有参考依据 |
| C5 seen | Steel02／塔端6DOF | diagnostic | 已见全塔历程；即使之后计算更精细，也不能改名独立留出 |
| C5 future | Steel02／塔端6DOF | holdout | 必须是未来独立路径，包含初始、重力和成功提交的两端6DOF |
| C6 | Steel02／三维铰接 | holdout | 高低幅顺序及次数与 C1 不同，用固定参数验证，不按该路径重新标定 |

0.10／0.25／0.50 是本轮预冻结的**选点裕度**，不是规范屈服定义，也不自动保证 Steel02 无残余。C1 的实际恢复和回线仍待测量。所有数值位移均未生成；参考需覆盖完整声明截面与纤维，并报告是否出现首个已提交 `max|σ|/fy >= 1` 事件。该事件只称“名义 fy 跨越”，不等同于唯一塑性起点。

两种边界为 `pinned_3d` 与 `tower_6dof_replay`。后者不参与拟合，保留为非训练边界类；已见诊断与未来独立响应使用不同 source ID。C6 共享参考幅值锚点，但响应必须独立，不能复制训练曲线。Q345／Q420及更多截面仍是后续实际样本筛选事项，未虚构杆号和通过结果。

## 3. 接口与保守约束

`validate_package(package)` 只验证设计，始终返回 `resolved_cases=0`、`physical_validation_passed=false`。

`resolve_case(package, case_id, bindings)` 需要：

- 绑定 schema 为 `otw2.cyclic_reference_bindings.v1`，且精确匹配设计指纹。
- G1 `passed`、T09 `completed`，两者均有注册 source 与 SHA256 的证据 ID。
- 轴向参考真实完成并获得网格／纤维精度认可，组、边界、钢材模型与用例一致；控制量必须为以压缩为正的 `end_shortening_m`。
- 使用已提交、有限、位于参考有效域内的锚点；小循环有实际纤维裕度依据，峰后点有实际峰值证据。禁止从试算状态、NaN 或越域外推生成幅值。
- 6DOF 历史必须含未加载初态、重力、两端完整6DOF、有效成员身份及来源哈希；holdout 还必须声明未来独立路径且未参与拟合。
- 使用记录不得将 holdout 用于拟合或模型选择；相同响应哈希不能以不同 ID 跨越 training／diagnostic 与 holdout。

即使成功解析，也只返回 `recipe_ready=true`，同时保留 `analysis_executed=false`、`physical_validation_passed=false` 与 `preyield_reversibility=to_measure_not_assumed`。

当前证据检查验证的是**声明字段与哈希格式／一致性**，不会自动读取所有源文件核验字节，也不能识别未如实登记的拟合使用行为。后续执行者必须结合 G0 来源账本核对真实文件、提交、边界转换和单位，并记录完整 usage。单元测试中的虚拟证据哈希不能作为工程参考。

## 4. 实际测试命令与结果

仓库根执行：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_cyclic_protocol_contract.py' -v
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract
.venv/bin/python -m initial_imperfection_material.cyclic_protocol_contract \
  --case q235_l40_0850_c1_train \
  --bindings initial_imperfection_material/protocols/t10_reference_bindings_template.json
```

实际结果：

- 最终快速测试：**16/16通过，0.026 s，退出码0**。首次运行有1项异常文案正则不匹配，实际正确抛出了纤维裕度异常；修正测试匹配字符串后复跑全部通过，未放松物理守卫。
- 设计 CLI：退出码0，16用例，4 diagnostic／8 training／4 holdout，0个已解析幅值，物理验证为 false。
- 待绑定模板 CLI：**预期退出码2**，`G1 is not passed; do not invent amplitudes`。此拒绝是正确行为，不是不收敛。

覆盖：设计及真实组号、C0纯Elastic、C1实际纤维裕度及3循环、原始等效应变拒绝、名义fy事件声明、峰后依据、有限／已提交／域内控制、边界一致性、留出拟合与选型泄漏、同哈希换名泄漏、已见诊断不可改名、证据注册、完整6DOF及重力、完整纤维覆盖、布尔完成状态和设计变更失效。

## 5. 目前仍未解锁

主线最新结论是 G1 **完整幅值未通过**：877完整路径第三组虽完成，但同四段重放的比较误差约2.15%，超过当前门槛。因此不能把已完成求解当作参考精度认可，模板继续锁定。本轮没有更改 TASKS.json，也没有把 T10 或 T22 标为完成。

[FULL_REFERENCE.md](FULL_REFERENCE.md) 提供新的已知诊断事件：877／878在第7目标首次跨名义应力 fy，源循环步354／357；825／828在第8目标跨越，498／502；917／920未跨越。前六目标未跨该标记不等于严格可逆。上述数据用于设计诊断观察窗口，**不是独立留出、不是已经收敛的幅值标定依据**。

仍缺：

1. 适用于目标完整路径的 G1 网格／纤维精度证据，或主线明确且可证明的局部有效域；不能由本模块自行放宽门槛。
2. T09 的实际杆纤维状态、首次事件及可接受控制域归档。
3. 对每种边界和钢材模型生成真实锚点；当前模板 `references`、`histories` 均为空。
4. 未来独立两端6DOF路径及 C6 响应；既有四段路径不准换名填入。
5. C0–C6 的真实 FE 循环、恢复误差、卸载刚度、残余量、共轭功和全状态比较。
6. 训练拟合、冻结参数、一次性留出检验、路线选择及更多实际等级／截面外推检查。

## 6. 后续 AI 的可执行入口

1. 先读 G1 最新报告和本报告第5节。G1 未通过时止于协议检查，不生成“示例实际幅值”。
2. 通过 G1/T09 后，复制模板到新的实验目录作为绑定输入，保留原模板；按真实证据填写 gates、evidence、references／histories、usage。不得修改 frozen design 来迎合已看过的留出结果。
3. 先运行上述默认 CLI 验证包，再使用新绑定文件执行 `--case ... --bindings ...`；成功只代表协议可解释，尚未运行分析。
4. 由后续执行器消费解析得到的 `targets_m` 或两端6DOF历史。当前模块**不是 FE 执行器**，不得宣传为一条命令完成 T10。
5. 先做 C0/C1 并检查可恢复性；训练 C2–C4 后冻结模型与参数，登记拟合使用记录，再运行 C5 future/C6。失败按原门槛报告，不能回头调参后继续沿用原“独立留出”标签。
6. 在新的结果目录保存每个用例来源、求解状态、物理验证状态、有效域和未达项；本轮只读旧结果，未覆盖任何旧证据。

本轮文件到此冻结，不再启动重 FE 或新增研究分支。
