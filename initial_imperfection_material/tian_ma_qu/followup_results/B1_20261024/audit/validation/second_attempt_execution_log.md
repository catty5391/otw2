# N00/N01 执行日志

- 首次快照：2026-10-23T16:47:03.055517+00:00，68文件匹配=True。
- 审计完成：2026-10-23T16:56:03.656782+00:00。
- 命令：`OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.diagnostic_audit --output initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/audit --expected-source-change initial_imperfection_material/tian_ma_qu/publish_modal.py --expected-source-change initial_imperfection_material/tian_ma_qu/modal_viewer.html`
- 新FE：0；现有模态工况4；静风重力初态对照13。
- 身份/初态检查：True；基线审计：True。
- 测试命令与实际日志见 validation/；不把脚本内部审计计数当作单元测试数。

- 第一次审计exit=1：身份检查通过，但模板变更未声明，保留首次失败记录。
- 第二次审计exit=0：显式声明两项N05展示层修改后，全部身份和证据检查通过。
- 单元/保存证据测试：12 passed, 0 skipped；命令与原始输出见`validation/tests.log`。
- 物理验证状态仍为unvalidated。
