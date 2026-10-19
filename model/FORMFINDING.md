# 输电线目标弧垂找形

`TowerLineSystemModel.build()` 会在正式建立塔—线耦合模型前读取每条导线的
`formfinding` 配置。启用后，程序先根据实际绝缘子挂点得到水平档距和高差，再建立隔离的
OpenSees 导线模型，通过二分法改变初始轴力，使自重平衡后的最大弧垂达到目标值。

```json
"formfinding": {
  "enabled": true,
  "target_sag": 8.0,
  "force_lower": 40.0,
  "force_upper": 80000.0,
  "tolerance": 0.001,
  "max_iterations": 30,
  "load_steps": 100
}
```

- `target_sag`：相对两挂点弦线的最大竖向弧垂，单位 m。
- `force_lower/force_upper`：二分搜索的初始轴力边界，单位 N；低轴力对应较大弧垂。
- `tolerance`：弧垂收敛容差，单位 m。
- `initial_sag`：在导线主配置中定义，是每次迭代采用的几何初值。

找到的轴力只写入当前内存中的建模配置，不改写原 JSON。结果保存在：

- `formfinding_summary.csv`：每条导线的目标弧垂、平衡弧垂、初始轴力和迭代次数；
- `formfinding_history.csv`：完整二分迭代过程；
- `formfinding_shape.csv`：平衡后的导线局部竖平面坐标，其中 `span_x` 沿档距方向；
- `formfinding_axial_forces.csv`：平衡后的逐段轴力分布；
- `result["formfinding"]`：供后续程序直接读取的结果。

当前 Z30103A6 示例在 `JL/G1A-400/50` 单根子导线、300 m 档距和 8 m 目标弧垂下，
平衡初始轴力约为 20.9 kN。该值会随挂点、导线质量、`EA`、档距和目标弧垂自动重算。

当前找形采用固定挂点边界，与输电线弧垂—张力计算的常用处理一致。求得的平衡初始力随后进入正式
塔—绝缘子—线耦合模型；柔性塔架在风荷载下的附加变形由后续整体分析计算。
