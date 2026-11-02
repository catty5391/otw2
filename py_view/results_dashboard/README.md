# Z30103A6 本地成果网页

网页读取已有成果，不在请求中调用OpenSees。默认端口9999；测试使用独立端口，避免干扰已有进程。

## 模块独立页面（2026-10-28）

首页 `/` 改为分类入口和最近成果，图表进入各自模块后查看。

| 路径 | 内容 |
|---|---|
| `/modules/materials/` | Steel02/TMQ对比、曲线本构、参数识别、Carden及旧材料目录 |
| `/modules/tower/` | 全塔往复、薄弱位置、诊断与试验记录目录 |
| `/modules/tower-line/` | 模态、导线网格、频率响应、阻尼和绝缘子目录 |
| `/modules/wind/` | 单塔和塔线新旧方案、风攻角、风速目录 |
| `/modules/member/` | 旧材料单杆标定及交互曲线 |
| `/modules/cyclic/` | 旧版全塔往复与共同目标表 |
| `/modules/diagnostics/` | 独立查因案例、关键杆轴力和应变 |
| `/modules/followup/` | 试验清单与质量状态 |
| `/modules/forces/` | 内力探索、指定时段包络、杆件历史 |
| `/modules/resources/` | 报告下载和本地论文 |
| `/modules/archive/` | 既有模型、推覆、找形与历史图表 |

`navigation.py`维护固定模块目录；`static/layout.html`提供共享布局；`static/pages/`存放独立内容。首页和目录只加载`site.js`，不请求分析API。交互页使用`app.js`按当前页面加载数据，窗口缩放只重绘已有数据。既有结果HTML保留原URL，HTTP响应增加返回首页/分类目录入口，源结果文件不被重写。旧`/#tianmaqu`、`/#forces`等书签自动跳转到新页面。

本轮10项路由、内容分离、报告编码和相关回归测试通过；浏览器核验12页、29个模块目标、桌面/390px手机、旧书签跳转、菜单及0—2步内力包络查询。记录位于本地 `py_view/.output/dashboard_multipage_20261028/`。

## Tian–Ma–Qu 新材料入口

2026-10-29新增[四分段初始缺陷：空间验证](http://localhost:9999/segmented-validation/)：三根实际塔杆，36个网格/往复工况与27个方向/幅值工况全部完成；独立页面展示五组曲线、步骤和全部有序CSV。材料目录及首页近期入口已接入。此模块共享全塔完整Steel02参数，不能当作全塔边界或真实角钢试验验证。完整方法见[模块说明](../../initial_imperfection_material/segmented_member_validation/README.md)。

本轮63项针对性测试通过；9999桌面1440px/手机390px、5幅图、24个页面和资源链接及目录往返检查通过。核验文件与截图位于 `py_view/.output/segmented_validation_20261029/`。

2026-10-28新增 [Steel02四分段初弯曲与TMQ对比](http://localhost:9999/steel02-tmq/)：46个单杆工况全部完成，包含两种杆长、完整往复、4/8/16/32段、缺陷幅值/形状和力法梁补充。文献PDF与说明由独立白名单提供；首页展示完整滞回。新增机械及HTTP检查与相关回归共15项通过，桌面/390px手机、8幅图及32个资源链接检查通过。详见本地 `py_view/.output/steel02_tmq_comparison_20261028/`。这是平面单杆数值比较，未宣称全塔或物理试验验证通过。

2026-10-28后续新增 `/liu-phm/results/index.html`：独立解析曲线本构、真实Carden分支拟合、1980步实际OpenSees单杆。采用单独固定白名单，保持材料族与原TMQ全塔参数分离。另发布 `/tmq/followup_results/carden_sign_audit_20261028/index.html`，说明原拟合恢复支偏左的定量原因及Q原点元数据更正，原始数据不作翻号或平移。

2026-10-28：按用户要求移除新增时间线简报，原分析报告保留；增加[新材料实现与参数说明](http://localhost:9999/tmq/followup_results/development_notes_20261028/index.html)。修复中文报告响应缺失字符编码的问题：文本、JSON、SVG 等统一声明 UTF-8，MD/TXT/CSV 重新验证缓存，二进制图片与 PDF 不改字节。编码回归检查见 `tests/test_dashboard_report_encoding.py`。

同日加入[单塔新旧四风角对比](http://localhost:9999/tmq/followup_results/single_tower_wind_comparison_20261028/index.html)和[塔线新旧四风角对比](http://localhost:9999/tmq/followup_results/tower_line_wind_comparison_20261028/index.html)。首页直接列出 40 m/s、0°/30°/45°/90°的共同完成结果；单塔 8 组合均达到 80 m/s，塔线 7 组合达到 80 m/s，0°四分段塔线因计算预算停止，最后完整保存 54.772 m/s，正式目标比较到 40 m/s。高风速局部 TMQ 压屈、V 串受压与预算停止分别说明，未认定工程极限风速。

本次 34 项针对性测试通过（网页与编码19、诊断HTTP复核1、单塔9、塔线5）；4页桌面/390px手机和25项页面/资源/访问边界检查通过。塔线长文本与表格溢出已修复。记录见本地 `py_view/.output/tmq_integration_20261028/integration_verification.json` 与 `browser_verification.json`。早期并发计算期间的广泛回归有HTTP超时且中止，未冒称整套通过；相关HTTP用例随后单独复核通过。

2026-10-26新增[参数识别页面](http://localhost:9999/tmq/followup_results/parameter_identification_20261026/index.html)：
展示10件先压单角钢和5件Black试件的条件容量参数、文献候选、GA收敛及明确标为合成数据的完整循环恢复。
`/api/tian-ma-qu`新增`parameter_identification`，保留未完成真实循环标定及未修改生产参数的状态。
35个HTTP检查与桌面/移动端显示通过，记录见[整合验收](../../initial_imperfection_material/tian_ma_qu/followup_results/parameter_identification_20261026/publication_verification.json)。

9999 首页选择 **材料研究**，再进入 **Tian–Ma–Qu 单杆滞回**；相关全塔、风荷载与塔线成果分别进入对应分类。也可直接访问：

- `http://127.0.0.1:9999/modules/materials/`：材料模块目录；旧`/#tianmaqu`书签会跳转至此。
- `http://127.0.0.1:9999/tmq/`：独立完整展示，含三组切换、计算顺序滑块回放、加载历史和假设敏感性。
- `/api/tian-ma-qu`：只读 `initial_imperfection_material/tian_ma_qu/results/summary.json`，保留计算完成与试验验证的区别。

报告文献栏目新增材料报告、文献溯源和运行说明。`/tmq/` 仅发布固定白名单的结果、报告与 CSV，不开放源码、原生编译缓存或任意目录。此项接入不会重新计算材料或全塔，也不改写既有结果。旧材料标定保留并单独命名，避免与 TMQ 混淆。若浏览器仍显示旧导航，请强制刷新；更新后的 HTML/JS/CSS 使用重新验证缓存策略。

当前 9999 由用户级临时服务 `otw2-dashboard.service` 托管；`systemctl --user status otw2-dashboard.service` 查看状态，`journalctl --user -u otw2-dashboard.service` 查看日志。临时服务未设开机自启。

本次接入验收：28 项 `test*dashboard*.py` 测试通过；独立端口的真实 Chromium 检查了新导航、三组结果、完整图片、案例切换、滑块回放及 390px 移动端布局，同时复查旧诊断和内力视图。记录与截图见 [browser_result.json](validation/tmq_20261023/browser_result.json)、[桌面截图](validation/tmq_20261023/desktop_tmq.png)。正式 9999 的首页、TMQ API、回放页面、SVG 和报告下载均实测返回 200；原 22 个 TMQ 结果产物的 SHA-256 均未改变。

## 常规启动

```bash
.venv/bin/python -m py_view.results_dashboard --host 127.0.0.1 --port 10000
```

浏览器打开`http://127.0.0.1:10000`。将正式服务更新到9999前，先核对该端口进程归属；本次T23没有结束或重启9999进程。

## 数据与解释

- 单杆页保留既有推覆、峰前卸载、网格与杆长算例，明确其证据只覆盖相应算例。
- 旧全塔6/9结果与四段参考9/9结果继续保留。共同完成目标、整体误差、逐杆局部验证分开展示。
- 三个诊断案例来自`initial_imperfection_material/results/convergence_diagnosis/`：`baseline`、`fine_sparse`、`elastic_877_878`。
- `fine_sparse`是计算完成9/9，但关键杆局部响应未通过且压应变越界；页面不会因此授予物理验证或易损性统计准入。
- 877/878的应变终点从实际`member_metadata.json`→`calibration_key`→该组`compression_envelope`读取，不使用全局3%常量。只读审核保留首个已提交越界事件。
- 旧清单经`normalize_result_quality`默认隔离。派生历史诊断状态在内存中构建，不回写旧结果；两根杆的压缩幅值检查不代表全塔、拉伸或边界适用性审核完成。
- Elastic消融标注`diagnostic_material_substitution`；它用于查因，不是最终新材料。
- 关键杆图按已提交步顺序绘制轴力和等效应变。已有参考检查点明确限定为负0.6%目标的参考首段轴力，不生成其他阶段的参考历程。
- 内力探索器继续读取旧`full_tower_cyclic`完整六分量SQLite；诊断CSV只含轴向状态。SQLite以`mode=ro`打开，并在查询后关闭连接。
- 新`results/followup/**/run_manifest.json`通过独立清单列表展示；计算用途、覆盖、验证、适用域、物理极限状态分别显示。
- followup的`quality`是`otw2.result_quality_summary.v1`摘要：全部质量flags、独立状态、覆盖和全局首次越界原样保留；域对象/观测/事件/证据改传准确计数，不传1528个完整域与长事件表。逐杆首事件最多预览20条，明确给出截断标记及总数；`authoritative_manifest`指向不变的完整权威清单。摘要不能冒充完整质量证据或输入正式统计。
- 引擎版本来自实际诊断摘要；包版本未知时不推断。旧6/9与9/9用时不构成公平加速比，页面显示待评估。
- 没有节点位移历史时不提供变形动画。页首塔形是静态示意。

## API

所有JSON响应增加`api_schema: otw2.results_dashboard.v2`，保持原API字段兼容。

| 路径 | 内容 |
|---|---|
| `/health` | 服务健康状态 |
| `/api/overview` | 概览、诊断摘要、新试验清单 |
| `/api/pushover`、`/api/cyclic` | 既有单杆及旧全塔曲线 |
| `/api/diagnostics` | 三个固定案例、独立质量状态与证据 |
| `/api/diagnostics/curve?case=fine_sparse` | 一个案例的已提交全塔曲线 |
| `/api/diagnostics/member?case=fine_sparse&member=877` | 关键杆轴向历程、位置、同阶段参考检查点 |
| `/api/followup` | 新followup清单与保守质量状态 |
| `/api/internal-force/meta?model=equivalent` | 旧完整内力库元信息 |
| `/api/internal-force/snapshot`、`envelope`、`history` | 既有内力查询接口 |
| `/api/resources` | 实际存在的报告与文献 |
| `/download?key=convergence-report` | 固定白名单报告下载 |

诊断案例固定为三个白名单名称；关键杆固定为825、828、877、878、917、920。其他模型、分量、案例、杆号返回400。
缺少所请求的曲线/库返回带版本号的JSON错误；概览缺文件显示`unknown`/不可用。静态文件、图片和下载使用白名单及项目根路径校验，拒绝符号链接逃逸。
非有限进度（NaN/Infinity）返回400。没有将查询值拼接成任意SQL列名，列名先经过固定分量白名单。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -p 'test*dashboard*.py' -v
node --check py_view/results_dashboard/static/app.js
```

HTTP测试用`127.0.0.1`空闲随机端口并禁用环境代理；测试结束关闭自己创建的服务。
`browser_smoke.cjs`可配合独立安装的Playwright 1.56.1执行真实Chromium冒烟，自动使用空闲端口并保存截图/结果；
必须传入尚不存在的输出目录，避免覆盖既有证据。例如：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/otw2-dashboard-browser.7XNqJ5/browsers OTW2_PLAYWRIGHT_MODULE=/tmp/otw2-dashboard-browser.7XNqJ5/node_modules/playwright node py_view/results_dashboard/browser_smoke.cjs initial_imperfection_material/results/followup/execution_20261022/dashboard_browser_new_attempt
```

`/tmp`依赖目录可能被系统清理；若缺失，需在新的临时目录独立安装上述固定版本并下载headless Chromium，
不需要把Playwright加入本项目依赖或改系统软件。脚本报告只代表实际完成的检查。
本批实际Chromium操作、桌面/手机截图和最终通过结果见
[`DASHBOARD_VALIDATION.md`](../../docs/ai_execution_plan/execution_20261022/DASHBOARD_VALIDATION.md)。

### 单角钢历史候选数据

`/api/tian-ma-qu` 的 `ordered_history` 与新材料区入口展示 `followup_results/ordered_history_20261026`。7条试验数字化记录保留CSV行序、原始偏移和全部9560点；交互页面可逐行查看，行号不代表时间。严格拟合准入0件；真实循环参数尚未识别。白名单只包含已发布曲线、摘要、图表和报告，不暴露源代码或下载原目录。

### Carden真实回线条件识别

`carden_conditional` API字段和主页新材料首个入口对应 `followup_results/carden_conditional_20261026`。P训练/Q留出、9589个原始绘图顶点、名义几何条件、ρ追加识别及全部失配均保留；结果明确非物理验证通过。

2026-10-29新增独立模块 `/tower-pushover/`，首页及“单塔分析”目录均有入口。展示Steel01/Steel02四分段与TMQ整杆等效在0°/30°/45°/90°的位移控制推覆，支持风角表格筛选、5类图、CSV/JSON及完整报告下载。原始全塔逐杆大文件保留本地，仅白名单汇总及必要单例诊断对外开放。末点、采样峰值、首屈服/压屈和数值停止分别标记。

## 雨谱与风雨荷载模块（2026-11-02）

独立入口 `/rain-loading/`，导航别名 `/modules/rain/`，首页和侧栏均有入口。概念说明区分雨滴粒径谱、雨强时程与荷载功率谱，计算结果来自 `rain_loading/results/summary.json`，不在网页中生成或补齐物理结果。

结果接口：`schema: otw2.rain_loading.v1`；`title/subtitle/status/scope` 为文本，`findings/assumptions` 为文本数组；`steps` 每项含 `title/detail`；`equations` 每项含 `name/expression/description`；`tables` 每项含 `title/columns/rows`，列含 `key/label`；`figures` 每项含 `title/file/caption`；`verification.checks` 每项含 `name/passed/value/criterion`；`sources` 每项含 `title/url/note`；`artifacts` 每项含 `title/file`。文件名相对 `results/`，仅发布服务器固定白名单中的实际产物。`literature_report_available: true` 显示文献调查链接。

检查项只在 `passed` 为布尔值 `true` 时显示“通过”，且页面明确数值核验不等于物理试验验证。缺少摘要显示“结果尚不可用”，缺少图显示实际读取错误；不会显示默认示意结果。新增报告和文献入口保留 UTF-8。报告阅读入口 `/rain-loading/results/REPORT.md`，文献入口 `/rain-loading/literature/README.md`。

针对性 HTTP、导航与编码检查：

```bash
.venv/bin/python -m unittest tests.test_rain_loading_dashboard tests.test_dashboard_navigation tests.test_dashboard_report_encoding -v
node --check py_view/results_dashboard/static/rain.js
```

实际数据的 Chromium 检查使用 `rain_smoke.cjs`，需指定新的输出目录；检查首页入口、真实图和检查项数量、全部展示资源链接、UTF-8、桌面/390px手机溢出、移动导航以及隔离的缺数据状态。该脚本不会修改分析结果。

同日补充通用风雨加载接口，页面新增 `loading_interface.md`、`loading_interface_verification.json`、`loading_interface_history.csv` 与 `loading_interface_validation.png`。展示独立弹簧动力叠加、矩阵指数精确解及步长收敛，并记录0°Steel02全塔接口替换前后的位移/反力差为零。该动态图不代表全塔风雨动力分析。现在页面共有9图、22项检查；原雨荷载物理假设保持原记录。

上线验收：14项网页HTTP/导航/编码测试通过；正式9999的8幅图、18项检查、19个展示资源链接、UTF-8及桌面/390px手机均通过，未出现JavaScript错误。最终截图和浏览器记录位于 `py_view/.output/rain_loading_browser_published_20261102/`，HTTP及服务记录位于 `py_view/.output/rain_loading_http_20261102/`。显示层保留6位有效数字，小数绝对值小于1e-4时采用科学计数；原始JSON/CSV精度不变。临时验收端口45409已关闭，正式9999由用户级服务保持运行。
