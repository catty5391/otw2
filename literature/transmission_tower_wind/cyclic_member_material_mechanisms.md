# 循环杆件等效材料：机制比较与来源核查

记录日期：2026-10-22。用途是 T10 协议准备，不是材料选型结论，也不是新的物理验证。

## 本轮核查范围

| 来源 | 本轮实际阅读范围 | 可以支持的判断与限制 |
|---|---|---|
| OpenSees `ElasticMultiLinear.cpp` 官方源码 | 应力插值、提交与恢复相关实现 | `eta=0` 时沿当前应变对应的分段线性骨架返回，不提供塑性记忆；不能据此证明整个分析器的回滚行为 |
| OpenSees Steel02 官方文档 | 材料参数及说明 | 平滑钢材滞回、运动／可选各向同性强化；不能把名义 `fy` 标记直接当作严格弹塑性分界 |
| OpenSees HystereticSM 官方文档 | 模型说明、骨架及卸载／损伤参数部分 | 多折线滞回载体具有自身的卸载规则，零损伤参数不等于可逆几何非线性 |
| OpenSees ReinforcingSteel 官方文档 | 材料适用对象及 GA／DM 屈曲、疲劳参数说明 | 原对象为钢筋纤维，不能无验证地迁移参数到角钢整杆 |
| Uriz 与 Mahin，PEER 2008/08 | 封面、摘要、目录片段及第4章 4.2–4.3 的相关片段，印刷页71–75／PDF页95–99 | 分布纤维非线性与几何非线性结合的循环支撑模型；未通读401页全文，未阅读完整疲劳推导 |
| 已有 ICASP2019 论文 | 本轮前约3页，含第2.1节 | 分段纤维梁、几何非线性和初弯曲的输电塔应用；文中的分段数不是本塔网格收敛证明 |
| 已有 Du 与 Hajjar SSRC2022 论文 | 本轮前约4页 | 单角钢质心／剪心不重合和扭弯耦合值得注意；文中的改进单元能力不能归给普通梁单元 |

官方源码和在线文档为访问时版本；本轮没有对当前安装的 OpenSees 二进制逐项做功能探测。

## 机制比较

| 方案 | 峰前恢复／塑性记忆 | 屈曲、换向与外功 | 需要识别的证据 | 本课题中的定位 |
|---|---|---|---|---|
| `ElasticMultiLinear`，`eta=0` | 沿同一骨架返回；无塑性残余记忆 | 可表示给定单调下降支；不能提供真实的循环退化或塑性回线 | 可靠单调骨架、独立小循环的恢复误差 | 可逆基线，不因推覆拟合好就宣布循环通过 |
| `HystereticSM` | 由自身卸载／再加载规则控制；存在记忆 | 支持拉压不对称、多折线与退化；几何弹性恢复未自动保证 | 卸载斜率、零力截距、嵌套循环、残余量、共轭功 | 保留为反例／候选，不继续以调 damage 代替机制验收 |
| `Steel02`＋分段空间纤维梁＋几何非线性 | 钢材层面平滑滞回和强化；几何效应由构件承担 | 能研究轴弯耦合与构件屈曲；依赖网格、纤维和边界 | 完整纤维状态、三维端部历程、网格／步长／截面精度 | 参考路线仍须通过 G1；不自动涵盖角钢局部板屈曲或翘曲 |
| `ReinforcingSteel` 的 GA／DM 屈曲选项 | 与钢筋滞回框架关联 | 钢筋屈曲、可选疲劳机制，不是通用角钢杆端等效关系 | 原适用范围、长细比定义、循环参数及角钢独立试验 | 仅机制参考，不作为现成替代或参数来源 |
| 待开发构件级材料 | 应区分可恢复几何柔化与不可恢复状态 | 是否需要屈曲记忆／退化由 C0–C6 证据决定 | 训练识别、独立协议及边界留出验证 | 本轮未开发；若不能保持局部响应，应讨论混合保留梁模型 |

这里“可恢复”不能只靠最大应力小于 `fy` 推断。C0 使用纯 Elastic 钢材检查几何恢复；C1 使用远离名义强度的小幅 Steel02 循环并实际测量残余。`max|σ|/fy=1` 仅命名为观测标记。单调积分和未闭合循环外功不能自动称为耗能。

PEER 报告的分段梁模型要求同时考虑轴力与弯矩，并讨论网格对局部应变的影响。其截面假设不等于已包含局部板屈曲／截面畸变。因此，不能把“文献用两个单元”转化为当前四段参考天然收敛的理由。

## 官方及原始来源

1. [ElasticMultiLinear 官方实现](https://raw.githubusercontent.com/OpenSees/OpenSees/master/SRC/material/uniaxial/ElasticMultiLinear.cpp)。使用时应进一步记录本地二进制对应版本，不能把 `master` 当成本地固定提交。
2. [Steel02 官方说明](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html)。
3. [HystereticSM 官方说明](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/HystereticSM.html)。
4. [ReinforcingSteel 官方说明](https://opensees.berkeley.edu/OpenSees/manuals/usermanual/2447.htm)。
5. Uriz, P., & Mahin, S. A. (2008). *Toward Earthquake-Resistant Design of Concentrically Braced Steel-Frame Structures*. PEER Report 2008/08。[大学研究中心发布页](https://peer.berkeley.edu/publications/2008-08)；[官方公开 PDF](https://peer.berkeley.edu/sites/default/files/web_peer808_uriz_patxi_uriz_stephen_a._mahin.pdf)。

本轮新增下载仅上述 PEER 报告，来自作者机构公开地址，无需绕过付费或登录：

- 本地文件：[07_Uriz_Mahin_PEER_2008_08_cyclic_braces.pdf](papers/07_Uriz_Mahin_PEER_2008_08_cyclic_braces.pdf)。
- 文件大小：18,212,814 bytes；PDF 共401页。
- SHA256：`0e183d161f42d370ea64b8c85e5d7e21c736df43dc492855edd0472f98b24ed1`。
- 阅读状态：**部分章节已读，全文未读**。本轮未采用未读章节的疲劳公式或经验参数。

已有本地文献分别是 [ICASP2019](papers/06_OpenSees_model_complexity_extreme_wind_ICASP2019.pdf)（实际题名 *Wind Reliability of Transmission Line Models using Kriging-Based Methods*）与 [SSRC2022](papers/03_OpenSees_hurricane_collapse_fragility_SSRC2022.pdf)。引用范围仅限本轮实际核查部分，原有文件未修改。

## 对当前试验设计的直接影响

1. 保留纯 Elastic 的 C0；不给 Steel02 的名义首次 `fy` 事件附加“此前严格弹性”的结论。
2. C1 两级压缩幅值由参考纤维应力状态选取，不用等效轴向应变阈值替代纤维判据。
3. C2–C4 必须比较卸载、残余与换向，不只比较包络峰值。
4. C5 使用从未加载、经重力预加载的两端6DOF历史；既有诊断路径与未来独立留出分开。
5. G1 未通过时冻结协议设计但不生成实际幅值、不拟合新材料、不声称 T10 完成。
