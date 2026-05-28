# 易损性分析流程

## 此分支进行易损性分析


### 1.考虑屈曲的输电塔建模

将杆件一分为4，并在中点处添加初始位移，建模如下

<img src="/home/panqiheng/otw2/static/2026_05_27/image.png" width=500>

<img src="/home/panqiheng/otw2/static/2026_05_27/PixPin_2026-05-27_14-57-07.png" width=500>

### 2.不同初始缺陷下的推覆分析

初始缺陷取 1/1000杆长 的倍数 1/1000 * L , 2/1000*L, ...

结果如下

#### （1）顶点位移
<img src="/home/panqiheng/otw2/static/2026_05_27/70d94026-5c1c-41d7-88b4-5114d519db5f.png">

####  (2) ISDR
<img src="/home/panqiheng/otw2/static/2026_05_27/plot_reaction_drift.png">


### 2.输电线建模

使用聚合截面命令定义输电线截面，赋予其较大轴向刚度

```python
ops.uniaxialMaterial("Elastic", 1, EA)
ops.uniaxialMaterial("Elastic", 2,nonaxial_stiffness)
ops.uniaxialMaterial("Elastic", 3, nonaxial_stiffness)
ops.uniaxialMaterial("Elastic", 5, nonaxial_stiffness)
ops.uniaxialMaterial("InitStressMaterial", 4, 1, init_force)
ops.section("Aggregator", 1, 4, "P", 2, "Mz", 3, "My", 5, "T")

```

使用有限元找形法，确定输电线重力作用下的位形

1.首先需要确定找形目标，一般来说以输电线最低点弧垂或者最低点轴向应力为找形目标，我这里以弧垂为例进行找形，假定最终弧垂为8m

<img src="/home/panqiheng/otw2/static/2026_05_27/ecdd1f85-f0d3-47dc-9893-68480eb16608.png">

2.每次开始迭代的初始位形相同，改变的是初始应力的大小，经过7次迭代，最终最低点弧垂收敛到7.9995，结束迭代。

<img src="/home/panqiheng/otw2/static/2026_05_27/ae829b7d-85a1-4158-8ed9-5169b0aad105.png">

3.输电线模态分析
<img src="/home/panqiheng/otw2/static/2026_05_27/modes_3x2.png">