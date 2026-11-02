# 文献与数据来源清单

检索日期：2026-10-26。`已读`仅代表本轮真实可见范围；没有把摘要阅读写成全文复现。公开 PDF 留本地，结论和溯源记录可以随项目版本管理。

| ID | 书目信息与入口 | 已读范围/状态 | 参数用途及限制 |
|---|---|---|---|
| JBE2022 | Liu J., Tian L., Ma R., Qu B. *Development of a hysteretic model for steel members under cyclic axial loading*. JBE46:103798. [DOI](https://doi.org/10.1016/j.jobe.2021.103798)，[出版社](https://www.sciencedirect.com/science/article/pii/S2352710221016569) | 官方摘要、章节片段；另公开原文转录覆盖第 2–5 节、表 1/2；未获出版社 PDF | 直接 GA 文献。九参数。精确表值使用预览证据，需原版复核；无已确认单等边角钢参数 |
| BLACK1980 | Black R.G., Wenger W.A., Popov E.P. *Inelastic Buckling of Steel Struts under Cyclic Load Reversals*. UCB/EERC-80/40. [NIST/NEHRP PDF](https://nehrpsearch.nist.gov/static/files/NSF/PB81154312.pdf) | 已有合法原 PDF；本轮重点表 1/2（PDF59/61）、附录 A 的管件材性图、附录 B 的图 B19/B20；另核对试件说明 | 原始试验特征证据强；扫描图不是有序CSV。原始单位 ft/in/kip/ksi；Kℓ/r为有效长细比 |
| ANGLE2022CN | 刘俊才、田利、毕文哲、刘文鹏/刘文棚、孟祥瑞.《考虑失稳效应的角钢非线性滞回模型研究》. 振动与冲击2022,41(23):19–26. [官方英文页面](https://jvs.sjtu.edu.cn/EN/Y2022/V41/I23/19) | 官方摘要与参考文献可核实；网页列3602KB PDF，但普通下载端点返回502/不可达；未取得全文。中英文网页对第四作者汉字存在差异，待原PDF核实；DOI未核实 | 单等边角钢实验与拟合是直接线索；不能从摘要声称使用GA、给出系数或认定与现有实现同式 |
| ANGLE2023 | Liu J., Tian L., Ma R., Meng X. *Phenomenological hysteretic model for fixed-end steel equal-leg angle: Development and application*. TWS183:110335. [DOI](https://doi.org/10.1016/j.tws.2022.110335)，[出版社](https://www.sciencedirect.com/science/article/abs/pii/S0263823122008874)，[作者主页](https://faculty.sdu.edu.cn/tianli/zh_CN/lwcg/13686/content/409020.htm) | 官方摘要/章节片段；2022-12在线，2023-02卷期。公开平台截至本轮无全文；OpenAlex返回closed且无仓储全文位置 | 当前最值得补齐的单角钢来源。12件试验、Q235/Q355、5截面、λ50–140；不据摘要提取未知系数 |
| ANGLE2014 | 张春涛、范文亮、李正良.《腐蚀环境中Q345等边角钢构件拟静力试验研究》. 工程力学2014,31(11):53–62. [DOI](https://doi.org/10.6052/j.issn.1000-4750.2013.05.0505)，[官方PDF](https://pubs.cstam.org.cn/data/article/em/preview/pdf/2014-11-53.pdf) | 官方PDF已下载；重点第55–59页，图3/4/8/9，表3/4/5 | 单角钢无腐蚀L1组有可核查特征；E单位是10^5 N/mm²，换算212.2GPa。长度与完整边界未明，压极值未证明是首次压屈；不是现成TMQ参数 |
| CARDEN2006 | Carden L.P., Garcia-Alvarez F., Itani A.M., Buckle I.G. *Cyclic Behavior of Single Angles for Ductile End Cross Frames*. Engineering Journal2006,43(2):111–126. [DOI](https://doi.org/10.62913/engj.v43i2.875)，[期刊](https://ej.aisc.org/index.php/engj/article/view/875)，[官方PDF](https://ej.aisc.org/index.php/engj/article/download/875/874) | 官方PDF已取得；本轮重点表1（印刷112/PDF2）、表4（印刷120/PDF10）及试验和屈曲讨论 | 17个单等边角钢循环试验，3批A36；表1有首循环方向、连接、有效长度与K，表4直接给coupon对应屈服力与压峰，可对先压10件做容量比特征标定；不能声称九参数全部识别 |
| WINDRAIN2024 | 张华恺等.《强对流天气下输电塔-线体系倒塌破坏与风雨组合系数研究》. 自然灾害学报2024,33(3):111–121. [DOI](https://doi.org/10.13577/j.jnd.2024.0310)，[官方PDF入口](https://cjournal.hep.com.cn/1004-4574/CN/PDF/10.13577/j.jnd.2024.0310) | 官方PDF已下载；已读3.1节、第115页示意与第121页参考文献 | VUMAT应用佐证，没有完整系数。参考文献[21]实际为JCSR2022:107344，不是2023固定端模型论文；搜索索引新日期不是出版年 |
| TMQ2018 | Tian L., Ma R., Qu B. *Influence of different criteria for selecting ground motions compatible with IEEE 693 required response spectrum on seismic performance assessment of electricity transmission towers*. Engineering Structures156:337–350. [DOI](https://doi.org/10.1016/j.engstruct.2017.11.046)，[出版社](https://www.sciencedirect.com/science/article/pii/S014102961731619X) | 官方摘要/书目；本轮未取得全文 | 是模型沿革/塔分析来源，不能代替2022九参数GA表格 |

## 公开预览的使用边界

JBE2022 第4页表1、第5页式(5)、第15页表2来自[公开原论文转录页面](https://www.scribd.com/document/1061083405/6-Development-of-hysteretic-model-for-steel-2022-fija)。只阅读无需登录的可见内容，没有下载受限全文。参数候选的 `source_quality` 明确保留此状态。其公式符号/范围存在排版或转录问题，不能用它替代原 PDF 视觉校核。

中文角钢论文的[参考网预览](https://m.fx361.com/news/2022/1215/18056088.html)只显示引言，后续要求 APP 登录；本轮没有把隐藏内容当作已读正文。

## 检索结果与未解决项

查询覆盖作者、模型全名、GA、参数、固定端单角钢、2018/2022/2023 DOI，以及中文角钢论文的官方站点。2022英文JBE的GA得到出版社直接支持；2022中文和2023固定端论文只确认“试验/参数分析/拟合”路线，没有确认其算法一定为GA。未找到公开的逐点实验位移—轴力数据仓储、原作者TMQ代码、`rho/gamma/zeta`明确统一值、可普遍适用于单角钢的2022九参数长细比回归公式。没有据“未找到”断言这些资料不存在。

优先获取次序：ANGLE2023完整式与表 → ANGLE2022CN式与表及试件对应关系 → 实验有序曲线与边界说明。上述步骤需要正式公开版本、用户已有文献或其机构合法订阅；本轮没有绕过付费或访问限制。
