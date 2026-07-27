---
doc_kind: evidence
id: EV-011
title: RPA Region-Scoped Snapshot Evidence
status: active
feature_refs:
  - docs/features/F011-rpa-region-scoped-snapshot.md
created: 2026-05-19
updated: 2026-05-27
scope: RPA region-scoped snapshot capture, compression, selected-region extract splitting, bounded section text compilation, and action replay compile boundaries
---

# EV-011 RPA Region-Scoped Snapshot Evidence

## Current Review State

Active。PR #55 的 review blockers 已经被修掉，主线 region-scoped snapshot 能力也已合入；但 post-merge hardening 还在继续，尤其是 selected-region extract 的语义分层、shared anti-hardcode guard、section anchor 证据，以及 region-backed action/download replay 边界。本地验证已经覆盖这些补丁，但本次 closeout 没有重新观察最新远端 CI / review 结果，因此本 Evidence 和 `F011` 都不应写成 completed/Done。

## Evidence Targets And Follow-ups

- Completed: region-scoped text compile classification backend coverage proves that `region_text_extract.kind=heading_scoped_text` plus a reliable `section_anchor` uses deterministic `_extract_bounded_section_text`, while region-scoped free-text extraction without a reliable anchor preserves `_execute_runtime_ai_instruction` and does not embed recording-time selected text locators.
- Completed: guardrail coverage proves table, list, single-value, and action traces are not reclassified into runtime AI solely because `_looks_like_extract_instruction()` recognizes broad verbs such as `获取`, `读取`, `get`, or `read`.
- Added: generic manual fixture `/section-texts` in rpa-eval-app with non-GitHub section text DOM shapes: heading plus same-section body, after-context-only heading, and nested/complex container text.
- Added: harness decision that the current regression chain remains under `F011 / EV-011`, not a new Feature, because the bug is still the same selected-region evidence classification problem rather than a separate product capability.
- Completed locally: selected-region extract now carries explicit semantic lanes, `single_value_extract` and `anchored_region_extract`, with compiler compatibility for legacy signals.
- Completed locally: `heading_scoped_text` now shares the replay-safe anti-hardcode locator guard used by `selected_region_text_extract`, so observed extracted values, dynamic framework ids, and structural region headers do not enter deterministic replay.
- Completed locally: regression coverage proves fixing title single-value extraction does not break anchored region extraction, and fixing anchored region extraction does not reintroduce `get_by_text(observed_text)`.
- Pending: convert `/section-texts` into reproducible eval/recording evidence by adding a golden eval case or saving a manual region-selection recording/compile artifact with expected classification for each selected region.
- Follow-up: consider recording region compile classification in accepted trace or generated skill metadata, for example `compiled_structured`, `compiled_heading_scoped_text`, `runtime_ai_missing_anchor`, and `runtime_ai_semantic_selection`. This should be treated as verifiable trace/skill evidence, not ordinary debug logging.

## Commands

- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_record_heading_scoped_signal_from_observed_value_anchor RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_rejects_observed_text_driven_heading_locator RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_rejects_dynamic_framework_heading_locator RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_rejects_structural_header_heading_locator -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_heading_scoped_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_inside_heading_not_after_context_heading_for_region_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_selected_region_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_record_selected_region_text_extract_from_observed_text_locator RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_selected_region_text_extract_with_explicit_locator_compiles_to_inner_text RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_selected_region_text_extract_rejects_observed_text_driven_locator RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_compiles_to_deterministic_script RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_classification_requires_durable_anchor -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `git diff --check -- RpaClaw/backend/rpa/trace_locator_utils.py RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py docs/features/F011-rpa-region-scoped-snapshot.md docs/evidence/EV-011-rpa-region-scoped-snapshot.md`
- `python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs --strict`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_context_builds_scope_from_evidence RpaClaw/backend/tests/test_rpa_region_context.py::test_region_scope_omits_standalone_evidence_payload RpaClaw/backend/tests/test_rpa_trace_models.py::test_accepted_trace_carries_region_scope_evidence -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_trace_models.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_marks_structured_views_with_region_scope RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_accepts_region_scope_and_marks_scope_relation -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_only_selected_detail_fields_with_section_title RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_selected_table_and_omits_outside_detail RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_only_selected_table_rows_with_headers -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_nearby_heading_as_context_not_candidate -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_does_not_fallback_to_outside_pairs_when_container_has_inside_node RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_uses_geometry_when_scope_relation_is_missing -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_pairs_by_geometry_when_scope_relation_missing RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_does_not_fallback_to_outside_pairs_when_container_has_inside_node RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_selected_text_in_action_group_and_filters_outside_actions -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_selected_action_group_text_by_geometry_when_scope_relation_missing -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_selected_text_in_action_group_and_filters_outside_actions RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_expands_selected_region_when_outside_text_overlaps_instruction RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_does_not_fallback_to_outside_pairs_when_container_has_inside_node RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_pairs_by_geometry_when_scope_relation_missing RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_nearby_heading_as_context_not_candidate RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_uses_geometry_when_scope_relation_is_missing -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_context_builds_scope_from_evidence RpaClaw/backend/tests/test_rpa_region_context.py::test_region_scope_omits_standalone_evidence_payload RpaClaw/backend/tests/test_rpa_trace_models.py::test_accepted_trace_carries_region_scope_evidence RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_planner_failure_when_debug_dir_is_enabled -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_repair_planner_failure_when_debug_dir_is_enabled -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_repair_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_initial_snapshot_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_repair_snapshot_after_first_failure -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_default_planner_contract_diagnostic_includes_llm_call_summary RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_initial_snapshot_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_repair_snapshot_after_first_failure -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_wraps_top_level_run_python_code -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_rejects_top_level_python_without_runtime_context -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_wraps_top_level_run_python_code RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_rejects_top_level_python_without_runtime_context RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_rejects_run_python_without_runner -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_accepts_fenced_json RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_rejects_run_python_without_runner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_wraps_top_level_run_python_code RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_rejects_top_level_python_without_runtime_context RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_accepts_plan_with_extra_planner_output RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_ignores_analysis_and_evidence_json_before_plan RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_finds_unfenced_plan_after_evidence_json RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_dumps_repair_planner_failure_when_debug_dir_is_enabled RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q`
- `python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs/features`
- `python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs`
- `Test-Path 'RpaClaw\frontend\node_modules'`
- `git diff --check`
- `$env:PYTHONPATH='RpaClaw'; E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_region_scoped_snapshot_for_region_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_accepts_planner_selected_region_extract_field RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_planner_when_region_extract_snapshot_missing_fields -q`
- `$env:PYTHONPATH='RpaClaw'; E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py -q`
- `$env:PYTHONPATH='RpaClaw'; E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_selected_region_local_text_extract_with_fields_uses_snapshot_extract_not_runtime_ai RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_selected_region_local_text_without_fields_does_not_inject_recorded_region_context RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_geometry_fallback_requires_matching_frame_path RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_budget_trims_low_priority_context_and_long_text RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_extract_snapshot_plan_validation_allows_empty_fields_by_default RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_execute_extract_snapshot_plan_allows_empty_output_by_default RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_extract_snapshot_plan_validation_rejects_empty_required_field RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_synthesize_region_extract_fields_from_local_text -q`
- `$env:PYTHONPATH='RpaClaw'; E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
- `$env:PYTHONPATH='RpaClaw'; E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_region_scoped_text_extract_does_not_embed_recorded_text_locator -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_region_scoped_snapshot_for_region_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_accepts_planner_selected_region_extract_field RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_planner_when_region_extract_snapshot_missing_fields RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_synthesize_region_extract_fields_from_local_text -q`
- `git diff --check -- RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_context_heading_for_selected_text RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_heading_scoped_text_extract_signal RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_compiles_to_deterministic_script -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_region_scoped_text_extract_does_not_embed_recorded_text_locator RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_selected_region_local_text_without_fields_does_not_inject_recorded_region_context -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_heading_scoped_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_accepts_planner_selected_region_extract_field RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_planner_when_region_extract_snapshot_missing_fields RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_repair_planner_when_region_extract_snapshot_missing_fields RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_inside_heading_separate_from_after_context_heading RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_context_heading_for_selected_text -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_heading_scoped_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_inside_heading_not_after_context_heading_for_region_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_create_heading_scoped_signal_from_after_context_heading_only -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_compiles_to_deterministic_script RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_rejects_after_context_anchor -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_heading_scoped_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_inside_heading_not_after_context_heading_for_region_text_extract_signal RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_create_heading_scoped_signal_from_after_context_heading_only RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_accepts_planner_selected_region_extract_field RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_planner_when_region_extract_snapshot_missing_fields RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_reasks_repair_planner_when_region_extract_snapshot_missing_fields RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot -q`
- `npm.cmd ci`
- `npm.cmd run test`
- `npm.cmd run test -- src/utils/rpaRegionSelection.test.ts src/pages/rpa/RecorderPage.test.ts --testTimeout 15000`
- `npm.cmd run build`
- `npm.cmd run type-check`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_heading_scoped_region_text_extract_classification_requires_durable_anchor RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_broad_extract_markers_do_not_override_structured_region_or_action_evidence -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
- `$env:PYTHONPATH='RpaClaw'; .\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py -q`
- `cd rpa-eval-app/frontend; npm.cmd run build`
- `python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs/features`
- `python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs/evidence`

## Results

- RegionScope / trace model targeted tests: `3 passed`.
- Snapshot capture contract regression: `7 passed`.
- Snapshot compression regression: `27 passed`.
- Structured-view scope marker tests: initial RED failed because real JS capture did not mark structured `table_views` / `detail_views`; after adding view/row/cell/field `scope_relation` and selected row indexes, GREEN `2 passed`.
- Scoped structured detail-field filtering: initial RED retained an outside detail field; after filtering selected fields while preserving section title, GREEN `3 passed` for detail/table scoped structured tests.
- Code review follow-up tests: initial RED confirmed mixed selected/outside pairs in one container leaked outside pairs, and nearby heading context handling needed explicit protection. After scoped pair filtering, scoped row sorting before caps, and `ancestor_context` capture for containing/nearby context, GREEN `2 passed`.
- Re-review follow-up tests: initial RED confirmed remaining fallback paths where mixed containers could leak outside label-value pairs, including geometry fallback when `scope_relation` was missing. After adding pair bbox filtering and passing `scope_rect` into scoped region selection, GREEN `3 passed`.
- Manual validation follow-up: user selected `1,027 stars today` in the second GitHub Trending card, but runtime returned the first card total star count `20,037`. Debug artifact `data/rpa_recording_snapshots/73ee9158-a972-4c77-8566-5aaf33c58e66/001-initial-snapshot-*.json` showed raw `content_nodes` had `1,027 stars today` with `scope_relation=inside_region`, while compact `expanded_regions` omitted it and exposed same-card outside action `star 37,451`; the planner then generated a broad first-match role-link extraction and got `20,037`. Added scoped action-group text retention and outside action filtering; GREEN `1 passed`, geometry fallback coverage `1 passed`, scoped compression regression `7 passed`, full compression/structured subset `34 passed`, and F011 focused subset `48 passed`.
- Focused F011 verification subset after final review fixes: `48 passed`.
- Capture + compression + trace model combined subset: `42 passed`.
- Runtime scoped planner targeted tests: initial RED failed because planner payload still contained top-level `region_context`; after wiring scope through capture/compression, GREEN `2 passed`.
- Runtime compatibility targeted subset after preserving no-scope monkeypatch behavior: `3 passed`.
- Planner failure debug artifact follow-up: initial RED confirmed planner contract failures wrote the initial snapshot but did not persist the invalid planner output or LLM call summary; after adding generic `planner_failure` debug dumps for initial planner failures, GREEN `1 passed`.
- Independent review follow-up: added direct repair planner failure coverage for the same `planner_failure` artifact path; GREEN `2 passed`.
- Planner/debug focused subset after the follow-up: `5 passed`.
- Planner/debug subset including `test_default_planner_contract_diagnostic_includes_llm_call_summary`: `4 passed, 1 failed`; the failure is the pre-existing local environment gap `ModuleNotFoundError: No module named 'langchain_openai'` while importing `backend.deepagent.engine`.
- Manual validation follow-up: user selected a GitHub Trending repository row and requested `获取stars数`; debug artifact `data/rpa_recording_snapshots/563a5185-3c16-4da5-ad3f-c27656d37cc0/002-initial-planner_failure-获取stars数.json` showed `compact_snapshot_summary.mode=region_scoped_snapshot`, `expanded_region_titles=["Imbad0202 / academic-research-skills"]`, and `snapshot_comparison.classification=present_in_both`, but the planner returned valid JSON with top-level Playwright Python instead of `async def run(page, results)`. This classified the failure as planner contract adaptation, not a snapshot compression miss.
- Planner contract wrapper RED/GREEN: initial RED confirmed top-level Playwright Python with `await`/`return` was rejected as a planner contract failure; after adding narrow runner wrapping for runtime-context code, GREEN `1 passed`.
- Planner contract guardrail RED/GREEN: initial RED confirmed broad wrapping would accept `import re\nreturn '3,184'`; after narrowing wrapping signals to `page.`, `await `, or `results`, GREEN `1 passed`.
- Planner parse focused subset after contract wrapper: `3 passed`, then `8 passed`.
- Runtime planner/debug focused subset after contract wrapper: `4 passed`.
- Full `test_rpa_recording_runtime_agent.py` after planner contract wrapper: `62 passed, 4 failed`. The remaining failures are blocked by missing optional dependency `langchain_openai` while importing `backend.deepagent.engine` for default planner tests.
- Requested backend target set after final review fixes: `114 passed, 11 failed`. Six `test_rpa_region_context.py` route tests and four default planner tests are blocked by missing `langchain_openai`; one lazy-import assertion is polluted by the earlier failed route import in the same pytest process. The focused F011 model/capture/compression/runtime tests passed.
- Readiness environment update (2026-05-20): the PR worktree venv install timed out, but the shared project Python 3.12 environment at `E:\Work-Project\OtherWork\ScienceClaw\.venv\Scripts\python.exe` contains `langchain-openai`, `pytest`, `fastapi`, and `playwright`; this interpreter was used for final backend verification against the PR worktree sources.
- Runtime scoped planner compatibility subset: initial RED showed two upstream `selected_region_snapshot/context_scope` tests were still asserting the old preview/debug payload path, while F011 requires planner main input to be `region_scoped_snapshot`. After updating the tests to assert scoped snapshot mode and no top-level `region_context/context_scope`, GREEN `4 passed`.
- Backend F011 target set: GREEN `149 passed` for `test_rpa_region_context.py`, `test_rpa_assistant_snapshot_runtime.py`, `test_rpa_snapshot_compression.py`, `test_rpa_snapshot_compression_structured.py`, `test_rpa_recording_runtime_agent.py`, and `test_rpa_trace_models.py`.
- PR #55 review follow-up RED/GREEN: initial focused tests failed for compiler region_context replay injection, selected-region local_text field priority, iframe geometry fallback, scoped budget trimming, and default empty extract validation. After the follow-up patch, the same focused set was GREEN `8 passed`.
- PR #55 impacted backend subset: GREEN `199 passed` for compiler, snapshot compression, structured compression, and recording runtime agent tests.
- PR #55 backend F011 target set with compiler included: GREEN `239 passed` for `test_rpa_region_context.py`, `test_rpa_assistant_snapshot_runtime.py`, `test_rpa_snapshot_compression.py`, `test_rpa_snapshot_compression_structured.py`, `test_rpa_recording_runtime_agent.py`, `test_rpa_trace_models.py`, and `test_rpa_trace_skill_compiler.py`.
- Manual validation follow-up (2026-05-22): user selected the GitHub repository About text and requested the project description. Debug artifact `data/rpa_recording_snapshots/384d1b79-8ec9-4944-9ccb-50837f5eb40b/001-initial-snapshot-获取这段项目介绍.json` showed `compact_snapshot.mode=region_scoped_snapshot` and selected text present in `expanded_regions`, but the accepted plan used `run_python` with exact observed text locators. RED/GREEN regression added `test_region_scoped_text_extract_does_not_embed_recorded_text_locator`; initial RED embedded the observed text locator, GREEN uses runtime semantic replay and removes the recorded text from compiled code.
- Compiler focused verification after the 2026-05-22 follow-up: GREEN `86 passed` for `test_rpa_trace_skill_compiler.py`.
- Region-scoped runtime/compile focused verification after the 2026-05-22 follow-up: GREEN `90 passed` for compiler tests plus four selected-region runtime planner contract tests.
- Whitespace check after the 2026-05-22 follow-up: `git diff --check` reported only existing Windows line-ending warnings for touched files, no whitespace errors.
- Heading-scoped text compile follow-up (2026-05-22): initial RED focused tests failed because compact snapshot did not preserve ancestor heading evidence for selected free text, accepted trace had no durable `region_text_extract` contract, and compiler had no deterministic path for section text. GREEN focused set `3 passed` after adding context heading evidence, accepted trace signal recording, and deterministic compile.
- Heading-scoped replay guardrails: compiler now requires `region_text_extract.kind=heading_scoped_text`, a valid heading locator, and `text_strategy=following_sibling_block`. This keeps the deterministic path out of generic free-text extraction, table/list extraction, single-value extraction, and action evidence flows.
- Focused regression after narrowing global `following::*` to same-sibling extraction: `2 passed` for the no-recorded-text and no-region-context-injection protections; full compiler suite GREEN `87 passed`; snapshot compression suite GREEN `31 passed`; selected runtime agent subset GREEN `5 passed`.
- Manual validation follow-up (2026-05-23): generated replay anchored About extraction on `Topics` and returned `about_info=""`. Debug artifact `data/rpa_recording_snapshots/b705be41-0974-4162-8599-c70c386c90cd/001-initial-snapshot-获取About的信息内容.json` showed `About` as `inside_region` heading in `evidence.texts`, selected body text present, and downstream `Topics` as `context_headings[0]`. This proved the failure was an evidence contract bug, not a GitHub-specific selector gap.
- Section-text contract RED/GREEN (2026-05-23): initial focused tests failed for missing `inside_headings`, missing accepted trace signal from `section_anchor`, and compiler rejection of the new `bounded_section_text` strategy. After the fix, focused snapshot tests GREEN `2 passed`, runtime signal tests GREEN `3 passed`, and compiler section tests GREEN `2 passed`.
- Section-text regression set after the 2026-05-23 fix: full compiler suite GREEN `88 passed`; snapshot compression suite GREEN `32 passed`; selected runtime agent subset GREEN `7 passed`.
- Independent subagent review: evidence explorer confirmed `scopeRelationForRect()` produced `About=inside_region` and `Topics=ancestor_context`, while compression promoted only ancestor headings. Vision/risk reviewer required deterministic compile to depend on explicit `section_anchor` evidence and to fallback to runtime AI when only after-context headings exist; the implementation follows that boundary.
- Region-scoped compile classification evidence (2026-05-24): added compiler coverage for reliable `section_anchor` versus missing-anchor free text, and for broad extract/read markers not overriding structured table/list/single-value/action evidence. Focused added tests GREEN `2 passed`; full compiler suite GREEN `90 passed`. This is evidence hardening only; no production compiler keyword narrowing was needed.
- Region action replay regression (2026-05-25): initial RED tests showed an AI click on the first Jalor/export-table file name with `table_region`, `output_key`, `action_performed=True`, and a download signal compiled to table `evaluate()` instead of `_download_from_export_task()`, and selected row/list extraction templates contained the invalid `;}})()` JavaScript shape. GREEN after compiler evidence-gate fix: `test_rpa_trace_skill_compiler.py` passed `94 passed`; `test_rpa_recording_runtime_agent.py -k region_context` passed `5 passed, 76 deselected`. Full `test_rpa_recording_runtime_agent.py` remained blocked by missing local dependency `langchain_openai` in four default planner tests, unrelated to this compiler change.
- Independent subagent review for the 2026-05-25 regression: explorer confirmed the smallest guard matrix should cover export-table click/download with `region_context`, no-download table-region click action, table/list selected-index template shape, and nearby export/helper plus region extract tests. A follow-up reviewer found a runtime metadata mismatch where `trace_requires_runtime_ai_replay()` could return false even though render output used `_execute_runtime_ai_instruction()` for region-backed runtime-AI preserve or no-code side-effect traces; added RED/GREEN coverage and aligned the helper ordering with the render branch.
- Generic rpa-eval-app manual fixture (2026-05-24): added `/section-texts`, a non-GitHub page with heading + sibling body, after-context-only heading, and complex nested container scenarios. `npm.cmd run build` in `rpa-eval-app/frontend` passed; Vite reported only the existing chunk-size warning. This proves the fixture exists and builds; it is not yet runner-backed eval evidence or a recorded RPA compile artifact.
- Review correction (2026-05-24): clarified that `/section-texts` is a manual fixture, not completed eval evidence; moved expected classification out of page DOM text and into README/Evidence metadata. `npm.cmd run build` in `rpa-eval-app/frontend` passed again; `git diff --check` reported only Windows line-ending warnings.
- Harness feature check: `6 errors` from pre-existing `F001-rpa-trace-source-convergence.md` missing required sections; F011 produced no feature-structure error.
- Harness docs check after the 2026-05-24 pre-work update: `docs/features` still reports `6 errors` from pre-existing `F001-rpa-trace-source-convergence.md`; F011 has no feature-structure error. `docs/evidence` still reports EV-001 structure debt and, when scanned alone, cannot resolve EV-011's `feature_refs: [F011]` because the feature document is outside the scan path. EV-011 now carries both `feature_ids` and `feature_refs`.
- Harness all-docs check: `23 errors, 3 warnings` from pre-existing ADR-001/ADR-002, EV-001, and F001 structure/link debt. The earlier F011 evidence backlink warning was removed by changing the Feature evidence entry to a Markdown link.
- Frontend dependency installation: `npm.cmd ci` succeeded in the PR worktree. It reported `25 vulnerabilities` via npm audit and deprecation warnings; these are existing dependency-maintenance issues, not F011 implementation changes.
- Frontend full test run: `npm.cmd run test` produced `219 passed, 3 timed out`. The failures were timeouts in existing RPA page tests under the default 5000 ms per-test limit, not assertion failures in F011 region selection.
- Frontend F011-relevant test subset: GREEN `25 passed` for `src/utils/rpaRegionSelection.test.ts` and `src/pages/rpa/RecorderPage.test.ts` with `--testTimeout 15000`, including pending region id forwarding, selected-region retention, canvas event isolation, valid drag analysis, stale analysis ordering, Escape cancel, and tiny-selection cancellation.
- Frontend production build: `npm.cmd run build` succeeded. Build warnings remain for existing duplicate locale keys, browserslist age, CSS syntax warnings, and chunk size.
- Frontend type-check: `npm.cmd run type-check` remains blocked by broad pre-existing TypeScript debt across unrelated components/locales/utils. No F011 files were modified to address this project-level debt.
- User manual validation: user reported local service verification passed for the region-scoped snapshot feature after selecting GitHub Trending row fields and extracting scoped values.
- Whitespace check: `git diff --check` passed.

Current summary:

- `699b088` closed the PR #55 review blockers on the merged mainline feature.
- `a27bb41`, `4a2fe58`, `7c1e273`, `04b8fac`, `8e1d1ad`, `f3a6c59` form the current selected-region text extract hardening chain.
- `0a2abc3` closes the region-backed action/download misclassification regression.
- Latest local implementation update: the `f3a6c59` stable-single-value guard is now shared with the older `heading_scoped_text` path. The old gap was that `heading_scoped_text` only checked locator validity and skipped the observed-value/dynamic-id/structural-header replay-safe guard added for `selected_region_text_extract`.
- Latest root-cause conclusion: selected-region extract must stay split between `single_value_extract` and `anchored_region_extract`; both lanes need the same replay-safe locator boundary so title fixes and region-content fixes do not regress each other.
- Latest harness conclusion: keep this hardening chain under `F011 / EV-011`; do not split a new Feature unless a future capability goes beyond the same selected-region evidence classification problem.
- Evidence remains `Partial` at feature-closeout level because local verification is present, but latest remote CI / review evidence for the current branch is still pending.

## Harness Validation

```text
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs --strict
```

Result: `Scanned 152 markdown file(s). Checked 6 knowledge artifact(s). Errors: 0. Warnings: 0.`

## Artifacts

- Feature: `docs/features/F011-rpa-region-scoped-snapshot.md`
- Spec: `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md`
- Plan: `docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md`
- Legacy design: `docs/superpowers/specs/2026-05-26-rpa-selected-region-text-extract-design.md`
- Legacy design scratch: `docs/superpowers/specs/2026-05-27-rpa-selected-region-extract-splitting-design.md`
- Patch chain commits: `6cb4b29`, `4a1adf2`, `5ea9aa7`, `699b088`, `a27bb41`, `4a2fe58`, `7c1e273`, `04b8fac`, `8e1d1ad`, `f3a6c59`, `0a2abc3`
- Independent Vision Gate reviewer: Entry Gate pass; exit review must verify capture-before-cap, scoped compression candidate filtering, planner payload unification, trace scope evidence, and no coordinate replay.
- Independent code reviewer found three blocking/important issues: same-container outside pairs leaked into candidates, structured table rows were capped before scoped ordering, and parent/heading context lacked `ancestor_context`. All three were addressed with targeted tests before this Evidence update.
- Independent Vision Gate / Patch Churn reviewer for the planner contract follow-up: pass with non-blocking tightening. The reviewer agreed this fix belongs at the planner JSON contract boundary because raw and compact snapshots already contained the selected evidence, and recommended keeping the wrapper narrow so non-runtime Python-like snippets remain planner contract failures.
- Independent risk review for the 2026-05-22 heading-scoped text follow-up: direction accepted as a narrow compile contract, with one required tightening. The global `following::*` candidate lookup was replaced by the explicit `following_sibling_block` strategy to reduce cross-region extraction risk.

### Region-Scoped Debug Artifact Example

```json
{
  "raw_snapshot": {
    "region_scope": {
      "region_id": "region-1",
      "tab_id": "tab-1",
      "frame_path": ["iframe.detail"],
      "frame_rect": {"x": 10, "y": 20, "width": 300, "height": 160}
    },
    "content_nodes": [
      {"container_id": "inside", "text": "SKU", "scope_relation": "inside_region"},
      {"container_id": "outside", "text": "Invoice Price Total", "scope_relation": "outside_context"}
    ]
  },
  "region_scoped_snapshot": {
    "mode": "region_scoped_snapshot",
    "region_scope": {
      "region_id": "region-1",
      "tab_id": "tab-1",
      "frame_path": ["iframe.detail"],
      "frame_rect": {"x": 10, "y": 20, "width": 300, "height": 160}
    },
    "expanded_regions": [{"summary": "SKU=A-001"}],
    "sampled_regions": [],
    "region_catalogue": [{"summary": "Line Items"}]
  },
  "accepted_trace": {
    "region_scope": {
      "region_id": "region-1",
      "frame_path": ["iframe.detail"],
      "frame_rect": {"x": 10, "y": 20, "width": 300, "height": 160}
    }
  }
}
```

## Notes

- 实现前 Evidence anchor 已创建，用于记录 F011 的验证轨迹。
- 实现必须证明选区内 DOM 在 raw capture 与 compact compression 中获得优先权。
- 选区外 DOM 不应作为任务候选参与竞争，但允许保留页面身份、父级、表头、dialog/frame/heading 等最小上下文。
- UI 交互未改动；现有 chat payload 的 `region_id` 路径保持兼容。
- `region_context.py` 只新增 scope conversion，没有扩展为第二套 snapshot/compression/compiler 系统。
- `RecordingRuntimeAgent` 不再把 top-level `region_context` 作为 planner 主输入；兼容性信号仍进入 debug/trace evidence。
- Replay/compile 路径未引入坐标执行逻辑。

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
