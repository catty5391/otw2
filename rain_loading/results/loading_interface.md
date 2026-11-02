# 通用节点荷载接口：风、雨与组合荷载

原接口 `apply_nodal_wind_loads` 已能施加六分量节点力，但一组节点只能共用一个标量时程；名称和限制容易让人误以为风、雨需要不同的 OpenSees 加载器。本次把节点荷载安装独立到 `nodal_loads.py`，旧风入口作为兼容包装继续可用。

## 1. 能加什么

|输入|入口|单位与说明|
|---|---|---|
|固定空间分布，静力递增或恒定|`apply_nodal_loads`|`Linear` 或 `Constant`，节点力 N、节点力矩 N·m|
|固定空间分布乘一个标量时程|`apply_nodal_loads(..., time_series_type="Path")`|`path_values` 是无量纲系数；`dt` 或 `times` 二选一|
|每个节点、方向各自变化的力时程|`apply_nodal_load_history`|`{node: [time][dof]}`，数组内直接为 N / N·m，无需用户再归一化|
|风与雨具有不同时间规律|分别调用并保留各自返回对象|引擎在同一全局时间下叠加；雨力保留竖向分量和力矩|
|查询当前已施加的合力账本|`current_nodal_loads(wind, rain, ops_module=ops)`|读取引擎当前荷载系数，兼容 `loadConst` 后冻结状态|
|移除某一类荷载|`remove_nodal_loads(rain, ops)`|仅移除该调用创建的模式/时程，不移除风、重力|

**接口接收已经换算好的节点力，不能直接输入风速 m/s、雨强 mm/h、压力 Pa 或杆上荷载 N/m。** 这些量先由相应物理模块转换和映射。本接口也不修改材料、质量、阻尼、求解器或边界。

三维框架顺序为 `[Fx,Fy,Fz,Mx,My,Mz]`；三维桁架可以是三个平动分量；二维框架通常为 `[Fx,Fy,Mz]`。接口按模型节点实际自由度数校验，不会自行把第三自由度判断为竖向力或弯矩。节点号必须是正整数，数值须有限。

## 2. 静风与雨滴冲击叠加

```python
from util.processing.nodal_loads import (
    apply_nodal_loads, current_nodal_loads, remove_nodal_loads,
)

# 先完成重力平衡，再由分析流程明确冻结已有荷载并重置伪时间。
ops.loadConst("-time", 0.0)

# wind_forces、rain_forces 都是 {node: [Fx,Fy,Fz,Mx,My,Mz]}，单位 N / N·m。
# 两者共用模型的 TagManager。以下两组一起随静力因子从 0 增至 1。
wind = apply_nodal_loads(wind_forces, model.tag_manager, ops, name="wind")
rain = apply_nodal_loads(rain_forces, model.tag_manager, ops, name="rain")

# 配置静力分析并 analyze() 后，再取实际荷载；账本不自动包含重力。
external_weather = current_nodal_loads(wind, rain, ops_module=ops)
```

`Linear` 要求当前伪时间为 0，防止刚添加荷载就隐含乘上已有时间。需要先加风再加雨时，先完成风平衡，再显式 `loadConst("-time",0)`，最后仅新建雨模式。本轮 `rain_loading/tower_check.py` 已改用这一通用入口与实际荷载账本，原数值未变。

## 3. 非比例风雨时程

```python
from util.processing.nodal_loads import apply_nodal_load_history

# 示例节点应已存在。第一个采样点对应 start_time；默认从当前模型时间开始。
wind = apply_nodal_load_history(
    {350: [[0,0,0,0,0,0], [100,20,0,0,0,0], [60,40,0,0,0,0]]},
    model.tag_manager, ops, name="wind", dt=0.1, hold_last=True,
)
rain = apply_nodal_load_history(
    {350: [[0,0,0,0,0,0], [0.6,0.1,-1.8,0,0,0], [1.2,0.3,-2.4,0,0,0]]},
    model.tag_manager, ops, name="rain", dt=0.1, hold_last=True,
)
# 随后配置并执行 Transient；不能再调用 loadConst，否则风雨时程也会被冻结。
```

荷载输入采用同一时间网格，每个节点都必须给足所有采样点和自由度。`times=[0,0.1,0.35,...]` 可替代 `dt`，表示相对 `start_time` 的偏移；不能同时传两者。不同物理场如果采样不同，允许分别建立时程并由引擎在各自采样点之间线性插值，但是否需要统一带宽、时间分辨率和观测窗口由上层物理模型负责，接口不自动补点或改谱。

默认要求 Path 的第一点为零，避免在初始状态未平衡时突然出现荷载。已有均风预加载时，建议把均值施加并平衡，只将增量传给时程；若确实另行处理了初始平衡/初始加速度，可以显式 `allow_nonzero_initial=True`。旧风包装和旧分层风文件入口保留历史首值处理方式，避免改变既有算例。

`hold_last=False` 表示超过记录后归零；`True` 表示保持末值。若要平滑卸载，应显式给卸载段，不能把“记录结束归零”解释为自然风雨过程。瞬态求解步长与荷载采样间隔不是同一个概念。

## 4. 本次发现并处理的引擎边界

在当前 OpenSees **3.8.0** 中实测，显式 `-time/-values` 路径可能忽略 `-useLast`。官方源码的 `OPS_PathSeries` 对这一构造分支没有传递 `useLast` 参数。只看文档或模拟工具调用无法发现这个差异。

接口对非等间隔、保持非零末值的情况采用精确分解：

`f(t) = [f(t) − f_last] + f_last · step(t − t_start)`。

第一部分用原时间点，末点为零；第二部分用受支持的等间隔常值 Path 并保持末值。两者在起点相消，在所有采样点和插值区间保持原函数，末点以后保持末值。没有重采样、增添虚构过渡段或使用极大哨兵时间。

这类返回对象可能持有两个底层模式：应使用 `receipt.pattern_tags`、`receipt.time_series_tags` 和 `current_nodal_loads`。单个 `.pattern_tag` / `.time_series_tag` 仅为旧调用保留，不能用其中一个系数代表组合后的完整时程。普通 `Linear`、`Constant` 和等间隔 `Path` 仍只有一个模式。

- [OpenSees Path 文档](https://openseespydoc.readthedocs.io/en/latest/src/pathTs.html)
- [官方 PathSeries 解析源码](https://github.com/OpenSees/OpenSees/blob/master/SRC/domain/pattern/PathSeries.cpp)
- [loadConst 的作用范围](https://openseespydoc.readthedocs.io/en/latest/src/loadConst.html)

## 5. 安装、叠加与生命周期

- 所有输入、时间和自由度先校验，再创建引擎对象；施加中途失败时撤销本次创建的完整分组。
- 一次创建的不同节点/方向只有在归一化时程完全相同时才共享模式；不做近似拟合。默认最多创建10000个模式，超限在施加前拒绝，不会截掉部分荷载。
- 全零雨荷载时程合法，返回空模式组，可查询为零，不创建无用时程。
- 必须共用同一标签管理器，或先登记已有标签。OpenSees 暴露模式编号但没有列出全部 timeSeries 的公共接口；遇到已有时程冲突，只报错，不删除别人的时程。
- 每次 `apply_*` 都表示新增荷载，不是按名称替换；名称只是来源标签。调用方要避免重复添加同一物理荷载。账本对同一返回对象重复计入会报错。
- 在 `analyze()` 后查询账本；`setTime()` 本身不会刷新引擎荷载因子。用 `loadConst` 冻结后，账本读取实际冻结系数，不按新时间错误重算。
- 对象只属于创建时的模型域，不可在 `wipe()`、重建并重用标签后继续使用。OpenSees 计算仍需进程隔离，不能把多个模型放在不同线程同时调用全局引擎。

## 6. 本次接入范围与验证

已接入旧方向风荷载包装、旧分层风荷载文件入口，以及雨影响全塔算例。旧重力和归一化推覆辅助器继续负责各自的物理量生成，不把它们改成雨强输入接口。

测试覆盖静力风雨与力矩叠加、三/六自由度、不同节点时程、不等间隔/非零起始时刻、末值保持、零雨、失败回滚、标签冲突与选择性移除。真实瞬态验证使用已知质量/刚度/阻尼的弹簧，与分段线性外力的矩阵指数精确解比较，并检查动力平衡、叠加与步长收敛。另复算既有0°四分段Steel02全塔，核对接口替换前后位移和支反力。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m unittest \
  tests.test_nodal_loads tests.test_directional_wind tests.test_directional_integration \
  tests.test_wind_model_isolation tests.test_analysis_workflows -v
.venv/bin/python -m scripts.verify_nodal_load_interface
```

**通用节点加载并未自动解决梁一致荷载、杆内分布荷载、跟随力、相对运动气动反馈或湿态系数标定。** 雨研究此前“原始物理杆两端集中”的映射假设仍然成立；若要研究局部杆件弯矩，需要上游另建分段/一致荷载映射，不能由本接口的通用性推导出局部应力已准确。

## 本轮实际运行结果

- 通过：通用接口：风雨时程叠加与零雨回归。叠加误差 1.25e-16 m；零雨回归 0 m。
- 通过：通用接口：实际荷载与动力平衡。账本最大误差 2.13e-13 N；动力残差 3.47e-15 N。
- 通过：通用接口：独立精确解与步长收敛。最细步长相对误差 0.00033；细/粗误差比 0.0625。
- 通过：通用接口：实际Steel02全塔回归。位移差 0 mm；反力差 0 N。

完整记录见 `loading_interface_verification.json`；动态图来自已知弹簧验证模型，不是全塔风雨动力响应。
