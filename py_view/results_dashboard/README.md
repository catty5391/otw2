# Z30103A6 本地成果网页

网页读取已有成果，不在请求中调用OpenSees。默认端口9999；测试使用独立端口，避免干扰已有进程。

## Tian–Ma–Qu 新材料入口

9999 首页左侧选择 **Tian–Ma–Qu 新材料**，或直接访问：

- `http://127.0.0.1:9999/#tianmaqu`：三组完整滞回曲线、实际完成步数、峰值与 CSV 下载。
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
