# 新材料、输电塔风荷载与风雨荷载文献

检索日期：2026-11-02。按当前项目语境，“新材料”指杆件等效本构、非线性滞回与屈曲模型，不是新钢种。优先查期刊/出版社、作者仓库、大学及政府资料；这里是针对项目的筛选，不是穷尽所有文献的系统综述。

共 **25 条**文献：新材料/构件与单元 **8** 条、输电塔风荷载 **7** 条、风雨荷载 **10** 条。本地PDF **12 份**，其中本轮新下载 **4 份**、复用已有论文 **8 份**；其余保留核实的DOI或期刊入口。技术报告、会议论文和期刊论文分别标注，不把下载失败或仅见摘要写成已获全文。

## 建议先读的顺序

1. **M02 + M03（刘俊才，2023英文/2022中文）**：先明确单角钢曲线本构的适用边界；已有你提供的全文，最贴近现在希望改进的材料路线。
2. **M01（Liu–Tian–Ma–Qu，2022）**：核对现有分段TMQ和GA识别的依据。GA拟合的是给定模型参数，不能自动消除模型形式/试验边界差异。
3. **W01 + M07（Du与Hajjar，2024/2021）**：OpenSees风致非线性、角钢耦合单元、IDA与易损性，且有作者公开算例。
4. **W04（Vu等，2025）**：直接对应当前不同风攻角的静风推覆，阅读塔身分层与导线荷载的处理。
5. **W06（Meng等，2026）**：作者含Xian-Chao Luo，弱节间—推覆等能量—IDA—刚度调整，适合连接现有薄弱位置成果。
6. **R10 → R01 → R02 → R03**：先用可下载的会议短文理解雨荷载，再追溯塔体、导线与雨滴速度模型。
7. **R06 → R07**：从风速/雨强易损性面走向含气象联合分布的失效概率；这应在荷载与结构响应可信之后做。

A=本项目优先，B=补充对照，C=扩展方向。优先级是与当前任务的匹配度，不是期刊质量排名。

## 新材料、杆件试验与OpenSees单元

|编号/优先级|文献（原题与入口）|期刊/会议与年份|本地全文|
|---|---|---|---|
|M01 / A|[Development of a hysteretic model for steel members under cyclic axial loading](https://www.sciencedirect.com/science/article/pii/S2352710221016569)|Journal of Building Engineering，2022|未取得；见原文入口|
|M02 / A|[Phenomenological hysteretic model for fixed-end steel equal-leg angle: Development and application](https://www.sciencedirect.com/science/article/abs/pii/S0263823122008874)|Thin-Walled Structures，2023|[PDF](materials/M02_2023.pdf)|
|M03 / A|[考虑失稳效应的角钢非线性滞回模型研究](https://jvs.sjtu.edu.cn/EN/Y2022/V41/I23/19)|振动与冲击，2022|[PDF](materials/M03_2022.pdf)|
|M04 / A|[Cyclic Behavior of Single Angles for Ductile End Cross Frames](https://ej.aisc.org/index.php/engj/article/view/875)|Engineering Journal，2006|[PDF](materials/M04_2006.pdf)|
|M05 / A|[Toward Earthquake-Resistant Design of Concentrically Braced Steel-Frame Structures](https://peer.berkeley.edu/publications/2008-08)|PEER Report 2008/08，2008|[PDF](materials/M05_2008.pdf)|
|M06 / A|[An adaptive nonlinear simulation method for member buckling in lattice towers](https://www.sciencedirect.com/science/article/abs/pii/S0143974X23006223)|Journal of Constructional Steel Research，2024|未取得；见原文入口|
|M07 / A|[Three-dimensional nonlinear displacement-based beam element for members with angle and tee sections](https://www.sciencedirect.com/science/article/pii/S0141029621003898)|Engineering Structures，2021|未取得；见原文入口|
|M08 / C|[A Uni-Axial Damage Model for Axial Steel Braces in Large-Span Structures Under Cyclic Loading Protocol](https://onlinelibrary.wiley.com/doi/10.1002/tal.70143)|The Structural Design of Tall and Special Buildings，2026|未取得；见原文入口|

**M01｜钢构件循环轴向加载滞回模型开发**

作者：Juncai Liu；Li Tian；Ruisheng Ma；Bing Qu。 DOI：[10.1016/j.jobe.2021.103798](https://doi.org/10.1016/j.jobe.2021.103798)。
**用于本项目：**现有TMQ分段本构及遗传算法识别的直接依据，核对每个经验参数对应的受力阶段。
**适用边界：**分段直线是原模型形式；管材或其他截面的拟合参数不能直接证明本塔角钢适用。

**M02｜固定端等边角钢的现象学滞回模型**

作者：Juncai Liu；Li Tian；Ruisheng Ma；Xiangrui Meng。 DOI：[10.1016/j.tws.2022.110335](https://doi.org/10.1016/j.tws.2022.110335)。
**用于本项目：**单角钢曲线型本构的首选；从试验、参数分析到曲线模型及塔结构应用形成完整链条。
**适用边界：**固定端边界、钢号和长细比范围需与本塔杆件逐一匹配。

**M03｜考虑失稳效应的角钢非线性滞回模型研究**

作者：刘俊才；田利；毕文哲；刘文棚；孟祥瑞。 DOI：[10.13465/j.cnki.jvs.2022.23.003](https://doi.org/10.13465/j.cnki.jvs.2022.23.003)。
**用于本项目：**中文公式、角钢试验和参数拟合说明，可交叉核对英文曲线本构。
**适用边界：**中文与英文版本不能未经逐式核对就混用参数。

**M04｜单角钢循环行为试验**

作者：Lyle P. Carden；Francisco Garcia-Alvarez；Ahmad M. Itani；Ian G. Buckle。 DOI：[10.62913/engj.v43i2.875](https://doi.org/10.62913/engj.v43i2.875)。
**用于本项目：**真实单角钢回线及试验边界，可用于现有Carden拟合的符号、标距和卸载路径核查。
**适用边界：**桥梁端横隔连接与塔杆连接不同；无序扫描点不能直接成为时程。

**M05｜中心支撑钢框架抗震设计与杆件数值建模**

作者：Patxi Uriz；Stephen A. Mahin。 此条未编造DOI。
**用于本项目：**Steel02纤维梁、初弯曲及循环屈曲参考；支撑现有四分段基准与网格核查。
**适用边界：**这是PEER技术报告，不是输电塔风荷载论文；不能据其示例宣称四段普遍收敛。

**M06｜格构塔杆件屈曲自适应非线性模拟**

作者：Yu Zhu；Hong-Nan Li；Xing Fu；Ding-Hao Yu。 DOI：[10.1016/j.jcsr.2023.108395](https://doi.org/10.1016/j.jcsr.2023.108395)。
**用于本项目：**轴向与转动弹簧组合、按需引入自由度、隐式显式顺序求解；适合比较等效模型与收敛处理路线。
**适用边界：**不是现成TMQ参数表或OpenSees材料插件；摘要不能替代算法实现。

**M07｜角钢和T形截面三维非线性位移型梁单元**

作者：Xinlong Du；Jerome Hajjar。 DOI：[10.1016/j.engstruct.2021.112239](https://doi.org/10.1016/j.engstruct.2021.112239)。
**用于本项目：**OpenSees非对称截面轴弯扭耦合，对照当前普通梁与TMQ解耦弯扭假设。
**适用边界：**单元开发不是构件等效本构标定；仍需验证材料和离散参数。

**M08｜循环轴向钢支撑的单轴损伤模型**

作者：Xiaofei Ma；Zhan Lu；Jianlong Sun；Liangming Tang；Yongtao Bai。 DOI：[10.1002/tal.70143](https://doi.org/10.1002/tal.70143)。
**用于本项目：**2026年补充路线：集中损伤力学与杆中塑性铰处理屈曲退化。
**适用边界：**目前仅核对官方摘要；不是本塔角钢已验证的新材料，全文参数仍待取得。

## 输电塔风荷载、推覆与易损性

|编号/优先级|文献（原题与入口）|期刊/会议与年份|本地全文|
|---|---|---|---|
|W01 / A|[Methodology for collapse fragility development for hurricane events: Electrical transmission towers](https://www.sciencedirect.com/science/article/am/pii/S0143974X24005558)|Journal of Constructional Steel Research，2024|[PDF](wind/W01_2024_preprint.pdf)（作者预印本）|
|W02 / B|[Nonlinear dynamic analysis and fragility development of electrical transmission towers under hurricanes](https://files.ssrcweb.org/proceedings/2022/Du_et_al_SSRC_2022.pdf)|Proceedings of the Annual Stability Conference, Structural Stability Research Council，2022|[PDF](wind/W02_2022.pdf)|
|W03 / B|[Evaluation of the Ultimate Collapse Load of a High-Voltage Transmission Tower under Excessive Wind Loads](https://www.mdpi.com/2075-5309/13/2/513)|Buildings，2023|[PDF](wind/W03_2023.pdf)|
|W04 / A|[Nonlinear Pushover Analysis of Retrofitted Transmission Towers Under Static Wind Loads](https://www.mdpi.com/2075-5309/15/5/654)|Buildings，2025|[PDF](wind/W04_2025.pdf)|
|W05 / B|[Progressive collapse analysis of a truss transmission tower-line system subjected to downburst loading](https://doi.org/10.1016/j.jcsr.2021.107044)|Journal of Constructional Steel Research，2022|[PDF](wind/W05_2022.pdf)|
|W06 / A|[Ductility-Based Stiffness Optimization of Transmission Tower–Line Systems for Wind-Induced Collapse Resistance](https://www.mdpi.com/2227-9717/14/20/3250)|Processes，2026|[PDF](wind/W06_2026.pdf)|
|W07 / B|[Wind-induced failure analysis of a transmission tower-line system with long-term measured data and orientation effect](https://www.sciencedirect.com/science/article/pii/S0951832022004926)|Reliability Engineering & System Safety，2023|未取得；见原文入口|

**W01｜飓风事件下输电塔倒塌易损性方法**

作者：Xinlong Du；Jerome F. Hajjar。 DOI：[10.1016/j.jcsr.2024.109005](https://doi.org/10.1016/j.jcsr.2024.109005)。
**用于本项目：**全时长风速/风向记录、IDA与易损性；作者公开OpenSees算例，最适合搭建可复现风振主线。
**适用边界：**不是只用静力推覆末点拟合倒塌；下载版本为作者预印本时需与期刊版区分。

**W02｜飓风下输电塔非线性动力分析与易损性**

作者：Xinlong Du；Jerome F. Hajjar。 此条未编造DOI。
**用于本项目：**W01方法前身，公开全文便于查看角钢单元与风致IDA的实现思路。
**适用边界：**SSRC会议论文，与2024期刊文有研究延续关系，不视为两项独立试验验证。

**W03｜超强风下高压输电塔极限倒塌荷载**

作者：Giacomo Vettoretto；Zongchen Li；Christian Affolter。 DOI：[10.3390/buildings13020513](https://doi.org/10.3390/buildings13020513)。
**用于本项目：**屈曲模态缺陷、几何材料非线性与不同风向，可对照当前初缺陷和容量曲线。
**适用边界：**使用Abaqus；模态缺陷与每杆半正弦初弯曲不是同一种定义。

**W04｜静风下加固输电塔非线性推覆分析**

作者：Quang-Viet Vu；Hyeok-Ju Lee；Jae-Min Kim。 DOI：[10.3390/buildings15050654](https://doi.org/10.3390/buildings15050654)。
**用于本项目：**对照静风推覆、风攻角、塔身分层荷载和导线荷载；最贴近当前三材料四风角推覆。
**适用边界：**论文采用IEC 60826:2017的相关方法；需核对本项目适用标准与角度定义，不直接照搬系数。

**W05｜下击暴流作用下桁架塔线体系连续倒塌**

作者：Hua-Dong Zheng；Jian Fan。 DOI：[10.1016/j.jcsr.2021.107044](https://doi.org/10.1016/j.jcsr.2021.107044)。
**用于本项目：**耦合塔线、杆件受压屈曲与受拉断裂、下击暴流移动路径；已有本地全文。
**适用边界：**原文为MATLAB显式中心差分及开发支撑单元，不应描述为直接OpenSees复现。

**W06｜基于延性的塔线体系抗风倒塌刚度优化**

作者：Ling-Xing Meng；Yun-Jie Liu；Jin-Peng Meng；Xian-Chao Luo；Shao-Yuan Zhang；Li Tian。 DOI：[10.3390/pr14203250](https://doi.org/10.3390/pr14203250)。
**用于本项目：**作者包含Xian-Chao Luo（罗贤超），弱节间识别、推覆等能量法、IDA与刚度调整，紧接现有薄弱位置研究。
**适用边界：**大型钢管塔ABAQUS算例；其延性目标和提升比例不能迁移成本塔损伤阈值。

**W07｜考虑长期实测与线路朝向的塔线风致失效**

作者：Wenzhe Bi；Li Tian；Chao Li；Zhen Ma；Haiyang Pan。 DOI：[10.1016/j.ress.2022.108875](https://doi.org/10.1016/j.ress.2022.108875)。
**用于本项目：**风速—风向联合分布及线路朝向；区分特定风角响应与实际失效概率。
**适用边界：**0°/90°含义和线路朝向需映射；原文钢管塔与本塔角钢不同。

## 风雨荷载、塔线动力响应与联合风险

|编号/优先级|文献（原题与入口）|期刊/会议与年份|本地全文|
|---|---|---|---|
|R01 / A|[Wind-rain-induced vibration test and analytical method of high-voltage transmission tower](https://www.techno-press.com/papers/15154)|Structural Engineering and Mechanics，2013|未取得；见原文入口|
|R02 / A|[Dynamic analysis of transmission tower-line system subjected to wind and rain loads](https://www.sciencedirect.com/science/article/pii/S0167610515302427)|Journal of Wind Engineering and Industrial Aerodynamics，2016|未取得；见原文入口|
|R03 / A|[Velocity Ratio of Wind-Driven Rain and Its Application on a Transmission Tower Subjected to Wind and Rain Loads](https://ascelibrary.org/doi/10.1061/%28ASCE%29CF.1943-5509.0001210)|Journal of Performance of Constructed Facilities，2018|未取得；见原文入口|
|R04 / B|[Fragility analysis and estimation of collapse status for transmission tower subjected to wind and rain loads](https://www.sciencedirect.com/science/article/abs/pii/S0167473015000624)|Structural Safety，2016|未取得；见原文入口|
|R05 / B|[Failure analysis of a transmission tower subjected to combined wind and rainfall excitations](https://onlinelibrary.wiley.com/doi/10.1002/tal.1615)|The Structural Design of Tall and Special Buildings，2019|未取得；见原文入口|
|R06 / A|[Fragility analysis of a transmission tower under combined wind and rain loads](https://www.sciencedirect.com/science/article/pii/S0167610520300088)|Journal of Wind Engineering and Industrial Aerodynamics，2020|未取得；见原文入口|
|R07 / A|[Failure analysis of a transmission line considering the joint probability distribution of wind speed and rain intensity](https://www.sciencedirect.com/science/article/abs/pii/S0141029621000638)|Engineering Structures，2021|未取得；见原文入口|
|R08 / B|[不同类风场雨滴冲击荷载对输变电塔线体系动力响应的影响研究](https://pubs.cstam.org.cn/article/doi/10.11776/j.issn.1000-4939.2024.02.014)|应用力学学报，2024|未取得；见原文入口|
|R09 / C|[Predicting the Dynamic Response of Transmission Tower–Line Systems Under Wind–Rain Loads](https://www.mdpi.com/2079-9292/14/3/558)|Electronics，2025|[PDF](wind_rain/R09_2025.pdf)|
|R10 / A|[Rain load for transmission tower-line system](https://objectext.auckland.ac.nz/figshare/9808657/Fu_Rainloadfortransmissiontowerlinesystem.pdf)|9th Asia-Pacific Conference on Wind Engineering, Auckland, New Zealand, 3–7 December 2017，2017|[PDF](wind_rain/R10_2017.pdf)|

**R01｜高压输电塔风雨振动试验及分析方法**

作者：Hong-Nan Li；Shun-Yong Tang；Ting-Hua Yi。 DOI：[10.12989/sem.2013.48.4.435](https://doi.org/10.12989/sem.2013.48.4.435)。
**用于本项目：**风雨荷载建模的基础：雨滴冲击、塔体荷载与风雨试验验证。
**适用边界：**应先核对雨滴尺度、速度、受雨面积及单位，不能简单按固定比例放大风荷载。

**R02｜风雨荷载下输电塔线体系动力分析**

作者：Xing Fu；Hong-Nan Li。 DOI：[10.1016/j.jweia.2016.08.010](https://doi.org/10.1016/j.jweia.2016.08.010)。
**用于本项目：**导线风雨荷载、阻力系数及塔线耦合响应，是从单塔雨荷载扩展至塔线的关键文献。
**适用边界：**研究导线由梯形股线构成，阻力系数及雨效应比例不能无条件用于本项目导线。

**R03｜风驱雨速度比及其在输电塔中的应用**

作者：Li Tian；Yu-Jie Zeng；Xing Fu。 DOI：[10.1061/(ASCE)CF.1943-5509.0001210](https://doi.org/10.1061/(ASCE)CF.1943-5509.0001210)。
**用于本项目：**雨滴水平速度和风速的关系、雨速时程与雨荷载公式，补齐雨荷载关键输入。
**适用边界：**不能默认雨滴水平速度始终等于当地风速；需核对公式适用风场与粒径。

**R04｜风雨下输电塔易损性与倒塌状态估计**

作者：Xing Fu；Hong-Nan Li；Gang Li。 DOI：[10.1016/j.strusafe.2015.08.002](https://doi.org/10.1016/j.strusafe.2015.08.002)。
**用于本项目：**早期风雨易损性与临界倒塌曲线，可与2020二维易损性面方法比较。
**适用边界：**卷期年2016，DOI含2015；不能把自己的数值不收敛点直接作为文中倒塌状态。

**R05｜风雨联合作用下输电塔失效分析**

作者：Xing Fu；Hong‐Nan Li；Jia Wang。 DOI：[10.1002/tal.1615](https://doi.org/10.1002/tal.1615)。
**用于本项目：**风雨荷载、不确定性及承载力/破坏模式识别，连接荷载建模与结构失效。
**适用边界：**目前只核对官方题录摘要，随机变量分布和失效条件须取得全文后使用。

**R06｜风雨联合作用下输电塔易损性分析**

作者：Xing Fu；Hong-Nan Li；Gang Li；Zhi-Qian Dong。 DOI：[10.1016/j.jweia.2020.104098](https://doi.org/10.1016/j.jweia.2020.104098)。
**用于本项目：**以风速和雨强构造易损性面，含结构不确定性、风角与临界倒塌面。
**适用边界：**优先作为后续易损性主线；原文最不利90°仅属于其算例，不是所有塔的规律。

**R07｜考虑风速与雨强联合概率的输电线路失效分析**

作者：Xing Fu；Hong-Nan Li；Gang Li；Zhi-Qian Dong；Mi Zhao。 DOI：[10.1016/j.engstruct.2021.111913](https://doi.org/10.1016/j.engstruct.2021.111913)。
**用于本项目：**风速雨强联合分布、雨强时间分辨率及危险性加权，避免独立叠加最大风和最大雨。
**适用边界：**需要站点气象数据及时间尺度统一；易损性条件概率不等于年失效概率。

**R08｜不同类风场雨滴冲击荷载对输变电塔线体系动力响应的影响研究**

作者：王辉；戴根；张鑫。 DOI：[10.11776/j.issn.1000-4939.2024.02.014](https://doi.org/10.11776/j.issn.1000-4939.2024.02.014)。
**用于本项目：**中文直接相关研究：良态风雨与湿下击暴流，比较塔顶位移、加速度谱和关键主材应力。
**适用边界：**目前只有期刊题录摘要；降雨增幅是其算例结果，不能作为统一荷载增大系数。

**R09｜风雨下输电塔线体系动力响应预测**

作者：Bo Yang；Yifan Luo；Yingna Li；Lulu Wang；Jiawen Zhang。 DOI：[10.3390/electronics14030558](https://doi.org/10.3390/electronics14030558)。
**用于本项目：**公开全文的风雨荷载和方向分解案例，可检查模型输入输出；扩展阅读TimesNet代理模型。
**适用边界：**论文主贡献是预测算法，荷载基础应回溯R01/R02/R03；当前不必引入深度学习。

**R10｜输电塔线体系的雨荷载**

作者：Xing Fu；Hong-Nan Li。 此条未编造DOI。
**用于本项目：**奥克兰大学公开会议全文，介绍塔与导线雨荷载方法及风雨试验；适合先通读建立荷载计算思路。
**适用边界：**会议综述与同一研究团队期刊文献相互关联，不计作独立重复验证；具体系数需回溯期刊原文。

## 代码与公式配套入口

- [TransTowerFragility作者仓库](https://github.com/xinlong-du/TransTowerFragility)：W01对应的OpenSees样例；本轮核对README，未运行它的算例。仓库说明了定制OpenSees与官方非对称截面单元路线，不能直接把仓库程序当作本项目已验证实现。
- [OpenSees dispBeamColumnAsym文档](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/elements/dispBeamColumnAsym.html)：M07配套。文档要求主轴坐标下纤维和剪心，且明确不考虑翘曲；不能只替换单元名字就跳过截面/剪心核对。
- [NSF公开的M07全文入口](https://par.nsf.gov/servlets/purl/10303457)：已检索到，但本环境下载超时；不计入已保存PDF。

## 与当前研究衔接时应提取什么

|现有工作|优先文献|需要提取的内容|
|---|---|---|
|TMQ/曲线本构开发|M01–M04、M06|试件A/L/E/fy、有效长度/边界、位移标距、首压峰、下降支、反转点、卸载与再加载、循环退化；标清实测/拟合/假设来源。|
|四分段Steel01/Steel02对照|M05、M07、W03|缺陷形状与幅值、截面方向、轴弯扭耦合、网格与积分点；不把一篇文章的分段数当作普遍收敛证明。|
|单塔/塔线及风攻角|W01、W04、W07|0°基准、线路朝向、风速高度/平均时长、荷载分区、导线法向投影、空间相关性和阻尼。|
|雨荷载模块|R10、R01–R03|雨强单位与时间间隔、雨滴粒径分布、水平/竖向速度、撞击传力、迎雨面积与湿态导线阻力系数；区分不同机制，避免重复计入。|
|推覆后续损伤分级/易损性|W01、W06、R04、R06、R07|变形观测点、屈服/失稳/损伤判据、不确定性和风雨联合取值；原论文阈值先核对物理定义再讨论迁移。|

上述是对本项目的阅读建议。当前已保存推覆曲线的停止点是数值截断，论文中的损伤/倒塌阈值不能未经校核直接套用。多风角的最大响应也不等于气象意义的最危险朝向；风险需要另计发生概率。

## 阅读与获取状态

本轮主要核对题录、作者、年份、摘要/可见方法说明，并检查本地PDF身份与可解析性。没有声称25篇均逐式精读。每篇的read_scope、来源、下载状态与哈希见catalog.json。英文文章的卷期年可能晚于DOI中的年份，例如M02标2023、W05标2022、W07标2023、R04标2016。
已补正中文M03的DOI与第四作者（刘文棚），依据现有用户PDF首页；旧2026-10-26报告的“未取得全文/待核实”是当时状态。M02/M03现有PDF来自用户提供，未宣称本轮从网络新下载。
部分Crossref请求遭遇限流，或中文DOI未被该数据库收录；这些条目以出版社/期刊或PDF首页核对，未把Crossref查询失败当成DOI无效。受限PDF保留入口，未绕过付费或访问限制。

## 文件

- `materials/`、`wind/`、`wind_rain/`：已实际取得的PDF，前缀对应文献编号。
- [catalog.csv](catalog.csv)：可用Excel打开的UTF-8 BOM表，含用途、限制与访问状态。
- [references.bib](references.bib)：25条UTF-8 BibTeX书目，可导入文献管理器；不补造未核实页码。
- [catalog.json](catalog.json)：完整结构化清单与获取记录。
- [metadata.json](metadata.json)：Crossref题录查询记录；缺项以清单中的原始来源补齐。
- [initial_selection.json](initial_selection.json)：最初24条候选的检索记录；补充R10后的最终25条以catalog.json为准。
- [supplement_retrieval.json](supplement_retrieval.json)：补充下载的获取记录。
- [verification.json](verification.json)：数量、PDF解析与哈希检查结果。

本轮仅整理文献与阅读说明，未修改分析代码、加载参数或材料系数。
