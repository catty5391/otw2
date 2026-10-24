# T23：网页证据整合实施步骤与验证结果

日期：2026-10-22；执行agent：`execution_dashboard_validation`。

## 1. 本工作线范围

完整阅读执行计划第0～5节、T23任务卡、当前`QUALITY.md`及已有服务器、前端和测试。
沿用仓库本地`py_view/results_dashboard`网页，消费T03的`normalize_result_quality`。
本次网页请求均只读旧结果，没有重跑OpenSees，没有改旧摘要、旧缓存或旧内力库，没有操作9999进程。

实际改动：

- `py_view/results_dashboard/server.py`：版本化诊断/关键杆/新试验API、质量状态、证据来源、安全查询。
- `py_view/results_dashboard/static/index.html`：三案例和新试验展示区域，收敛/验证/范围的独立表达。
- `py_view/results_dashboard/static/app.js`：案例切换、关键杆轴力/应变图、保守未知值与状态展示。
- `py_view/results_dashboard/static/styles.css`：证据卡片及响应式图表布局。
- `py_view/results_dashboard/README.md`：启动、数据解释、API与测试说明。
- `py_view/results_dashboard/browser_smoke.cjs`：独立空闲端口真实Chromium操作、截图与结果记录脚本。
- `tests/test_dashboard_quality.py`：10项新增质量/实际HTTP测试。
- 本报告。

原`tests/test_results_dashboard.py`的5项测试继续使用，未通过修改预期规避失败。

## 2. 逐步实施

1. 核对磁盘实际证据。原网页读取旧`full_tower_cyclic`，硬编码`OpenSeesPy 3.7.1.2`、共同验证±0.6%和旧6/9对参考9/9的用时比；这些表达不能证明当前全塔材料已验证。
2. 加入固定三案例：`baseline`、`fine_sparse`、`elastic_877_878`。它们来自`results/convergence_diagnosis/`的实际summary/manifest/history/member数据，案例名不解释成任意目录。
3. 保留历史清单的保守读取结果。无新质量schema的旧manifest仍显示`legacy_unknown`且统计不准入。
4. 用T03质量对象在内存中派生带来源的诊断状态。计算完成从实际摘要读取；局部失配引用`evidence.json#member_comparison_at_negative_0_6_percent`，且必须实际超过冻结`acceptance_profile.json#tower_critical_force_relative`，不会仅因表非空判失败；临时Elastic明确标注诊断材料替换。
5. 按877/878的实际`calibration_key`逐根查找骨架压缩终点，流式读取已提交member历程并登记首次越界；没有使用全局3%常量，也没有宣称两根杆的压缩幅值审核等于全塔适用域通过。
6. 增加关键杆API，保留原杆号、截面、端点坐标、长度、按步顺序的轴力/等效应变/切线。切线明确为`dN/dε`，单位N；除以杆长才是N/m。
7. 前端并列三案例的覆盖、执行、验证、适用域、极限状态和统计准入；案例/关键杆可切换。整体图、关键杆轴力图和等效应变图分别绘制。
8. 参考对照仅展示实际已有负0.6%检查点，明确是四段参考首段轴力；未生成其他阶段参考时程、弯矩、曲率或节点变形动画。
9. 保留旧完整六分量内力探索器，并标识旧数据集；诊断CSV只有轴向通道，不接成完整弯矩内力库。
10. 增加`/api/followup`，自动发现新followup运行清单；未知/旧/无效质量仍由T03防御性读者隔离。冒烟试验的完成范围单独显示。
11. 增加实际存在的诊断报告、计划、质量报告、实施记录和决策下载入口；缺文件不提供下载条目。
12. 移除旧引擎版本与不公平速度比。引擎版本读取实际诊断摘要，Python包版本不推断；公平性能评估显示待评估。
13. 全部JSON响应增加`otw2.results_dashboard.v2`。SQLite改用`mode=ro`并关闭连接；模型/分量/案例/关键杆均白名单；下载/图片校验解析后路径，拒绝符号链接逃逸；NaN/Infinity进度返回400。
14. 在本进程自己创建的`127.0.0.1`空闲随机端口进行真实HTTP测试，测试结束关闭该服务。首次urllib请求受到环境代理影响返回502，测试明确使用`ProxyHandler({})`后通过；没有通过放宽服务器响应绕过错误。

## 3. 页面现在呈现的实际历史结果

| 案例 | 覆盖/成功步 | 执行状态 | 力学/范围表达 |
|---|---|---|---|
| 原步长baseline | 6/9，272步 | nonconverged | 已有局部失配，适用域完整审核未知；不标倒塌 |
| 同材料fine_sparse | 9/9，590步 | completed | validation failed；877/878压缩幅值out_of_range；统计拒绝 |
| 临时Elastic消融 | 9/9，587步 | completed | diagnostic、unvalidated、材料替换警告；不作修复证明 |

fine_sparse审核得到：

| 原杆 | 骨架压缩幅值终点 | 最大压缩幅值 | 首次越界 |
|---|---:|---:|---|
| 877 | 0.030000000000000016 | 0.0410276651325291 | step499，stage8 |
| 878 | 0.030000000000000016 | 0.041027665132528444 | step499，stage8 |

负0.6%目标的877、878压力幅值差分别约−78.53%、−79.04%。该比较沿用历史四段参考首段轴力证据；
没有把它提升为网格收敛后的最终真值，也没有用整体包络相关性遮盖局部问题。

新followup展示以磁盘现有manifest为准，不硬编码清单个数。本工作线读取时已发现空间参考记录器冒烟试验，
它的3个小幅目标与旧9目标强非线性协议分别标识，不能互相替代。

## 4. 命令及软件验证

仓库根目录运行：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test*dashboard*.py' -v
node --check py_view/results_dashboard/static/app.js
.venv/bin/python -m py_compile py_view/results_dashboard/server.py tests/test_dashboard_quality.py
git diff --check -- py_view/results_dashboard
```

新增10项检查覆盖：

1. 历史计算完成/验证失败/越界独立，首次越界step499/stage8。
2. 历史清单默认隔离与公平加速比未知。
3. 关键杆591点含重力step0、实际位置、同阶段参考范围、白名单。
4. 缺全部结果时概览unknown/不可用，不授予验证。
5. 新followup中伪造`eligible_for_fragility=true`的旧清单仍被隔离。
6. 固定下载/图片拒绝路径穿越和符号链接逃逸。
7. SQLite只读连接拒绝INSERT。
8. 真实HTTP读取新API、版本字段、nosniff头和首页新区域。
9. HTTP拒绝非法案例/杆号/模型/分量、NaN/Infinity、静态/下载路径穿越。
10. 比较表有数据但误差未超冻结门槛时保持unvalidated，不伪造failed或validated。

网页相关合计18项：新增10项、既有成果页5项、既有塔线页3项；最终源码回归18/18通过，末次11.907s。
补齐未知API的版本化404后，新增质量/HTTP子集再次10/10通过，20.678s。
Node语法检查、Python编译及限定范围diff空白检查通过。全仓库最终集成结果由主agent统一执行与记录，
本报告的18项不能代替全仓库测试数。

## 5. 真实浏览器实施与最后结果

初始环境没有浏览器控制工具、Python Playwright或Chromium。按主agent指令，在
`/tmp/otw2-dashboard-browser.7XNqJ5`独立安装固定`playwright@1.56.1`，下载Chromium Headless Shell
141.0.7390.37（build1194）和FFmpeg。没有sudo、apt或修改项目依赖/系统软件。
首次3分钟预算内仅完成包安装和部分下载，保存状态并终止本次下载进程；主agent随后明确追加预算，继续下载成功。
完整下载约106.6MiB，展开安装约315MB；第一次未完成的下载缓存保留，没有删除用户数据。

真实浏览器脚本每次创建自己的空闲端口服务；各次输出在新的目录中，不覆盖旧证据：

| 次数 | 实际结果与处理 |
|---|---|
| `dashboard_browser_v1` | 初始关键杆页面等待较慢，人工终止本次浏览器后记录Target closed；没有标通过。后续增加明确等待上限与失败DOM/截图。 |
| `dashboard_browser_v2` | 三案例、878切换、三张画布通过并生成桌面截图；下载测试定位器匹配正文和资源列表两处，strict mode拒绝。改为精确选择第一个已知下载入口，并正确收集Promise。 |
| `dashboard_browser_v3` | 全部页面操作通过并保存四张截图及11404B报告；末尾把成功附件下载的`net::ERR_ABORTED`误当网络错误。改为只在精确URL且文件确已保存验证时，单独记录预期下载导航事件；其他失败仍阻断。 |
| **`dashboard_browser_v4`** | **最终完整通过**，端口34139；错误0、非预期网络失败0、所有页面检查通过。自己的服务已关闭。 |

最终运行命令：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/otw2-dashboard-browser.7XNqJ5/browsers OTW2_PLAYWRIGHT_MODULE=/tmp/otw2-dashboard-browser.7XNqJ5/node_modules/playwright node py_view/results_dashboard/browser_smoke.cjs initial_imperfection_material/results/followup/execution_20261022/dashboard_browser_v4
```

该命令使用已经生成的目录会主动拒绝覆盖；复跑时必须换一个新的attempt目录。

最终8组检查为：

1. 三个历史案例、首次越界事件、独立质量状态、公平用时比待评估。
2. 切换baseline。
3. 切换Elastic消融。
4. 切回fine_sparse。
5. 切换877→878、核对参考检查点范围、三张诊断画布确已绘制。
6. 实际点击报告下载并检查落盘文件。
7. 旧完整内力库轴力与My查询，云图均显示1528根物理杆。
8. 390px窄屏无页面横向溢出，保存截图。

最终证据根目录：`initial_imperfection_material/results/followup/execution_20261022/dashboard_browser_v4/`。

| 文件 | 内容 |
|---|---|
| `browser_result.json` | passed、Playwright版本、8组检查、errors空、failed_requests空、单独保留预期附件导航中止 |
| `server.log` | 实际HTTP请求记录，案例、关键杆、报告下载、轴力/My查询均200 |
| `desktop_cyclic.png` | 桌面全塔曲线与当前研究边界 |
| `desktop_diagnostics.png` | 桌面三案例与独立质量卡片 |
| `desktop_member_charts.png` | 878轴力、等效应变、同阶段参考检查点、followup质量列表 |
| `mobile_diagnostics.png` | 390px三案例竖向布局 |
| `downloaded_convergence_report.md` | 浏览器真实下载的查因报告 |

执行agent实际打开并目视检查了桌面证据卡、关键杆图和手机截图，确认中文可读、数据与图表对应、窄屏没有横向裁切。
最终浏览器结果可从网页`/download?key=browser-summary`下载；桌面/手机截图增加固定白名单asset入口。
软件与浏览器验收不改变该材料的力学验证状态，fine_sparse仍是局部未通过且越界。

## 6. 交付状态与服务更新

**T23本批软件、自动API测试和真实浏览器验收已完成；后续产生新研究证据时仍需增量维护。**
9999服务更新由主agent协调。该工作线未结束或重启9999进程；全部浏览器试验的临时服务均自行关闭。
未修改TASKS.json，未提交/推送仓库，未新增agent。

## 7. 完整全塔计算完成后的网页小补充

本节是后续已实际执行的补丁。先阅读主agent最新`RESULTS.md`、`FULL_REFERENCE.md`和
`TOWER_SOLVER_REGRESSION.md`：legacy空间参考9/9、fine9/9仍在step499首次越界、gradual相同最小步设置
仅6/9与277成功步、T08全幅未通过。没有把这些新事实改成全塔物理验收通过。

补丁步骤：

1. 量测真实API响应。三个等效塔新清单各含1528个`member_domains`、1528个`observed_domains`，fine有74条域事件；原overview紧凑UTF-8 JSON达1,316,149B，followup为1,264,875B。
2. 对每份清单先用`normalize_result_quality`得出保守结论，再转换为独立的`otw2.result_quality_summary.v1`。计算、验证、适用域、极限状态、用途、策略、覆盖、失败原因、全部flags、准入结论和全局首次越界完整保留。
3. 完整域定义、已观测域列表、长事件列表和证据表不重复传给页面，改传各自准确计数。逐杆首事件按步排序最多预览20条，明确给出总杆数与`first_out_of_domain_by_member_truncated`，不会暗示预览是全量。
4. 每份摘要包含`source_quality_schema`和`authoritative_manifest`，明确原run_manifest仍是完整权威证据；摘要本身不能替代完整质量对象供正式研究准入使用。
5. 页面保留所有flags，显示首越界杆/步/阶段/值、域与事件计数及完整清单位置。fine依然是out_of_range、首次499；没有因压缩响应体积改质量结论。
6. 增加固定白名单下载：`RESULTS.md`、`FULL_REFERENCE.md`、`TOWER_SOLVER_REGRESSION.md`、`T09_ACTUAL_CALIBRATION.md`。核查时T10报告尚未存在；主agent明确文件名后，预设`CYCLIC_PROTOCOL_PREPARATION.md`的固定候选`cyclic-protocol-preparation`，仍只在文件确实存在时显示，不生成空下载链接。
7. 增加`full-reference-local`参考局部图asset，以及主agent四案例图的`/asset/tower-regression-plot`与`/download?key=tower-regression-plot`。没有重新设计页面或改图的验收边界标签。
8. 新增1528域/3056事件的序列化测试及真实HTTP体积测试，验证flags/状态/全局首事件不丢、逐杆预览明确截断、Content-Length正确、响应显著缩小，读取后原文件字节完全不变。
9. 使用已有Playwright/Chromium运行新的`dashboard_browser_v5`，无依赖重装。8组实际交互再次全部通过，端口35859的临时服务已关闭；零页面错误和非预期网络失败。

### 小补充最后结果

| 检查 | 实际结果 |
|---|---|
| 全部网页相关测试 | **20/20通过，13.367s**；原18项与新增2项 |
| 新1528域/3056事件测试 | 状态、flags、首事件保留；20条预览+截断计数明确；真实overview小于40KB且不修改源清单 |
| 实际overview | **1,316,149B → 69,263B，减少约94.7%** |
| 实际followup | **1,264,875B → 17,989B，减少约98.6%** |
| 原始6份followup清单 | 修改前后SHA256逐一一致 |
| 真实fine清单 | 1528域/1528观测、74事件、2根首越界、首个step499，out_of_range与原flags保留 |
| 真实浏览器v5 | **passed**，8组检查全通过，桌面/手机截图与HTTP请求记录已保存 |

上述实际体积是当前六份清单、相同紧凑JSON编码下的读数，不承诺未来新增任意清单后响应仍固定为此字节数。
完整质量flags不截断；即使后续flags很多也必须保留，不能为体积门槛删除警告。

最终补丁浏览器证据：`initial_imperfection_material/results/followup/execution_20261022/dashboard_browser_v5/`。
`browser-summary`、桌面与手机截图的固定资源已指向此次最新通过证据。初次v1～v4仍保留。
9999主服务本轮一直由主agent拥有；该补丁没有关闭或重启它，代码冻结后由主agent统一重启自己的服务。
