# T03：独立结果质量状态执行报告

执行日期：2026-10-22。工作线：`execution_quality`。本报告为已经执行的步骤和实际结果，不是下一轮计划。

## 1. 范围与前置条件

先完整阅读执行计划第0～5节、T03和T22任务卡，再检查既有RunManifest、29项公共分析/工作流测试及历史诊断文件。
主agent完成G0源码快照、53项测试基线后，明确发送“G0允许写入”，此后才修改源码。

本工作线仅实现质量状态基础设施和RunManifest接入，不修改材料、塔模型、风振/易损性入口或9999服务，不重算全塔，不改旧结果。
计划写的`fragility_curve/main.py`在当前项目中的实际位置是`fluctuate_wind_simulate/fragility_curve/main.py`。

改动文件：

- `util/analysis/result_quality.py`：新模块。
- `util/analysis/run_manifest.py`：保留原`status`及运行锁/原子写入语义，新增独立质量字段。
- `tests/test_result_quality.py`：17项新测试。
- 本报告。

## 2. 实际实施步骤

1. 冻结独立状态语义，使用`otw2.result_quality.v1`。执行完成、物理验证、适用域、极限状态分别登记，不互相推导。
2. 实现`ResultQuality`与证据登记。每个证据ID引用文件/报告/验收用例的位置；证据ID不能静默重指向别处。
3. 实现`MemberDomainRange`。每个原杆与每个量拥有自己的有符号上下界、单位、方向/边界限制以及标定来源；没有全局硬编码3%。
4. 实现已提交状态审核。失败trial不进入域检查；记录首次越界杆、步、阶段、量值、允许范围、证据和策略动作。数值越界与上下文未知分开标记。
5. 实现`stop/fail/diagnostic_continue`策略返回值。模块不操作OpenSees，不把已提交状态假装回滚，也不把求解失败解释为物理倒塌。
6. 实现域审核闭合。只有声明对象都观察过、无未解决事件且附完整审核证据时，才能从`unknown`变为`in_range`；审核闭合后禁止继续添加观察。
7. 实现正式统计准入条件派生。只有正式研究用途、计算完成、预定覆盖完整、明确范围内独立验证、有证据的域内审核、有已冻结物理判据及评估结果、无警告时，才可能得到`eligible_for_fragility=true`。该字段不能直接赋真。
8. 实现防御性读者`normalize_result_quality(manifest)`。无清单、旧清单、未知schema、字段缺失、无证据、互相矛盾的状态均默认隔离；不信任磁盘上直接写的`eligible_for_fragility=true`。读取不改旧文件。
9. RunManifest默认加未验证的质量信息；构造器接受`quality=ResultQuality(...)`，运行中可用`run.set_quality(quality)`保存明确审核结果。原`status`字段完全保留。
10. 执行新测试、既有分析/工作流回归，以及只读历史`fine_sparse`逐杆域检查，结果见后文。

## 3. 字段与接口

| 字段 | 默认/规则 |
|---|---|
| `execution_status` | 与当前RunManifest运行状态同步，允许completed/nonconverged/failed/interrupted等 |
| `validation_status` | 默认unvalidated；通过须validated+范围+证据；局部不符使用failed |
| `quality_flags` | 例如local_response_mismatch、out_of_calibration_range、unknown_domain_context |
| `domain_status` | 默认unknown；in_range或out_of_range不由是否完成计算推导 |
| `limit_state_status` | 默认not_evaluated；reached/not_reached须物理判据ID及证据 |
| `purpose` | training_fit/independent_validation/diagnostic/formal_research/legacy_unknown |
| `coverage` | requested/completed/unit；单位可targets或steps，不能混算 |
| `eligible_for_fragility` | 保守派生，默认false |
| `evidence` | ID→source/description；追溯性不等于软件自动认可文献结论 |
| `first_out_of_domain_by_member` | 每根原杆最早已提交越界事件 |

质量对象完整放在manifest的`quality`字段中；常用执行/验证/适用域/极限状态/准入字段同时在顶层给出。
显式传入quality时，其覆盖范围由调用方维护；不能用自适应成功子步数替代目标协议覆盖。

最小接入示例（这些证据路径是说明占位，不是已取得新验证）：

```python
from util.analysis.result_quality import ResultQuality, MemberDomainRange, normalize_result_quality
from util.analysis.run_manifest import RunManifest

quality = ResultQuality(purpose="diagnostic", domain_policy="diagnostic_continue")
quality.add_evidence("group", "new_run/calibration_library.json#actual_group")
quality.add_evidence("history", "new_run/member_states.sqlite")
quality.register_domain(MemberDomainRange(
    member_id=877, quantity="equivalent_strain", lower=-0.03, upper=0.02,
    evidence_ids=("group",), unit="dimensionless",
))  # 真实接入时必须从该组有效域读取上下界，不能抄示例常量。

with RunManifest("new_run", parameters={}, quality=quality) as run:
    quality.set_coverage(requested=9, completed=0, unit="targets")
    # 每个已提交状态调用observe_member_state；失败trial传committed=False。
    # 每个目标完成后更新completed目标数；stop/fail须由入口保存并停止。
    run.set_quality(quality)

# completed不代表validated；统计侧统一经此函数读取，而不是只看status。
assessment = normalize_result_quality(manifest_payload)
if not assessment["eligible_for_fragility"]:
    pass  # 分流并保留拒绝原因，不静默删除样本。
```

以上代码展示API形态，不是可用于物理验收的算例。未传真实协议和分析调用的上下文不能作为研究计算结果。

## 4. 测试命令与实际结果

在仓库根目录执行：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_result_quality.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_analysis_*.py' -v
```

| 测试 | 实际结果 | 内容 |
|---|---|---|
| 新质量模块 | 17/17通过，末次约0.044 s | 完成不等于验证、逐杆实际域、首次事件、方向/边界、trial隔离、证据、策略、正式准入、旧/坏清单、Manifest接入 |
| 原分析/工作流回归 | 29/29通过，约0.613 s | RunManifest原语义/锁/异常、stepper、响应比较、小OpenSees模型、风振入口与既有筛选兼容 |

累计本工作线执行的不同测试46项。**该数量不是全仓库最终集成测试总数**；其他agent仍在并行开发，由主agent最后统一统计。
新增测试仅证明软件数据契约，不证明新材料、空间参考或全塔力学已经验证。

## 5. 只读历史细步结果审核

读取：

- `initial_imperfection_material/results/convergence_diagnosis/fine_sparse/members.csv`
- 同目录`member_metadata.json`和`calibration_library.json`
- `initial_imperfection_material/results/convergence_diagnosis/evidence.json`

使用每根杆metadata中的实际`calibration_key`查对应组骨架，提取其压缩应变终点，然后按已提交step顺序审核。
只取`max(0,-equivalent_strain)`作压缩幅值；**本次只核对压缩应变范围，没有宣称塔端空间边界已被铰接标定覆盖**。
每根877/878读取591点（包含step0重力终点，590个后续成功步），不重运行OpenSees。

| 原杆 | 骨架压缩幅值终点 | 首次越界step / stage | 首次越界幅值 | 全程最大幅值 |
|---|---:|---|---:|---:|
| 877 | 0.030000000000000016 | 499 / 8 | 0.03033354019729604 | 0.0410276651325291 |
| 878 | 0.030000000000000016 | 499 / 8 | 0.030333540197295776 | 0.041027665132528444 |

这与已有“最大约4.103%超出3%骨架终点”的判断一致，并补出了**首次越界为step499、stage8**。
结合已有负0.6%目标的局部力失配证据，生成的状态为：

```json
{
  "execution_status": "completed",
  "validation_status": "failed",
  "domain_status": "out_of_range",
  "quality_flags": ["out_of_calibration_range", "local_response_mismatch"],
  "eligible_for_fragility": false
}
```

这是新质量接口对旧证据的**内存中审核**，没有把上述字段写回旧run_manifest或覆盖旧报告。
本次局部失配的验证证据直接引用既有`evidence.json`，没有将软件注入测试伪装为新物理对照。

可复查的核心只读命令如下（完整质量接口另有单元测试）：

```bash
.venv/bin/python - <<'PY'
import csv, json
from pathlib import Path
root = Path('initial_imperfection_material/results/convergence_diagnosis/fine_sparse')
meta = {r['original_element_tag']: r for r in json.loads((root/'member_metadata.json').read_text())}
groups = json.loads((root/'calibration_library.json').read_text())['groups']
limits = {m: max(abs(p['strain']) for p in groups[meta[m]['calibration_key']]['compression_envelope']) for m in (877, 878)}
first, maximum, counts = {}, {m: 0.0 for m in limits}, {m: 0 for m in limits}
with (root/'members.csv').open() as stream:
    for row in csv.DictReader(stream):
        m = int(row['element'])
        if m not in limits:
            continue
        value = max(0.0, -float(row['strain']))
        counts[m] += 1
        maximum[m] = max(maximum[m], value)
        if value > limits[m] and m not in first:
            first[m] = {'step': row['step'], 'stage': row['stage'], 'value': value}
print(json.dumps({'limits': limits, 'first': first, 'maximum': maximum, 'counts': counts}, indent=2))
PY
```

## 6. 最后结果与未达项

**已完成：T03核心质量契约、RunManifest兼容接入、防御性读者、逐杆域检查和软件测试。**
现有调用RunManifest的运行会默认增加未验证质量信息，但不会自动得到逐杆物理验证。

仍须后续任务执行，不能在本报告标完成：

1. T04/全塔入口在新成功子步调用域观察接口，把真实validation证据和覆盖范围填入；本次未改入口或记录器。
2. T23网页消费`normalize_result_quality`并明确显示局部失配/越界。
3. T22在`fluctuate_wind_simulate/fragility_curve/main.py`调用保守读者并形成样本流转表。**现有旧统计函数未修改，仍可能只按旧status筛选；不能因为本模块存在就宣布生产统计已强制准入。**
4. 冻结有来源的物理极限状态、完成空间局部/全塔/风振验收。测试中的虚拟criteria/validation证据不是项目真实通过证据。
5. 域审核的完整性需要调用方提供全程记录及审核报告；本模块验证结构、声明覆盖和事件一致性，不从一条观测自动证明全时程处于适用域。

未修改TASKS.json，由主agent结合实际整合范围登记任务状态。没有新开子agent，没有提交/推送，没有重启服务。
