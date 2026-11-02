# 四分段初始缺陷：空间单杆验证

日期：2026-10-29。延续文献审计，将实际杆件的长度分段、截面网格、缺陷方向和幅值分别检查。网页入口：[9999 独立模块](http://localhost:9999/segmented-validation/)。

## 完成内容

- 真实杆件349（L125×8Q345，1.602 m）、920（L40×3Q235，1.950 m）、292（L200×16Q420，1.403 m）。349保留为此前对照；另两杆来自已完成单塔风荷载工况中同钢级的压缩需求排名，依据和原文件哈希保存在 `results/convergence/plan.json`。
- **36个离散与往复工况**：固定17纤维比较4/8/16/32段；固定16段比较17/68/272纤维；步长减半；小幅弹性卸载；±0.5、1、2、4倍屈服应变的有序往复，每档两次。
- **27个方向与幅值工况**：固定16段和272纤维，比较弱轴弯曲正反方向、seed30103原随机方向，以及L/2000、L/1000、L/500。
- 全部63工况到达目标。两次Newton失败尝试分别出现在349号方向试验和920号往复试验，均由NewtonLineSearch恢复，没有放宽1e-5残差容限。
- 5组PNG/SVG/PDF图、完整中文报告、工况汇总、有序曲线CSV和原始迭代记录。

## 对当前模型的修正

`model/steel02_parameters.py` 统一完整Steel02定义，原 `model.mechanical_profile` 继续导出同一类型，兼容既有调用。全塔注册材料与本次单杆均使用 `Steel02Parameters.legacy_tower`；全塔原材料数值保留，材料CSV增加完整参数并支持读取。

`OpenSeesModelWithBuckling` 默认缺陷改为 **L/1000**。需要重现历史L/100时显式传 `random_disp_ratio=.01`。旧推覆幅值扫描固定 `imperfection_seed=30103`，各幅值沿用同一组方向。现有显式L/1000的近期风荷载算例输入未改变，历史计算结果未覆盖。

本次没有将全塔改成弱轴方向，也没有把全塔一律加密到16段或改变截面纤维默认值；这些取舍应结合实际端部约束回放和成本再决定。

## 关键结果

|杆件|4段相对32段|16段相对32段|固定16段，17纤维相对272纤维|
|---|---:|---:|---:|
|349|+2.175%|+0.193%|−0.770%|
|920|+5.078%|+0.238%|−1.694%|
|292|+0.558%|+0.025%|−0.124%|

这里比较的是单调最大采样压力；本组均有内部峰值和下降支。长度网格和截面网格分别改变，误差不能直接相加。32段及272纤维是数值参照，并非实测真值，也没有进行每个细截面上的32段联合极限收敛证明。

L/1000时，当前随机方向相对弱轴正方向的最大压力差分别为 **+0.636%、+0.923%、+0.110%**。幅值敏感性更明显，但结论只适用于三根试件及所抽方向，不能认定全塔最不利缺陷。

建议保留四段作为初筛，对关键压杆使用16段并细化截面复核，然后利用全塔实际六自由度端部历史检查。920号铰接单杆的压力上限不能直接与全塔轴力相比就宣布失稳。

## 复现步骤

每个求解过程独占OpenSees域，禁止在同一Python进程中用线程同时建模。运行默认目录已存在时会拒绝覆盖证据。复算请使用新的输出目录，例如：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.segmented_member_validation.experiment --output /tmp/otw2-member-recheck/convergence
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.segmented_member_validation.direction_study --output /tmp/otw2-member-recheck/direction
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.segmented_member_validation.publication --output /tmp/otw2-member-recheck
```

第一项读取近期完整风荷载结果以复核选杆依据；若原数据不在本机，会报错而不自动另选试件。图表发布只读取已有结果，不运行有限元。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m unittest tests.test_tower_steel02_contract tests.test_segmented_member_validation tests.test_imperfection_direction_study tests.test_segmented_validation_dashboard -v
```

## 边界和文件

采用既有 `MechanicalCatalog`、`build_member_reference`：Steel02、Corotational、dispBeamColumn、6点Legendre，三维两端铰接，一端固定扭转刚体运动。它是独立单杆试验，**不是全塔六自由度端部历史回放**。

钢材参数是项目假定，缺陷不是实测值。截面沿用当前模型逐段全局辅助轴的朝向规则；弱轴位移方向与弱弯矩轴垂直。该规则的参考绕轴角变化已记录，但实际安装角、局部屈曲、翘曲、连接滑移和断裂仍未验证。

- `results/REPORT.md`、`summary.json`：报告、汇总与发布时源码快照。
- `results/case_summary.csv`、`histories.csv`：全部工况和按时间顺序保存的曲线。
- `results/convergence/`：网格、截面、弹性与往复原始记录、执行代码哈希、独立核验。
- `results/direction/`：方向矩阵、几何核对、幅值试验与独立核验。此批运行前未冻结Python源码副本；发布时哈希不冒称执行时哈希，后处理峰后指标保存了原记录哈希。
- [文献审计](../../literature/opensees_segmented_steel02_20261028/README.md)：来源及原文阅读范围。

原始数据只保存在本地；本轮未执行git提交或推送。

## 集成验收

63项针对性测试通过，包含共享材料兼容、已有力学/标定回归、新单杆与方向验证、HTTP访问与中文编码。独立检查29601行有序历史；发布源码哈希与当前文件一致。桌面1440px、手机390px检查通过，5幅图与24个页面/资源链接可用，目录进入与返回正常。证据见 `results/verification.json` 和 `py_view/.output/segmented_validation_20261029/`。这些是数值及软件检查，不替代物理验证。
