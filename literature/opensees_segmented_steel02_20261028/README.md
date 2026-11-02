# OpenSees 分段初弯曲与 Steel02：文献核对

检索与复核日期：2026-10-28。数值试验另见 `initial_imperfection_material/steel02_tmq_comparison/`。

## 最直接的输电塔依据

**Jeddi, Shafieezadeh, Hur, Ha, Hahm & Kim (2022)**，*Multi-hazard typhoon and earthquake collapse fragility models for transmission towers: An active learning reliability approach using gradient boosting classifiers*，EESD 51(15):3552–3573。[出版社全文](https://onlinelibrary.wiley.com/doi/full/10.1002/eqe.3735)。

已在线读到§2.1.1–2.1.2。采用 **Steel01、纤维截面、forceBeamColumn、5积分点、Corotational**。杆件分为四个单元，按Euler屈曲形状给中间节点施加弱轴平面初弯曲，跨中幅值在0.0005L–0.001L之间取值。四段选择追溯到Darestani对所研究塔中两个代表截面的检查。**这支持方法来源，不证明任意角钢四段均已收敛，也不能把文中的材料改称Steel02。** 本地直接下载全文HTML返回403，已读到的出版社网页与本地PDF要区别记录。

**Darestani, Shafieezadeh & Cha (2020；2019在线发表)**，*Effect of modelling complexities on extreme wind hazard performance of steel lattice transmission towers*，Structure and Infrastructure Engineering 16(6):898–915。[DOI/出版社](https://www.tandfonline.com/doi/full/10.1080/15732479.2019.1673783)。检索到原论文出版信息，全文未取得；本轮涉及其四段结论的具体叙述来自上述Jeddi论文明确转引，不冒称直接复核原始数据。

**Jeddi等2020 KNS会议论文**，*Fragility Assessment of Overhead Transmission Towers under Typhoon and Earthquake Multi-Hazard Events*。[学会原始PDF](https://www.kns.org/files/pre_paper/44/20A-443-%EA%B9%80%EB%AF%BC%EA%B7%9C.pdf)。本地 `jeddi_2020_kns.pdf`。PDF第1页§2.1提到四段及0.05%–0.1%杆长缺陷，第4页参考文献[7]指向Darestani。该短文简写“中间节点”，缺陷分布细节以2022全文为准，不能据此断言只动唯一中点。

## 直接包含 Steel02 代码的原始研究

**Uriz & Mahin (2008)**，*Toward Earthquake-Resistant Design of Concentrically Braced Steel-Frame Structures*，PEER Report 2008/08。[Berkeley原始PDF](https://peer.berkeley.edu/sites/default/files/web_peer808_uriz_patxi_uriz_stephen_a._mahin.pdf)。本地 `uriz_mahin_2008_peer.pdf`，并保存可检索文本。

- 印刷页77–79：对杆件单元数2/4/10/30、积分点2/3/5/7及纤维离散进行参数分析；采用二次函数初弯曲。这里不是本项目采用的半正弦形状。
- 印刷页81，图4.11：给出 **Steel02 + fiberSec + Corotational + nonlinearBeamColumn** 的Tcl例子。示例含端部节点板与刚性段，不能把总单元数当作净杆段的分段数。
- 印刷页82–83，§4.4.2：比较单调和循环响应，指出总力响应接近时曲率分布仍可能不同；其特定模型中4个以上子单元、每个7积分点得到接近的结果。
- 本报告主要验证支撑/管截面，并非本塔角钢的直接实验验证。示例材料的强化与各向同性参数不自动移用于Q345角钢。

关联期刊论文：Uriz, Filippou & Mahin (2008)，*Model for Cyclic Inelastic Buckling of Steel Braces*，JSE134(4):619–628，[DOI](https://doi.org/10.1061/(ASCE)0733-9445(2008)134:4(619))。本轮方法细节以已取得的PEER报告原文为依据。

## 往复与疲劳研究补充

**Salawdeh & Goggins (2013)**，*Numerical simulation for steel brace members incorporating a fatigue model*，Engineering Structures46:332–349。[作者所在大学成果页](https://research.universityofgalway.ie/en/publications/numerical-simulation-for-steel-brace-members-incorporating-a-fati-3/)，[出版社](https://www.sciencedirect.com/science/article/pii/S0141029612004105)。作者机构摘要可核对其纤维梁、轴向往复试验及低周疲劳模型。本轮作者托管PDF下载失败，**未据此引用未读到的参数表或分段数**；本项目也未添加未经验证的疲劳断裂参数。

## Steel02 实现参数依据

[OpenSees官方文档](https://opensees.github.io/OpenSeesDocumentation/user/manual/material/uniaxialMaterials/Steel02.html)，本地 `steel02_official.html`。Steel02为Giuffre–Menegotto–Pinto钢材模型，R0、cR1、cR2控制屈服过渡；官方推荐R0在10–20、cR1=0.925、cR2=0.15。可选a1/a3默认0，a2/a4默认1。

本轮取R0=20、cR1=0.925、cR2=0.15；E=210GPa、fy=345MPa、b=0.03沿用项目参数。**b是现有假定，不是材料试验标定值。** 杆件压屈来自分段几何、弯曲与纤维塑性，不能只给直线truss赋Steel02就认为已经包含初弯曲。

## 文件与使用

下载状态、原始URL、字节数及SHA256见 `download_manifest.json`。两份PDF及派生文本留在本地供阅读；本轮未执行git提交或上传数据。检索到的文献没有替代本项目自身的网格、步长和物理验证。

## 2026-10-29：当前全塔四分段初始缺陷是否合理

后续实施更新：以下保留修改前的审计。随后已将裸构造器默认改为L/1000、固定旧幅值扫描的seed，并完成三根实际杆件的63个空间单杆工况；详见[实现、步骤与结果](../../initial_imperfection_material/segmented_member_validation/README.md)。原文中L/100默认值和单杆参数差异指审计时的代码与旧二维模块，新空间试验已与全塔完整材料参数统一。

结论：**目前“半正弦初弯曲＋L/1000＋Steel02空间分段梁”有研究依据，可以保留为基线；四段只是离散选择，尚不能称为本塔经过验证的精确模型。** 当前优先问题是缺陷方向、单杆与全塔参数一致性，以及长度和截面两个层面的离散精度。本次为联网文献复核、代码与既有输出审计，没有重新进行非线性有限元计算。

### 已运行模型与代码默认值必须分开

| 检查项 | 当前实际情况 | 判断 |
|---|---|---|
| 形状 | `model/tower_model_with_buckling.py` 的 `_get_breakpoint_coord` 使用 `sin(pi*s/L)`；每根杆共用一个横向向量 | 已解决旧版仅中间节点偏移及加密改变缺陷位置的问题 |
| 最近单塔与塔线风荷载对比 | 显式指定四段、`random_disp_ratio=.001`、`imperfection_seed=30103` | 实际为 L/1000，不是 L/100 |
| 裸构造器默认值 | `random_disp_ratio=.01`，seed 未指定 | L/100 是近期算例幅值的十倍；不能不加说明地作为本塔一般制造缺陷使用 |
| 初弯曲方向 | 在杆轴正交平面内均匀随机抽取方向 | 尚未与角钢截面弱主轴绑定；固定 seed 只能保证复现 |
| 杆件模型 | 三维 `dispBeamColumn`、默认6点Legendre、Corotational、Steel02纤维截面；原节点转角共享 | 与二维两端铰接弱轴单杆不等价 |

沿原始杆轴坐标 s，当前缺陷函数为 `r(s)=r0(s)+e0*n*sin(pi*s/L)`，其中 n 是垂直杆轴的单位方向。四段五个节点的偏移幅值依次为 `0, 0.7071e0, e0, 0.7071e0, 0`；半正弦是指定的初弯曲形状，不表示所有空间塔杆在真实节点约束下都具有该屈曲模态。

独立审计最近单塔与塔线0°输出，各1528根物理杆、4584个内部节点，均满足上述L/1000半正弦定义；幅值比最大数值偏差约4.73e-15，轴向偏移残量不超过3.40e-15 m。349号杆长1.602379 m，三个分点横向偏移约1.133、1.602、1.133 mm。检查输入：

- `initial_imperfection_material/tian_ma_qu/followup_results/single_tower_wind_comparison_20261028/runs/steel02_four_segments_0/model_data/`
- `initial_imperfection_material/tian_ma_qu/followup_results/tower_line_wind_comparison_20261028/segmented_reference_deg_0/model_data/`

近期入口为 `single_tower_wind_comparison.py:112` 和 `tower_line_wind_comparison.py:208`。旧 `pushover/pushover_main_with_buckling.py` 扫描0至L/100且未固定seed；比较幅值效应时，随机方向也变化，会混合两种影响。已有结果应保留其原始参数，后续入口宜要求显式幅值和seed。

### 文献具体支持到什么程度

1. **Jeddi等（2022）§2.1.1–2.1.2**直接支持四分段、Euler形状缺陷、L/2000至L/1000以及使杆件绕弱轴弯曲的方向。该文用Steel01、forceBeamColumn和5积分点，四段依据来自其引用的Darestani代表截面检查。因此可借鉴几何建模方法，不能宣称本项目是原文全部复现。[出版社全文](https://onlinelibrary.wiley.com/doi/10.1002/eqe.3735)
2. **Uriz与Mahin（2008）**提供Steel02纤维梁和初弯曲的直接OpenSees实现及分段研究，原报告采用二次形状；其示例与本塔的截面、边界和材料参数不同。其幅值敏感性试验也包含较大初弯曲，不能据此将某个幅值宣布为普遍正确或错误。[PEER原始报告](https://peer.berkeley.edu/sites/default/files/web_peer808_uriz_patxi_uriz_stephen_a._mahin.pdf)
3. **Vettoretto、Li与Affolter（2023）**，*Evaluation of the Ultimate Collapse Load of a High-Voltage Transmission Tower under Excessive Wind Loads*，Buildings13(2):513。§3.2通过角钢与连接模型比较，显示方向、幅值和连接条件会影响承载力，缺陷较小也不保证容量较高；该文采用Abaqus，不是OpenSees复现。文中使用的规范等效缺陷、实测弯曲和模态缺陷不能混为同一物理量。本项目L/1000应表述为文献参考假定，而非实测值或已完成规范校核。[原文](https://www.mdpi.com/2075-5309/13/2/513)
4. **Du与Hajjar（2022）**，*Nonlinear dynamic analysis and fragility development of electrical transmission towers under hurricanes*，SSRC年度会议。§3.1使用每杆3个单元、Steel01并施加纤维残余应力；其单元是针对非对称截面弯扭响应开发的位移型/混合型单元。这说明“分几段”需要连同单元能力判断，不能将其三段直接移用于当前标准dispBeamColumn。[学会原始PDF](https://cloud.aisc.org/SSRC/2022/Du_et_al_SSRC_2022.pdf)

新增两篇PDF及可检索文本保存在 `supplement_20261029/`，原始链接、大小、SHA256和下载状态见其中 `download_manifest.json`。此前Darestani全文未取得的限制不变。

### 本项目已有数值证据

下表读取2026-10-28独立单杆试验 `initial_imperfection_material/steel02_tmq_comparison/results/mesh_summary.csv`，不是本轮新计算、不是实测承载力。两杆均为L125×8Q345、二维弱轴、两端铰接、L/1000半正弦、同一截面离散和位移协议。

| 试件 | 4段峰值/kN | 8段峰值/kN | 16段峰值/kN | 32段峰值/kN | 4段相对32段 |
|---|---:|---:|---:|---:|---:|
| 实塔349号杆，1.602 m | 555.409 | 546.885 | 545.666 | 545.319 | +1.850% |
| 3 m演示杆 | 254.906 | 246.020 | 243.806 | 243.254 | +4.790% |

32段仅为此处数值比较基准。16段相对32段峰值偏差分别为0.064%、0.227%；这些结果不能代表全塔四段误差，也没有证明全塔失效顺序收敛。

相同16段模型中，幅值取L/2000、L/1000、L/500时，1.602 m杆的峰值分别为580.624、545.666、494.452 kN；3 m杆分别为257.098、243.806、223.638 kN。幅值影响不可忽略，L/500仅为敏感性工况，不是已认定的实际缺陷值。数据来自同目录 `summary.json` 的 `imperfection_l2000`、`monotonic_steel02_16`、`imperfection_l500` 算例。

另有两处不能忽略的模型差异：

- 全塔Steel02：`a1=a3=.0005, a2=a4=.01`；独立单杆：`a1=a3=0, a2=a4=1`。尽管E、fy、b等已匹配，循环强化参数并未完全统一；本次没有计算该差异的影响。
- 全塔默认截面为17个纤维（角部1个、两肢各8个），独立单杆约174个。由保存的L125×8纤维坐标计算，全塔弱主惯性矩约1.1719263e-6 m^4，相对S2K的1.1939431e-6低1.844%；独立单杆约低0.166%。应分别检查长度分段和截面离散，不能直接将这两个误差与承载力误差相加。

### 建议保留与补齐的内容

- 保留半正弦及L/1000作为明确标注的研究基线，幅值以原始物理杆长定义；没有实测依据时不称为真实缺陷。
- 先统一单杆和全塔的Steel02完整参数、截面离散及方向定义，再抽取实际关键压杆进行4/8/16段检查；必要时以32段进一步比较。
- 在截面朝向可核对的前提下，增加绕弱主轴弯曲的正、反方向工况，与当前固定随机样本比较。随机方向可以用于不确定性研究，但单一seed不是最不利情况或可靠概率分布的证明。
- 以L/2000、L/1000、L/500做幅值敏感性；比较时保持同一方向样本和其他参数，避免幅值与方向混淆。
- 对代表性塔段/全塔检查初始刚度、峰值、峰后曲线、首失稳杆及失效顺序。半正弦分段梁主要表示构件整体弯曲屈曲，角钢局部屈曲、翘曲/弯扭、连接偏心与滑移仍需另行验证，不能靠加密长度网格自动补齐。
