# 交给后续 AI 的开工提示

以下文字可直接复制：

> 请在 `/home/panqiheng/otw2` 的当前工作区，按 `docs/ai_execution_plan/tmq_next_plan_20261024/` 执行首批 **N00～N05**。先读 README、PLAN、METHODS、NEXT_TASKS、ACCEPTANCE 和 BASELINE。
>
> 本批目标是：保留现有成果，统一模型身份；利用现有裸塔及20/40/80段塔线的K/M、完整振型和风荷载，解释X向耦合的网格敏感性；完成成组模态/子空间比较及实际风荷载投影；审计阻尼和空间时程适配所需接口；发布诊断图与说明。
>
> 本批不新增全塔特征值、推覆或随机风时程。使用保存的矩阵做线性代数/静柔度求解属于本批允许的后处理。若发现必须补新FE，先写清触发证据、最小新增工况和预算，交到N06的下一批。
>
> 逐项交付实际步骤、改动、命令、结果、测试、局限，不只给计划。所有旧数据与旧任务状态保留，结果写入唯一新目录。不要reset、checkout、删除已有未提交工作，不要改旧summary数值让其符合新结论。
>
> N00检查变化后，按事实更新当前批基线；N01冻结模型声明；N02使用float64原振型和共同原塔质量，不使用viewer显示值；N03在各网格重组同一个物理荷载，不复制20段节点标签到80段；N04明确`doRayleigh`、区域和实际阻尼待验证；N05解除发布器硬编码时保留原页面行为。
>
> 本批结束应给出：哪些频段/响应可靠，哪些仍敏感，是否确需160段或更多阶，推荐的最小下一批是什么。物理验证状态继续为unvalidated，数值诊断通过不能改成工程认可。

## 真实存在的命令与入口

从项目根目录运行。下面两个命令只显示帮助，不启动FE：

```bash
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.modal_analysis --help
.venv/bin/python -m initial_imperfection_material.tian_ma_qu.full_tower --help
```

计划一致性检查（本包自带；仅检查文档、JSON、依赖和基线，不运行OpenSees）：

```bash
.venv/bin/python docs/ai_execution_plan/tmq_next_plan_20261024/check_plan.py
```

N06在下一批获得执行范围且满足触发条件后，可以使用以下**真实CLI示例**；本批不要执行：

```bash
OPENBLAS_NUM_THREADS=1 timeout 900 .venv/bin/python \
  -m initial_imperfection_material.tian_ma_qu.modal_analysis \
  --segments 80 --modes 300 --solver scipy \
  --output initial_imperfection_material/tian_ma_qu/followup_results/B2_unique/runs/coupled_80_300
```

该目录必须不存在；运行前检查剩余内存/磁盘、自由质量秩、矩阵维数和当前参数限制。`timeout`返回124应标超时，不能按成功发布；stdout/stderr应由批次监督器保存。当前modal CLI没有`--timeout`参数。
另一个160段工况只有N06明确需要时才运行，仍不超过300阶。不要照抄旧计划中的400/640阶或擅自扩大segments限制。

**尚未存在**：本计划中的成组诊断器、广义风投影器、专用TMQ瞬态runner及其CLI。应按任务开发并测试，不能在说明中把拟定命令写成已可运行。
现有`wind_refactor_common.run_one_sample`只支持`model_factory/initialize_model`等现有参数，不接受本计划拟议的`wind_loader`或`analysis_initializer`。

## 接班前必须看懂的事实

- 风速结果塔线20段，模态主结果80段；统一之前不得称同一模型。
- 0.195Hz是导线主导低频；塔体主要模态约2～2.5Hz。
- 160阶有效质量比不是风荷载覆盖率；真正截断判定依赖输入、输出和频带。
- 45°推覆已存在峰后下降；塔线未跑完1%X目标，停止不等于倒塌。
- 导线/绝缘子默认元素Rayleigh标志未开启；需分别检查节点质量阻尼，不能简单宣称完全无阻尼。
- 旧风入口单DOF楼层加载和旧漂移方向不能直接用于任意风向塔线时程。
- 角钢TMQ循环、气动力与远端边界尚未物理验证；正式损伤/易损性不自动放行。
- 不启动额外子agent，除非用户或适用指令另有要求；这份计划的编制已用1个子agent，后续执行并行方式不由本文件代替用户决定。

## 完成一批的回答格式

1. 本批实际完成的任务与评估结果（完成/未通过/受限须分开）。
2. 关键数值和结论，链接对应图、原始表、报告与代码。
3. 运行的测试、FE个数、成功/失败/超时及实际预算消耗。
4. 9999新增结果的URL（若本批发布）及旧入口回归情况。
5. 下一批最多一个明确建议，列前置已满足与未满足项；不得把未做工作写成已验证。
