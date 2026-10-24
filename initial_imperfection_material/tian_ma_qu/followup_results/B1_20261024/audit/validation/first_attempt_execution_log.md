# N00/N01 执行日志

- 首次快照：2026-10-23T16:47:03.055517+00:00，68文件匹配=True。
- 审计完成：2026-10-23T16:53:29.753632+00:00。
- 命令：`OPENBLAS_NUM_THREADS=1 .venv/bin/python -m initial_imperfection_material.tian_ma_qu.diagnostic_audit --output initial_imperfection_material/tian_ma_qu/followup_results/B1_20261024/audit --expected-source-change initial_imperfection_material/tian_ma_qu/publish_modal.py`
- 新FE：0；现有模态工况4；静风重力初态对照13。
- 身份/初态检查：True；基线审计：False。
- 测试命令与实际日志见 validation/；不把脚本内部审计计数当作单元测试数。
