# N00/N01 执行日志

- 首次快照：2026-10-23T16:47:03.055517+00:00，68文件匹配=True。
- 审计完成：2026-10-23T17:00:46.870974+00:00。
- 命令：`OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.diagnostic_audit --output initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/audit --expected-source-change initial_imperfection_material/tian_ma_qu/publish_modal.py --expected-source-change initial_imperfection_material/tian_ma_qu/modal_viewer.html`
- 新FE：0；现有模态工况4；静风重力初态对照13。
- 身份/初态检查：True；基线审计：True。
- 测试命令与实际日志见 validation/；不把脚本内部审计计数当作单元测试数。

- 第一次审计exit=1：模型身份通过，模板变化未声明；保留首次失败。
- 第二次审计exit=0：仅显式允许两项N05展示层变化。
- 最终审计exit=0：补充实际引擎/桥/源码哈希核对后通过；最终执行命令/输出见validation/audit_final_execution.json和audit_final_stdout.log。
- 最终测试13 passed, 0 skipped；原始stdout/stderr见validation/tests_final.log。
- 所有步骤新FE均为0；物理验证仍为unvalidated。

- 最终发布器指纹刷新：2026-10-23T17:02:49.515408+00:00。重新核对68个基线文件以及evidence_index全部输入；仅更新已明确允许的publish_modal.py/modal_viewer.html当前指纹，初始快照、失败及中间成功记录保留。未重跑13项测试，无FE。此前基线检查保存至validation/baseline_before_final_publisher_refresh.json。
