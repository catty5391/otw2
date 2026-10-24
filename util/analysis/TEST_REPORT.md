# 通用分析模块测试记录

本记录对应本轮新增的公共模块和入口接入。测试运行使用项目 `.venv`，没有重新生成或覆盖单杆及全塔正式对比结果。

## 自动化测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

结果：**53/53 通过**。其中原有项目测试 24 项，本轮新增 29 项。测试文件为：

- `tests/test_analysis_common.py`：24 项，覆盖循环协议、时序校验、响应指标、自适应求解、状态文件与异常边界。
- `tests/test_analysis_workflows.py`：5 项，覆盖实际 OpenSees 静力/瞬态解析验证、风振入口正常/失败流程、易损性样本状态过滤。

重点检查结果：

| 项目 | 验收内容 | 结果 |
|---|---|---|
| 循环加载 | 重复次数、负向起步、最终回零、剩余步长不越界 | 通过 |
| 风荷载输入 | 非均匀时间、NaN、错误列数、荷载长度不一致、重复或未知节点 | 均按预期拒绝 |
| 自适应求解 | 回退保持同一容差、缩步后补足区间、失败保留真实终点 | 通过 |
| 状态一致性 | 返回失败但状态前进时停止重试 | 通过 |
| 曲线比较 | 两端共同区间、无外推、采样加密不改变积分 RMSE | 通过 |
| 路径外功 | 弹性往返净外功约为零，闭合矩形回线面积正确 | 通过 |
| 运行清单 | 原子写入、目录互斥、异常传播、缺少输入不保留旧成功状态 | 通过 |
| 覆盖率 | 已完成步数不足预期时标记未完成 | 通过 |
| 风振记录 | 3 个原始时间间隔各分成两个子步，产生 6 行位移角和含初始态的 7 个内力时刻 | 通过 |
| 失败清理 | 风振求解失败后清单保存错误、运行锁释放、数据库可独占访问 | 通过 |
| 下游样本 | 未收敛样本即使存在大幅值输出，也不会混入新的易损性数据 | 通过 |

## 当前项目全部风荷载样本预检查

运行：

```bash
.venv/bin/python -m util.analysis check-wind \
  fluctuate_wind_simulate/static/wind_press_generate \
  --node-config fluctuate_wind_simulate/.config/node_to_add_wind_press.json \
  --output /tmp/otw2-wind-preflight.json
```

结果：发现 **70** 组样本，**70 组通过、0 组无效**。此项检查验证时间与荷载数据的格式、长度及配置，不代表重新验证了风场的统计特性。

## 解析示例

运行 `.venv/bin/python -m util.analysis.demo`，输出在 `util/analysis/.output/demo/`：

| 指标 | 实际结果 |
|---|---:|
| 静力弹簧最大力误差 | 0 N |
| 弹性往返路径外功 | −2.17×10⁻¹⁸ J |
| 瞬态最大位移误差 | 7.58×10⁻⁸ m |
| 瞬态计算终点 | 0.2 s |
| 静力成功步数 | 42 |
| 瞬态成功步数 | 200 |

静力参照 `F=200u`；瞬态参照 `u(t)=(1−cos(10t))/200`，使用一致的初始加速度。输出包含 `static.csv`、`transient.csv`、`verification.png`、`summary.json` 和 `run_manifest.json`。

## 真实全塔入口检查

使用 Z30103A6、四分段参考模型、L/1000 初始缺陷，单独在临时目录运行：

```python
run_tower_cyclic(
    "segmented_reference",
    output_root=temporary_output,
    target_drift_ratios=(0.00001, -0.00001, 0.0),
    maximum_increment=0.00025,
    minimum_increment=0.00003125,
)
```

结果：3/3 个目标完成，7 个成功分析步，7 次求解尝试，未触发失败回退；最终相对位移为 `6.56e-21 m`，清单状态为 `completed`。本次运行约 205.9 秒，主要用于验证公共模块已能通过真实模型入口。

该小幅工况只证明入口、记录及状态流程可用。本轮没有重新计算正式 ±1% 全塔对比，因此不改变此前等效材料模型的已知大变形收敛边界。
