# 等效初始缺陷材料：单杆试验模块

本目录是一个与全塔模型隔离的实验区，用单根 `L125x8Q345` 角钢验证“等效杆件屈曲本构”能否替代当前四分段几何初弯曲模型。

运行默认试验：

```bash
uv run python -m initial_imperfection_material.run_experiment
```

改变杆长、初弯曲和结果目录：

```bash
uv run python -m initial_imperfection_material.run_experiment \
  --length 3.0 \
  --imperfection-ratio 0.001 \
  --steps 400 \
  --output /tmp/imperfection-result
```

输出包括推覆曲线、归一化曲线、材料骨架、缺陷敏感性 PNG，全部曲线 CSV 和汇总 JSON。理论、实现方法、首轮结果及使用边界见 [REPORT.md](REPORT.md)。

注意：一个等效材料实例只对应一根具有确定 `L、K、A、I、fy` 的原始物理杆件。应用该材料时不得再次给同一杆件施加几何初弯曲，也不得把原杆分段后按每段长度重复计算材料。
