# 初始缺陷等效杆件本构：修订试验报告

## 1. 本轮修订目的

初版证明了七点压缩骨架能够重构单杆的单调轴力—缩短曲线，但审查发现三个必须优先解决的问题：

1. `HystereticSM` 把屈服前可恢复的几何柔化表现成了有记忆的滞回过程；
2. 原四分段标定曲线存在约 4%～5% 的网格误差；
3. 单杆试验与 Z30103A6 全塔模型的弹性模量、强化比、梁单元和积分方法没有统一。

本轮已经逐项修改，并增加实际塔杆筛查、压缩—卸载验收、网格/步长收敛和未收敛保护。当前成果仍定位为“**单杆单调受压与屈服前卸载的等效杆件本构原型**”，还没有宣称可直接替换全塔风振模型。

## 2. 主要代码改动

### 2.1 峰前响应改成可逆非线性弹性

初版用 `HystereticSM` 承载整条拉压不对称骨架。即使 `damage=0、beta=0`，它仍有自身的卸载/再加载规则，不能保证沿峰前几何柔化曲线原路返回。

现在默认载体改为 `ElasticMultiLinear`：

- 压缩支仍来自分段参考曲线或 Perry 试算；
- 拉伸支与参考钢材采用同一 `E、fy、b`；
- 卸载沿同一单值骨架返回，因此屈服前没有人为残余力；
- `HystereticSM` 仅作为 `response_mode="hysteretic"` 的旧模型对照，不再是默认材料。

这个选择解决的是“屈服前恢复”问题。它也意味着峰后卸载目前同样是可逆的，尚未表示真实的屈曲后塑性、刚度退化和循环损伤。因此它适合本轮单调推覆与小循环验收，暂不直接用于脉动风全时程。

### 2.2 标定参考改为收敛后的分段模型

参考模型由固定四段改为可配置分段，默认采用：

```text
16 segments
dispBeamColumn
Corotational transformation
Legendre integration, 6 points
Steel02: E=210 GPa, fy=345 MPa, b=0.03
```

这些参数与当前 `OpenSeesModelWithBuckling` 的核心单元、积分和材料参数保持一致。试件仍为二维弱轴、两端铰接、确定性半正弦初弯曲，因此边界和空间传力尚未等同于塔架。

### 2.3 原塔初弯曲离散同步修正

原塔代码只在 `num==2` 的分点加偏移，改变分段数会同时改变缺陷位置，二分段甚至没有缺陷。现在每根杆先生成一个固定的横向缺陷方向，所有内部节点按

```text
w(x) = e0 sin(πx/L)
```

分配偏移。因此 `member_divisions=2、4、8、16` 都保持同一个跨中峰值和同一缺陷方向，分段数只控制离散精度。

### 2.4 收敛状态和共同区间评价

每次分析现在记录：

- 请求步数和完成步数；
- 是否到达目标位移；
- 请求终点和实际终点；
- 计算时间。

参考模型未完成全部步数时默认直接报错，不再继续生成“完整曲线误差”。候选曲线和参考曲线的 NRMSE、单调外功只在二者共同覆盖的位移区间计算，禁止把参考曲线终点力常值外推。

## 3. 试件与统一参数

演示试件仍使用 `Source/Z30103A6.s2k` 中的 `L125x8Q345`：

| 参数 | 修订值 | 说明 |
|---|---:|---|
| 杆长 | 3.000 m | 保留用于方法演示 |
| 面积 | 0.001936 m² | S2K |
| 弱轴惯性矩 | 1.193943×10⁻⁶ m⁴ | `I22-abs(I23)` |
| 弹性模量 | 210 GPa | 与 S2K、全塔模型统一 |
| 屈服强度 | 345 MPa | Q345 |
| Steel02 强化比 | 0.03 | 与全塔构造器默认值统一 |
| 初弯曲 | `L/1000` | 半正弦 |
| 有效长度系数 | 1.0 | 单杆两端铰接假定 |
| 长细比 | 120.80 | 演示杆 |
| Euler 荷载 | 274.95 kN | 计算值 |
| 截面屈服荷载 | 667.92 kN | 计算值 |

纤维离散后的面积误差为 0，弱轴惯性矩误差为 `-0.166%`。

## 4. 屈服前压缩—卸载验收

加载路径为：

```text
εeq: 0 → -0.0005 → 0
```

即 3 m 杆先压缩 1.5 mm，再恢复原端距。采用十六段参考模型、默认可逆等效材料和旧 `HystereticSM` 载体同时计算。

| 模型 | 最大压缩轴力 | 回到原端距后的轴力 |
|---|---:|---:|
| 16 段 Steel02 参考 | 193.11 kN | 0.00019 N |
| 可逆等效材料 | 190.82 kN | 0 N |
| 旧 HystereticSM 载体 | 190.82 kN | +9.49 kN |

参考模型全过程最大纤维应力为 **169.93 MPa**，低于 345 MPa，确认属于钢材弹性范围。验收容限取 `0.001Afy=0.668 kN`，参考模型和新材料均通过。

![屈服前压缩卸载](results/pre_yield_unloading.png)

这个结果说明初版审查指出的残余力问题已经被消除。旧载体曲线保留在图中，作为材料形式选择确实会影响风振卸载路径的直接证据。

## 5. 网格和步长收敛

### 5.1 分段收敛

保持半正弦初弯曲、材料、纤维和 400 个位移步不变：

| 分段数 | 完成步数 | 峰值承载力 | 相对 16 段 |
|---:|---:|---:|---:|
| 4 | 400/400 | 254.90 kN | +4.55% |
| 8 | 400/400 | 246.02 kN | +0.91% |
| 16 | 400/400 | 243.81 kN | 0 |

四段结果不再作为标定基准。八段与十六段峰值差小于 1%，默认使用十六段。

### 5.2 步长收敛

十六段模型从 400 步增加到 800 步，峰值均为 **243.806 kN**，本算例记录到的峰值缩短均为 **2.475 mm**。默认主试验采用 800 步。

![收敛检查](results/convergence_study.png)

## 6. 修订后的单调推覆结果

| 模型 | 峰值 | 峰值误差 | NRMSE | 单调外功误差 |
|---|---:|---:|---:|---:|
| 16 段参考 | 243.81 kN | — | — | — |
| 标定型可逆等效材料 | 243.81 kN | 0.00% | 2.10% | 4.46% |
| Perry 可逆试算材料 | 238.78 kN | -2.06% | 28.42% | 70.78% |
| 无缺陷 Steel02 corotTruss | 1013.79 kN（终点） | +315.82% | 307.71% | 831.84% |

“峰值零误差”仍然只代表骨架取点规则包含参考峰值，不是独立预测能力。`2.10%` 的 NRMSE 和 `4.46%` 的单调外功误差表示七点骨架对这条已知曲线的重构精度。

![单杆推覆曲线](results/pushover_comparison.png)

Perry 支路仍只把首次纤维屈服作为峰值；3% 压应变和 25% 残余强度仍是试算假设。报告和 JSON 已将 3% 明确称为“骨架标定边界”，不是失效应变。超过该边界时默认保持近似恒定的末端残余应力（为避免零切线导致求解奇异，保留 `10⁻⁶` 量级的数值切线），不再含糊地把它解释为构件断裂。

## 7. 实际 Z30103A6 杆件筛查与验证

从 S2K 的 `CONNECTIVITY - FRAME` 和 `FRAME SECTION ASSIGNMENTS` 直接抽取 `L125x8Q345`：

- 数量：112 根；
- 长度：1.440～2.414 m；
- 中位长度：1.602 m；
- 在 `K=1` 假定下，弱轴长细比：57.97～97.19。

这确认 3 m 演示杆不代表塔中该截面的实际长度范围。本轮进一步取最短、中位和最长三种实际长度，分别用十六段参考曲线重新标定：

| 代表杆 | 长度 | 长细比 | 参考峰值 | NRMSE | 单调外功误差 |
|---|---:|---:|---:|---:|---:|
| 最短 | 1.440 m | 57.97 | 569.80 kN | 2.36% | 4.64% |
| 中位 | 1.602 m | 64.52 | 540.09 kN | 2.34% | 4.78% |
| 最长 | 2.414 m | 97.19 | 351.30 kN | 2.00% | 4.46% |

三组分析均到达目标位移。它们证明“按每根物理杆或参数分组离线生成骨架”的方法能覆盖该截面的实际长度范围，但仍属于同数据标定后的重构检查。Q235、Q420 角钢和不同有效长度系数尚未完成验证。

![实际杆长验证](results/actual_member_validation.png)

逐根筛查数据见 `results/actual_l125x8_members.csv`，三种代表杆的验证表见 `results/actual_member_validation.csv`。

## 8. 当前可以和不可以做什么

当前原型已经可以：

- 重构一根已标定角钢杆的单调 `N-Δ` 曲线；
- 在未屈服的小幅压缩—卸载路径中恢复零力；
- 按原始物理杆的 `L、K、A、I、fy、b` 独立生成材料；
- 用 `corotTruss` 保留塔架层面的整体大位移几何非线性；
- 对未收敛和评价区间不一致给出显式状态或拒绝评价；
- 对实际 L125x8 杆长进行分组标定和误差统计。

当前还不能：

- 描述屈曲后的不可恢复变形、循环退化和真实滞回耗能；
- 输出被等效掉的杆内弯矩、侧移形态和屈曲方向；
- 自动表示单角钢连接偏心、弯扭/局部屈曲和节点滑移；
- 直接沿用原纤维应变阈值作为等效杆损伤判据；
- 由单根铰接杆证明空间塔段的弯曲传力和失效顺序等效；
- 将同一杆再施加几何初弯曲，或拆段后按每段短长度重复生成材料。

## 9. 接回课题主线的建议

下一阶段不宜直接替换全塔。建议按以下顺序：

1. 对塔中主要 Q235、Q345、Q420 截面各选短、中、长杆，形成独立的单杆误差矩阵；
2. 为参考分段模型增加屈服后卸载—再加载和拉压往复路径；
3. 根据参考回线决定是否需要“峰前非线性弹性 + 峰后损伤塑性”的混合材料；库存材料无法清晰实现时，再开发原生 C++ `UniaxialMaterial`；
4. 选择一个包含主材和斜材的小塔段，比较弹性刚度、模态、推覆、首根失稳杆和失效顺序；
5. 小塔段通过后，再把材料缓存和构件级损伤指标接入全塔风时程及易损性分析。

本课题中最稳妥的表述仍是：**面向输电塔批量非线性分析的构件级等效建模方法**。创新点不必放在发明复杂本构，而应放在参考模型—等效骨架—误差验收—塔段验证这条完整证据链。

## 10. 复现与输出

默认完整试验：

```bash
uv run python -m initial_imperfection_material.run_experiment
```

快速调试时可以跳过附加收敛和实际杆验证：

```bash
uv run python -m initial_imperfection_material.run_experiment \
  --steps 100 \
  --reference-divisions 8 \
  --skip-convergence \
  --skip-actual-validation \
  --output /tmp/imperfection-check
```

主要输出：

- `summary.json`：参数、收敛状态、误差和卸载验收；
- `pushover_curves.csv`：全部单调曲线；
- `pre_yield_unloading.csv`：压缩—卸载全过程；
- `convergence_study.csv`：分段和步长收敛；
- `actual_l125x8_members.csv`：112 根实际构件筛查；
- `actual_member_validation.csv`：短、中、长代表杆验证；
- `material_backbones.csv`：材料骨架点。

## 11. 参考资料

1. GB 50017—2017《钢结构设计标准》，第 7.2 节和附录 D：[标准文本](https://www.steelbuildingtech.com/cdn/https/www.steelbuildingtech.com/Content/upload/pdf/2020739979/GB-50017-2017-Standard-for-design-of-steel-structures.pdf)。
2. Simões da Silva, L.; Simões, R., *Design of Steel Structures*：[JRC Eurocode 3 报告](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC96658/jrc_steel_report_2015_07_22.pdf)。
3. OpenSees `ElasticMultiLinear Material`：[官方文档](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/ElasticMultiLinear.html)。
4. OpenSees `HystereticSM Material`：[官方文档](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/HystereticSM.html)。
5. OpenSees `Corotational Truss Element`：[官方文档](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/CorotationalTruss.html)。
6. Scott, M. H.; Fenves, G. L., *How to Introduce a New Material into OpenSees*：[PEER/OpenSees PDF](https://opensees.berkeley.edu/OpenSees/NewMaterial.pdf)。
7. Abdelrahman et al., *An effective stress-strain model for angles under axial compression*, Structures 20 (2019) 298–308：[DOI](https://doi.org/10.1016/j.istruc.2019.04.013)。
