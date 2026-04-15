# OpenSeesPy 常用查询命令速查

这份清单重点放在：
- 节点信息（坐标、位移、速度、加速度、反力）
- 杆件/单元信息（连接节点、内力、变形、响应）
- 分析过程中实时读取结果

> 建议统一写法：
>
> ```python
> import openseespy.opensees as ops
> ```

## 1. 节点相关命令

### 1.1 获取节点标签

```python
node_tags = ops.getNodeTags()
```

### 1.2 获取节点坐标

```python
xyz = ops.nodeCoord(nodeTag)      # 返回该节点全部坐标，如 [x, y, z]
x = ops.nodeCoord(nodeTag, 1)     # 取第1个坐标分量
```

### 1.3 获取节点位移/速度/加速度

```python
disp_all = ops.nodeDisp(nodeTag)      # 全部自由度位移
ux = ops.nodeDisp(nodeTag, 1)         # 第1自由度位移

vel_all = ops.nodeVel(nodeTag)
acc_all = ops.nodeAccel(nodeTag)
```

### 1.4 获取节点反力（常见易错点）

先更新反力，再读取：

```python
ops.reactions()                        # 先调用
r_all = ops.nodeReaction(nodeTag)      # 全部反力
rx = ops.nodeReaction(nodeTag, 1)      # 第1自由度反力
```

### 1.5 获取不平衡力（残余力）

```python
ub = ops.nodeUnbalance(nodeTag)
```

## 2. 杆件/单元相关命令

### 2.1 获取单元标签和连接节点

```python
ele_tags = ops.getEleTags()
conn = ops.eleNodes(eleTag)           # 返回该单元的节点连接
```

### 2.2 获取单元力与变形（常用）

```python
f = ops.eleForce(eleTag)              # 单元力向量（与单元类型相关）
q = ops.basicForce(eleTag)            # 单元基本力（梁柱常用）
v = ops.basicDeformation(eleTag)      # 单元基本变形
```

### 2.3 通用响应接口（最灵活）

```python
resp = ops.eleResponse(eleTag, 'globalForce')
resp2 = ops.eleResponse(eleTag, 'localForce')
```

不同单元支持的关键词不同，常见还有：
- `'force'` / `'forces'`
- `'stiffness'`
- `'section', secTag, ...`（纤维/截面相关单元）

如果返回空列表，通常是关键词不匹配该单元类型。

## 3. 分析过程中实时读取（最常用模板）

```python
import openseespy.opensees as ops

ok = 0
n_steps = 200
for i in range(n_steps):
    ok = ops.analyze(1, 0.01)   # 瞬态时程：一步一步算
    if ok != 0:
        print(f'分析在第 {i+1} 步失败')
        break

    t = ops.getTime()

    # 节点响应
    u_top = ops.nodeDisp(101, 1)      # 例：节点101, UX

    # 单元响应
    f_col = ops.eleForce(201)         # 例：单元201

    # 反力（需要先 reactions）
    ops.reactions()
    r_base = ops.nodeReaction(1, 1)

    print(t, u_top, f_col[0], r_base)
```

## 4. 用 recorder 持续输出到文件（推荐）

大模型建议优先 recorder，避免每步 Python 循环频繁调用查询导致效率下降。

### 4.1 节点位移

```python
ops.recorder('Node', '-file', 'node_disp.out', '-time',
             '-node', 101, 102, '-dof', 1, 2, 3, 'disp')
```

### 4.2 节点反力

```python
ops.recorder('Node', '-file', 'node_reaction.out', '-time',
             '-node', 1, 2, 3, '-dof', 1, 2, 3, 'reaction')
```

### 4.3 单元力

```python
ops.recorder('Element', '-file', 'ele_force.out', '-time',
             '-ele', 201, 202, 'globalForce')
```

## 5. 常见问题

1. 反力全是 0：
先调用 `ops.reactions()` 再读 `ops.nodeReaction(...)`。

2. `eleResponse` 没结果：
响应关键词与单元类型不匹配，需看该单元支持的 response 类型。

3. 分析过程中读取很慢：
优先用 `recorder` 写文件，后处理时读取文件。

## 6. 额外实用命令

```python
t = ops.getTime()
lf = ops.getLoadFactor(patternTag)
ops.wipeAnalysis()   # 清理分析器设置（不清空模型）
ops.wipe()           # 清空整个模型
```

---
如果你愿意，我可以下一步按你现在的模型脚本（例如 `opensees_simulate/main_record_stressStrain_by_fiberLoaction.py`）直接插入一段“分析中实时提取关键节点位移+底部反力+关键杆件内力”的模板代码。