# N05 发布器的独立只读审查

审查者：`/root/b1_model_audit`。范围为 `publish_modal.py` 的版本化 manifest 解析和新目录发布流程，以及 `modal_viewer.html` 模板身份。本次只读源码并刷新审计指纹，没有运行发布、编译、有限元或重复测试。

## 结论

在**显式传入 manifest、采用不存在的新输出目录**的调用方式下，未发现会改写旧模态输入文件的路径：

1. `publication_config()` 校验版本、唯一工况标识、工程内已存在的输入目录，以及工况已完成且检查通过；只读取输入。
2. `publish()` 的 manifest 分支拒绝已存在的输出目录；先检查所有工况所需文件，再建立新目录并复制。
3. 后续 `viewer_data.json`、汇总、图片和HTML写入新输出根目录及其复制的 `runs/`，不写原始 `row['source']`。
4. 汇总保存发布器及模板指纹，能够区别“物理结果未改变”和“显示模板改变”。

此前发现最低允许5阶，但网格比较使用前6阶；最终版本已提高为至少6个有限正频率，修复了这一输入边界不一致。

无manifest的legacy分支仍保留原有原地发布方式。本批应始终使用manifest与新目录；不能把新分支的保护条件泛化为所有旧调用方式。此审查不代替主agent随后执行的发布回归和浏览器检查，也不增加力学或物理验证结论。

## 最终指纹与证据检查

- `publish_modal.py`：`5f5c0a1c2990a6cf0fa0bf3e3c6990e720fdbea13f1324b883a5624a5c135794`
- `modal_viewer.html`：`32e3a71b5ac23641eb1a66b5b7deeaa2aed948d3b66ef1ffd0799aa6ecd0e136`

最终刷新重新核对68个计划基线文件及147项实际输入索引。首次快照保留，只有上述两个明确声明的发布层文件相对初始基线变化；其余选定旧结果、历史任务和物理源码没有变化。刷新前基线记录另存 `validation/baseline_before_final_publisher_refresh.json`。

本轮刷新没有重跑已通过的13项测试；原始测试日志和结果仍保留。最终当前指纹见 `baseline_check.json`、`evidence_index.csv` 与 `verification.json`。
