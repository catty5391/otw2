# 单角钢完整记录：来源、准入和分组

2026-10-26：取得 EPFL RESSLab 的 Jain 单角钢试验数字化记录 7 条、9560 点。8 件试件可按数据库几何整理成 4 个候选组，1L 缺少曲线。**尚无试件满足“实测 E、确认初态、原文核对时序”这一完整识别条件。**

## 来源

| 来源 | 用途 | 本地状态 |
|---|---|---|
| [EPFL RESSLab 数据库](https://resslab-hub.epfl.ch/braces/database) | 试件元数据、完整数字化曲线 | `raw/braces.json` 与 7 个 CSV；保留原字节和行序 |
| [公开元数据接口](https://resslab-hub.epfl.ch/api/braces?size=500&page=1) | 本次 294 件元数据 | 下载地址与哈希见 `download_manifest.json` |
| [Jain_2L 曲线接口示例](https://resslab-hub.epfl.ch/api/braces/Jain_2L/displacement/csv) | 位移 mm、轴力 kN；其余 ID 为 3L～8L | 无时间列；不得假定等时间间隔 |
| [Lignos、Karamanci、Martin，15WCEE 2012](https://www.iitk.ac.in/nicee/wcee/article/WCEE2012_4366.pdf) | 第 2 节说明数据库历史由原始试验报告数字化；第 2.1 节区分实测/名义屈服强度 | `papers/01_Lignos_Karamanci_Martin_2012_brace_database.pdf` |
| [Jain 1978 博士论文](https://deepblue.lib.umich.edu/handle/2027.42/127507) | 原始加载、券样、尺寸、端部连接及位移定义 | 本次 HTTP 403，未取得正文；没有绕过访问限制 |
| [Jain、Goel、Hanson 1980，Hysteretic Cycles of Axially Loaded Steel Members](https://ascelibrary.org/doi/10.1061/JSDEAG.0005498) | 对应试验期刊线索；17 管件及 8 角钢 | 出版社摘要，未取得付费全文 |

2012 论文的历史数据库统计为 295 件；本次在线 API 为 294 件。两者是不同时间的库快照，不能以历史数量替代本次下载验收。

## 得到与未得到的证据

- 得到的是公开数据库维护者整理的**真实试验数字化副本**；没有取得仪器原始采样时程。
- CSV 行序不变，不排序、不移零、不补原点、不制造时间。数据库方法论文支持“历史”的用途，但单条记录与原论文循环编号尚未独立核对。
- E 一律记录为 200 GPa，当前不能证明是实测 E。`fy_m` 虽标为实测，仍需核对原始券样表。
- 7L 首点为约 0.569 mm、17.839 kN，前序加载未知。其余曲线也有非零起点；不把这些值自动当扫描误差抹去。
- G01：1L/5L；G02：2L/6L；G03：3L/7L；G04：4L/8L。当前分组仅用于资料整理，不许可共享参数，也未选择训练/留出试件。
- 3L/7L 的名义尺寸尖角面积约 229.66 mm²，数据库 A=273 mm²，差约 18.9%；可能涉及真实尺寸、圆角或录入问题，待原文判定。数据库 K=0.7 明确属于假设值。
- 不从完整记录最大压力直接提取首压 φ；不由仅弹性段识别屈曲后系数。

## 执行入口

- [本批步骤与结果](../../initial_imperfection_material/tian_ma_qu/followup_results/ordered_history_20261026/REPORT.md)
- [分阶段识别输入说明](../../initial_imperfection_material/tian_ma_qu/GROUPED_IDENTIFICATION.md)
- 本地网页：`http://localhost:9999/tmq/followup_results/ordered_history_20261026/index.html`

原始 CSV、元数据全集及 PDF 已在本目录 `.gitignore` 排除。可以提交来源清单、方法和结论；本轮没有 git push，也没有更换全塔材料系数。

## 本轮后续取证与条件识别

[Jain复核](jain_primary_review.md)发现预拉和端部标签冲突线索，尚未获得原试件资料。另取得[Carden原报告与17件属性](alternative_history_review.md)，确认实测券样E/fy和P/Q同规格数据。P/Q作者连续路径9589点已用于名义几何条件识别：[本批步骤与结果](../../initial_imperfection_material/tian_ma_qu/followup_results/carden_conditional_20261026/REPORT.md)。这不改变Jain原批严格准入0件的历史结论。
