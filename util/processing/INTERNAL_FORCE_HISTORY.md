# 全塔内力时程记录

`TowerInternalForceRecorder` 在每个分析步读取所有塔身梁柱单元的局部端力，并保存为带索引的
SQLite 数据库。绝缘子和输电线单元默认排除。

记录的 12 个分量依次为：

```text
I 端: P, Vy, Vz, T, My, Mz
J 端: P, Vy, Vz, T, My, Mz
```

力的单位为 N，弯矩和扭矩单位为 N·m，正负号遵循 OpenSees 单元局部坐标系。

## 在分析循环中记录

```python
from util import TowerInternalForceRecorder

recorder = TowerInternalForceRecorder(
    model,
    "tower_internal_forces.sqlite",
    overwrite=True,
)
recorder.capture(step=0)  # 初始状态

for step in range(nsteps):
    ok = model.ops.analyze(1, dt)
    if ok != 0:
        raise RuntimeError("analysis failed")
    recorder.capture(step=step + 1)

history = recorder.close()
```

已有的脉动风批处理 `wind_refactor_common.py` 已接入该记录器，每个样本都会生成
`tower_internal_forces.sqlite`。

## 查询任意时间段

```python
from util import TowerInternalForceHistory

history = TowerInternalForceHistory("tower_internal_forces.sqlite")

# 2~8 s 的全部塔身单元内力
rows = history.iter_history(start_time=2.0, end_time=8.0)
history.export_history_csv("forces_2_8s.csv", start_time=2.0, end_time=8.0)

# 距离 5.25 s 最近的记录时刻，全塔内力空间分布
snapshot = history.snapshot(5.25)
history.export_snapshot_csv("forces_at_5_25s.csv", 5.25)

# 2~8 s 内每根杆件各内力分量的绝对值包络
envelope = history.envelope(start_time=2.0, end_time=8.0)
history.export_envelope_csv("force_envelope_2_8s.csv", start_time=2.0, end_time=8.0)
```

也可通过 `element_tags=[...]` 或 `tower_ids=["tower_1"]` 缩小查询范围。长时程数据量较大时，
可在记录器中设置 `record_every=5`，表示每 5 个分析步保存一次。

不写 Python 代码也可以直接导出，例如：

```bash
# 5.25 s 最近记录时刻的全塔空间分布
.venv/bin/python -m util.processing.internal_force_recorder \
  tower_internal_forces.sqlite forces_at_5_25s.csv --mode snapshot --time 5.25

# 2~8 s 的各杆件内力包络
.venv/bin/python -m util.processing.internal_force_recorder \
  tower_internal_forces.sqlite envelope_2_8s.csv --mode envelope --start 2 --end 8
```
