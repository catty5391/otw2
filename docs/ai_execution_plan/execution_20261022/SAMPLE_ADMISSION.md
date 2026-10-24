# T22工程前置：全样本流转与准入审核

执行日期：2026-10-22。工作线：原第3角色`execution_quality`继续执行；没有另开agent。

**状态：完成独立软件准备及实际响应提取入口的保守准入接入；T22物理判据、动力验证和正式易损性研究仍未完成。**

## 1. 任务范围与执行步骤

1. 阅读当前质量契约、实际易损性入口`fluctuate_wind_simulate/fragility_curve/main.py`和冻结验收配置。确认旧入口只过滤已存在清单的非completed状态；没有清单的旧结果仍可能被读取。
2. 第一阶段新建`util/analysis/sample_admission.py`，当时不改现有入口；后续经主agent明确分配，接入实际易损性响应提取入口，详见第7节。风振和全塔入口仍不由本工作线改动。
3. 定义单样本输入：`sample_id`、`wind_speed`（m/s），以及完整`manifest`或完整`quality`对象，二者不能同时输入；可选旧有限响应`response`和来源路径。
4. 每个输入保留一条流转记录。计算状态、局部验证、适用域、极限状态、覆盖和准入分别登记；一个样本可以同时具有多个拒绝原因。
5. 正式准入先经过`normalize_result_quality`，再核对本次选定的`criteria_id`、样本身份、风速和输入完整性。未选物理判据、缺清单、未知schema、冲突/伪造eligible均不能成为正式样本。
6. 增加显式`exploratory_legacy`模式：只允许没有新质量信息的历史有限响应作探索展示，标签固定为`exploratory_legacy_only`；未知/损坏的新quality不能降级绕过，失败运行不能被该模式挽救。
7. 生成全样本流转表、整体/风速档计数、未知物理状态比例、数值失败中的未分类比例。重复身份保留两行但均隔离，不能静默去重；样本预算超出直接报错，不能偷偷截断。
8. 给出有限队列事件比例的计数识别界限，禁止把数值失败自动归成倒塌或统一右删失。没有选定物理判据、队列身份无效或空队列时不给上下界。
9. 执行15项新增测试、17项质量回归和29项公共分析/工作流回归。
10. 在70条预算内，只读审核已有`input_wind_drift.csv`全部70条记录，逐条检查旧入口预期manifest路径；不计算动力模型，不从已有峰值反推失效。

## 2. 文件与接口

新增：

- `util/analysis/sample_admission.py`
- `tests/test_sample_admission.py`
- 本报告
- [sample_admission_legacy_audit.json](sample_admission_legacy_audit.json)：70条逐样本结果、来源指纹、风速档和两种模式的汇总。

接口：

```python
from util.analysis.sample_admission import (
    load_manifest_sample, assess_sample, build_sample_flow,
)

sample = load_manifest_sample(
    sample_id="sample_01", wind_speed=20.0,
    manifest_path="new_results/20mps/sample_01/run_manifest.json",
)
row = assess_sample(sample, criteria_id="physically_frozen_rule_id")
report = build_sample_flow(
    [sample], mode="formal", criteria_id="physically_frozen_rule_id", max_samples=70,
)
```

以上判据ID仅是API占位，不能直接当项目已冻结的真实阈值。`mode`默认formal；没有真实判据ID时仍可统计拒绝原因，但不会正式准入。

`load_manifest_sample`对每个明确路径最多读取8 MiB，可显式配置；不存在/损坏/超预算的清单保留为该样本的input_errors，不抛弃样本。
模块不遍历输出目录，不自动发现/删除/补算样本。调用方必须把预先声明队列中的未运行、缺文件和失败样本也列入，不能仅传已有成功目录。

主要输出：

| 字段 | 含义 |
|---|---|
| `rows` | 每个输入一条，不静默过滤；包含record_index、来源、质量、理由、响应、证据ID |
| `admission_status` | formal_admitted / exploratory_legacy_only / excluded |
| `reason_codes` | nonconverged/failed/interrupted/legacy/out_of_domain/physical_state_unknown等，可并列 |
| `reported_limit_state_status` | 原质量声明的状态，保留供复核 |
| `physical_state_for_selected_criterion` | 只有正式通过且同一物理判据的样本才计reached/not_reached，其他unknown |
| `overall`、`by_wind_speed` | 全部记录、正式准入、探索、排除、执行状态、拒绝原因及未知比例 |
| `unclassified_failure_fraction_of_failures` | 未分类数值失败数/明确数值失败数；分母0时null，不能说失败率100%或0% |
| `unclassified_failure_fraction_of_all_records` | 未分类数值失败数/全部输入记录数，与上项分母不同 |

风速档按精确输入值分组，不插值、不擅自四舍五入分箱。相同sample_id在不同风速档可以存在；同一风速档重复ID必须复核。

## 3. 计数上下界的限定

在选定同一个已冻结物理判据、队列身份明确的前提下，令：

- N：传入队列全部记录数，不是仅通过筛选后的记录数；
- R：已正式核实的reached数；
- U：物理事件未知数；
- 已核实的not_reached数为N−R−U。

返回`[R/N, (R+U)/N]`，它仅表示这些未知结果在两端情形下，**当前有限队列**可能的事件比例范围。
不是拟合概率、不是置信区间，更不是总体易损性曲线。
代码不会给每个未知样本实际赋“倒塌/未倒塌”，也不会添加right_censored标签。

即使未收敛样本的原质量字段声称reached，该声明也只保留为`reported_limit_state_status`，在当前保守策略下不会升级成正式已知事件。
以后若要认可“终止前已确证首次穿越”的事件，须另行定义观测机制、证据及准入规则，不能仅因字段存在就绕过完整质量门槛。

## 4. 实际测试结果

执行命令：

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_sample_admission.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_result_quality.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_analysis_*.py' -v
```

| 测试组 | 实际结果 | 范围 |
|---|---|---|
| 样本准入新增 | 15/15通过，末次约0.083 s | formal/legacy、失败、越界、不同判据、未知事件、计数界限、重复ID、非有限输入、坏文件、预算及输入不变 |
| 质量契约回归 | 17/17通过，约0.046 s | T03语义不退化 |
| 公共分析/工作流回归 | 29/29通过，约0.813 s | 原入口兼容、清单、分析工具和小OpenSees模型 |

本次不同测试合计61项，**不是全仓库最终集成测试数量**。这些测试不构成真实物理阈值或新材料动力验证。

## 5. 70条旧记录的只读审核结果

输入为当前已有导出表：`fluctuate_wind_simulate/fragility_curve/input_wind_drift.csv`，3296 bytes。
SHA256：`5c017d4834fd636d5b9605ef94c77cc12c159c7331af35b36705a95eb0813ad8`。

该表包含10、20、30、40、50、60、70 m/s共7档，每档10条，总计70条有限响应。
旧脚本预期的原始输出根目录`fluctuate_wind_simulate/static/.opensees.output`在本工作区不存在，因此对应70个run_manifest均缺失。
这不证明原计算失败，也不证明原计算完整；**执行状态应为legacy_unknown，不是failed**。

| 模式 | 保留流转记录 | 正式准入 | 仅历史探索 | 排除 | 物理事件未知 |
|---|---:|---:|---:|---:|---:|
| 默认formal | 70 | 0 | 0 | 70 | 70 |
| 显式exploratory_legacy | 70 | 0 | 70 | 0 | 70 |

每个风速档的正式准入都是0/10，未知物理状态都是10/10。
明确记录为数值失败的样本数为0；由于执行记录缺失，这不应被表述成“70次计算全部成功”。
“未分类数值失败/明确数值失败”的比例为null（0/0）；未知物理状态占比为100%。
没有选择已冻结物理判据，所以上下界均为null，原因`criteria_not_selected`，没有输出伪易损性概率。

逐样本JSON同时保留CSV行来源、预期清单路径、响应值和两种模式标签。未读取另外两份响应表凑更多样本，未对同一70样本重复计数。

只读复查示例：

```bash
.venv/bin/python - <<'PY'
import csv, json
from pathlib import Path
from util.analysis.sample_admission import load_manifest_sample, build_sample_flow
source = Path('fluctuate_wind_simulate/fragility_curve/input_wind_drift.csv')
root = Path('fluctuate_wind_simulate/static/.opensees.output')
samples = []
with source.open() as stream:
    for row in csv.DictReader(stream):
        if len(samples) >= 70:
            raise RuntimeError('read budget exceeded: do not truncate')
        samples.append(load_manifest_sample(
            row['sample'], float(row['wind_speed']),
            root/row['speed_dir']/row['sample']/'run_manifest.json',
            response=float(row['response']),
        ))
for mode in ('formal', 'exploratory_legacy'):
    result = build_sample_flow(samples, mode=mode, max_samples=70)
    print(mode, json.dumps(result['overall'], ensure_ascii=False))
PY
```

## 6. 最终结论与T22真实缺口

软件可以保留所有样本并解释它们为何不能进入正式统计；不会把只保留成功样本后的结果冒充完整队列。
但**本工作没有完成T22**，仍缺：

1. 空间局部、全塔及动力阶段门通过的证据；本次未选择A/B/C路线。
2. 有正式来源并与响应量相容的物理极限状态；不能把当前0.001/0.0015/0.002或样本分位数直接视作可靠倒塌阈值。
3. 等效应变与钢材纤维应变的已验证映射或分别定义的判据。
4. 风速档、样本数、种子、停止规则及完整队列清单的冻结。
5. 对未知/失败样本的补算或可辩护观测机制，及统计拟合、置信区间和敏感性分析。
6. 风振侧可靠质量证据与后续正式统计流程：实际`fragility_curve/main.py`响应提取已按第7节接入保守准入，但风振入口未由本工作线修改，正式概率拟合也未因入口接入就自动开放。

没有重跑动力、写回旧清单、修改原CSV、启动全样本计算或修改TASKS.json。T22只能登记“工程前置已做，物理/统计任务待后续”，不得标done。

## 7. 追加执行：真实易损性入口接入

主agent在前述独立模块完成后，明确要求本工作线继续接入实际入口；以下为本次追加执行的步骤与结果。

### 7.1 改动位置与行为

- 修改`fluctuate_wind_simulate/fragility_curve/main.py`。
- 新增`tests/test_fragility_admission.py`。
- 在`tests/test_analysis_workflows.py`原下游演示测试中，仅给提取函数调用增加`eligibility_mode="exploratory_legacy"`参数；没有把fixture伪造为已验证材料。
- 没有改`wind_refactor_common.py`、RunManifest或现有旧结果。

实际完成：

1. `extract_input_from_opensees`新增keyword-only参数`eligibility_mode`（默认formal）、`criteria_id`、`audit_json`和`expected_samples`。
2. 对每个发现的样本读取清单和响应，失败、未收敛、无清单、缺响应、非法/非有限响应、越界和物理状态未知均保留在完整流转表，不静默删除。
3. 默认把审计写到输出CSV同名的`*.admission.json`，采用临时文件原子替换。零准入时**先写审计，再明确抛异常**；若输出CSV之前存在，不读取或复用它，也不删除用户旧文件。
4. 正式模式只接纳质量契约通过、同一明确`criteria_id`、输入完整的样本；仅`status=completed`不足以准入。
5. 正式导出明确包含`eligible_for_fragility`和`limit_state_reached`。已验证的`False`事件是有效非事件，不能被真值判断过滤。未知事件保持空值，不自动变False。
6. 层间位移角提取不把`time/step`等元数据列当响应；严格拒绝非有限数据，不能靠`nanmax`忽略坏点。
7. 可用`expected_samples`补充尚无目录的预期运行，使缺失运行也进入流转分母；不提供时报告明确提示“只扫描已存在目录不证明预定队列完整”。
8. 显式`exploratory_legacy`保留原历史演示能力，并区分两类：
   - `exploratory_legacy_only`：没有新质量信息的历史有限响应；
   - `exploratory_unvalidated_only`：新schema完整、计算完成、尚未验证、无已知局部失败/越界的诊断响应。
   两者均保留实际质量和未知物理状态，`eligible_for_fragility=false`。已知越界、局部失配、损坏schema不能通过探索分支被提升。
9. `main(argv=None)`改为CLI，默认formal。没有已冻结判据ID时解释原因并保留审计；formal拒绝临时手填/分位数阈值作为物理判据。
10. 当前formal主入口只导出准入表和证据支持的队列事件计数，**不自动拟合旧阈值概率曲线**。真实物理阈值映射、统计方案和未知样本机制仍属T22后续工作。
11. 旧拟合功能保留在显式探索模式，必须再显式选择`--manual-thresholds`或`--auto-thresholds`；输出文件名带`_exploratory`，控制台明确“仅探索性演示”。不覆盖仓库原`input_wind_drift.csv`等历史导出表。

调用形态：

```python
df = extract_input_from_opensees(
    output_root, new_csv,
    reference_type="drift",
    criteria_id="真实证据中已经冻结的判据ID",
    expected_samples=[
        {"sample_id": "sample_01", "wind_speed": 20},
        {"sample_id": "sample_02", "wind_speed": 20},
    ],
)
```

CLI示例（示例路径须换成真实的新结果目录；当前旧原始输出根目录缺失，不会自动补造）：

```bash
.venv/bin/python -m fluctuate_wind_simulate.fragility_curve.main --help

# 正式：只导出准入表/完整流转；criteria-id必须和样本证据一致。
.venv/bin/python -m fluctuate_wind_simulate.fragility_curve.main \
  --output-root path/to/new_runs --output-dir path/to/new_admission \
  --reference-type drift --criteria-id physically_frozen_rule \
  --cohort-json path/to/declared_samples.json

# 明确的历史探索演示，不是正式阈值或正式概率结论。
.venv/bin/python -m fluctuate_wind_simulate.fragility_curve.main \
  --output-root path/to/existing_runs --output-dir path/to/exploratory_export \
  --reference-type drift --eligibility-mode exploratory_legacy \
  --manual-thresholds 0.001 0.0015 0.002
```

### 7.2 追加测试的实际命令与结果

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_fragility_admission.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_analysis_workflows.py' -v
```

| 追加测试 | 实际结果 | 关键验收 |
|---|---|---|
| 新实际入口测试 | 11/11通过；unittest报告2.261 s（启动另外受到资源调度等待） | formal拒legacy/越界/unvalidated，False事件保留，未知/缺失样本留分母，审计先落盘，未验证探索分支不升级，正式主入口不做未冻结阈值拟合 |
| 原工作流回归 | 5/5通过；385.171 s | 原演示显式探索后仍只选1/2，失败样本完整留审计；其余原工作流通过 |

较长工作流耗时发生在主agent全塔运行、后处理和其他测试并行的资源竞争期间，不能用作模型性能结论。
主agent要求停止重复回归后，本agent核对疑似PID时它已自然结束；session实际返回5/5和exit_code=0，不是把中断冒充通过。
此后不再启动并行公共回归，最终全仓库串行集成测试由主agent统一执行。

第4节的61项是之前独立模块阶段结果；第7节明确区分本次入口接入后的11项新测与5项原工作流复核，不能把历史结果当成最终全仓库测试总数。

### 7.3 尚未完成

入口已经强制正式模式拒绝无证据结果，但没有产生任何新的正式研究样本，也没有完成真实物理判据、动力适用性、统计拟合或置信区间。
正式研究仍须冻结完整队列并审查样本来源；`expected_samples`是补全缺失记录的接口，不是程序自动证明研究设计充分。
本追加工作只关闭“实际提取函数默认接受旧completed/无清单样本”的软件漏洞，T22保持工程前置完成、物理/统计任务未完成。
