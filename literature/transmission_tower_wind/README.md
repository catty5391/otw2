# 输电塔抗风与 OpenSees 文献包

整理日期：2026-10-19。

本目录优先保存出版社、学校或会议官网公开提供的 PDF。无法公开下载全文的文献只列 DOI/摘要页，不保存来源不明的转载文件。

## 本地全文

| 编号 | 文献 | 主要内容 | 与本项目的关系 |
|---|---|---|---|
| 01 | 唐珏，2013，同济大学硕士论文，《基于性能的输电塔—线体系风灾易损性分析》 | 四线三塔、脉动风模拟、增量动力分析、蒙特卡洛、易损性曲线与曲面 | 最适合用来观察一篇完整硕士论文的章节组织和成果规模 |
| 02 | Zhu et al., 2023, *Fragility Analysis of Transmission Towers Subjected to Downburst Winds* | 3 类塔、下击暴流、风向角与径向位置、LHS、不确定模型、非线性屈曲与易损性 | 参考风向、随机参数和损伤概率的设计 |
| 03 | Du & Hajjar, 2022, *Nonlinear dynamic analysis and fragility development of electrical transmission towers under hurricanes* | OpenSees 角钢纤维梁单元、屈曲、非线性时程、IDA、飓风倒塌易损性 | 与当前 Fiber + Corotational + 初始缺陷路线最接近 |
| 04 | Du & Hajjar, *Methodology for collapse fragility development for hurricane events: electrical transmission towers* | 全时长风暴记录、风记录缩放、IDA 曲线拟合、倒塌易损性 | 参考“风荷载 IDA”如何形成严谨的方法链 |
| 05 | 宋鹏艳等，2023，《基于整体易损性的猫头型输电塔抗倒塌能力分析》 | OpenSees、3 种塔高、20 条地震记录、4 种倒塌判据、IDA 易损性 | 虽是抗震，但很适合参考 OpenSees 输电塔论文的结果组织方式 |
| 06 | Darestani et al., 2019, ICASP13 conference paper | OpenSees 非线性推覆，比较屈曲、屈服、节点滑移和连接破坏等建模复杂度 | 可用于确定当前模型简化假设和验证章节 |

PDF 均保存在 [`papers`](papers/) 目录。

导线质量的取值、单位换算和在 OpenSees 中的节点质量分配说明见
[`conductor_mass_parameters.md`](conductor_mass_parameters.md)。

## 建议重点跟踪但未保存全文的文献

1. Wang, Li, Fu et al. (2022), *Wind fragility assessment and sensitivity analysis for a transmission tower-line system*. DOI: [10.1016/j.jweia.2022.105233](https://doi.org/10.1016/j.jweia.2022.105233)。几何初始缺陷、塔线体系不确定性和敏感性分析。
2. Ma, Khazaali & Bocchini (2021), *Component-based fragility analysis of transmission towers subjected to hurricane wind load*. DOI: [10.1016/j.engstruct.2021.112586](https://doi.org/10.1016/j.engstruct.2021.112586)。OpenSees 精细/简化模型、构件失效和渐进倒塌。
3. Darestani, Shafieezadeh & Cha (2020), *Effect of modelling complexities on extreme wind hazard performance of steel lattice transmission towers*. DOI: [10.1080/15732479.2019.1673783](https://doi.org/10.1080/15732479.2019.1673783)。OpenSees 推覆、屈曲后行为和节点滑移。
4. Zhu & Ou (2025), *Wind fragility modeling of transmission tower-line system based on threat-dependent structural robustness index*. DOI: [10.1016/j.strusafe.2024.102571](https://doi.org/10.1016/j.strusafe.2024.102571)。纤维应力识别失效杆件、删单元、剩余承载力和鲁棒性损伤指标。
5. Zekavati et al. (2025), *A proposed approach for failure analysis of lattice transmission towers considering geometric imperfection effects*. DOI: [10.1016/j.engfailanal.2024.109068](https://doi.org/10.1016/j.engfailanal.2024.109068)。OpenSees 初始弯曲、偏心、节点滑移及足尺试验验证。
6. Asgarian et al. (2017), *Determining critical areas of transmission towers due to sudden removal of members*. DOI: [10.1016/j.csefa.2015.09.005](https://doi.org/10.1016/j.csefa.2015.09.005)。OpenSees 渐进倒塌和薄弱区域识别，全文开放但出版社下载接口当前返回 403。

## 可比较的国内硕士论文

- 项楚原，清华大学，2021，《沿海地区典型输电线路台风下力学性能研究》：[学校摘要页](https://newetds.lib.tsinghua.edu.cn/qh/paper/summary?dbCode=ETDQH&sysId=268734)。数值仿真、不同风速/风向/档距、1:25 风洞试验。
- 胡礼颖，武汉理工大学，2024，《考虑随机与模糊不确定性的输电塔线体系抗风可靠度研究》：[题录与摘要](https://cnki.istiz.org.cn/kcms/detail/detail.aspx?dbcode=CMFD&dbname=CMFD2026&filename=1025837966.nh)。单塔/挂点力简化/塔线模型比较、失效模式、可靠度和加固。
- 吴宇，四川农业大学，2025，《非平稳非高斯风场下输电塔结构风致易损性分析》：[题录与摘要](https://cnki.istiz.org.cn/kcms/detail/detail.aspx?dbcode=CMFD&dbname=CMFD2026&filename=1025901479.nh)。把主要工作集中在风场建模及其对易损性的影响。

## 推荐阅读顺序

1. 先看 01 的目录、第三章和第四章，建立硕士论文工作量尺度。
2. 看 06 和 03，核对 OpenSees 角钢杆件、屈曲和初始缺陷模型。
3. 看 02，学习参数工况、随机样本和易损性图表怎么组织。
4. 看 04，决定是否需要做完整的风荷载 IDA；它更接近论文加强版，不是保底毕业的必选项。
5. 看 05，把“极限状态、潜在失效杆件、易损性曲线、倒塌裕度”的表达移植到抗风研究。

