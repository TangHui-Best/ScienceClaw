---
doc_kind: evidence
id: EV-011
title: RPA Region-Scoped Snapshot Evidence
status: active
feature_ids: [F011]
created: 2026-05-19
updated: 2026-05-19
scope: RPA region-scoped snapshot capture and compression
---

# EV-011 RPA Region-Scoped Snapshot Evidence

## Commands

- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_context_builds_scope_from_evidence RpaClaw/backend/tests/test_rpa_region_context.py::test_region_scope_omits_standalone_evidence_payload RpaClaw/backend/tests/test_rpa_trace_models.py::test_accepted_trace_carries_region_scope_evidence -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_trace_models.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_marks_structured_views_with_region_scope RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_accepts_region_scope_and_marks_scope_relation -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_only_selected_detail_fields_with_section_title RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_selected_table_and_omits_outside_detail RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_only_selected_table_rows_with_headers -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_keeps_nearby_heading_as_context_not_candidate -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_does_not_fallback_to_outside_pairs_when_container_has_inside_node RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_uses_geometry_when_scope_relation_is_missing -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_pairs_by_geometry_when_scope_relation_missing RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_does_not_fallback_to_outside_pairs_when_container_has_inside_node RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_filters_outside_pairs_in_selected_container -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_planner_json_parse_failure_returns_agent_diagnostic RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
- `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py -q`
- `Test-Path 'RpaClaw\frontend\node_modules'`
- `git diff --check`

## Results

- RegionScope / trace model targeted tests: `3 passed`.
- Snapshot capture contract regression: `7 passed`.
- Snapshot compression regression: `27 passed`.
- Structured-view scope marker tests: initial RED failed because real JS capture did not mark structured `table_views` / `detail_views`; after adding view/row/cell/field `scope_relation` and selected row indexes, GREEN `2 passed`.
- Scoped structured detail-field filtering: initial RED retained an outside detail field; after filtering selected fields while preserving section title, GREEN `3 passed` for detail/table scoped structured tests.
- Code review follow-up tests: initial RED confirmed mixed selected/outside pairs in one container leaked outside pairs, and nearby heading context handling needed explicit protection. After scoped pair filtering, scoped row sorting before caps, and `ancestor_context` capture for containing/nearby context, GREEN `2 passed`.
- Re-review follow-up tests: initial RED confirmed remaining fallback paths where mixed containers could leak outside label-value pairs, including geometry fallback when `scope_relation` was missing. After adding pair bbox filtering and passing `scope_rect` into scoped region selection, GREEN `3 passed`.
- Focused F011 verification subset after final review fixes: `48 passed`.
- Capture + compression + trace model combined subset: `42 passed`.
- Runtime scoped planner targeted tests: initial RED failed because planner payload still contained top-level `region_context`; after wiring scope through capture/compression, GREEN `2 passed`.
- Runtime compatibility targeted subset after preserving no-scope monkeypatch behavior: `3 passed`.
- Full `test_rpa_recording_runtime_agent.py`: `58 passed, 4 failed`. The remaining failures are blocked by missing optional dependency `langchain_openai` while importing `backend.deepagent.engine` for default planner tests.
- Requested backend target set after final review fixes: `114 passed, 11 failed`. Six `test_rpa_region_context.py` route tests and four default planner tests are blocked by missing `langchain_openai`; one lazy-import assertion is polluted by the earlier failed route import in the same pytest process. The focused F011 model/capture/compression/runtime tests passed.
- Frontend verification: skipped because `RpaClaw\frontend\node_modules` is missing in this worktree. No frontend files were modified.
- Whitespace check: `git diff --check` passed.

## Artifacts

- Feature: `docs/features/F011-rpa-region-scoped-snapshot.md`
- Spec: `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md`
- Plan: `docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md`
- Independent Vision Gate reviewer: Entry Gate pass; exit review must verify capture-before-cap, scoped compression candidate filtering, planner payload unification, trace scope evidence, and no coordinate replay.
- Independent code reviewer found three blocking/important issues: same-container outside pairs leaked into candidates, structured table rows were capped before scoped ordering, and parent/heading context lacked `ancestor_context`. All three were addressed with targeted tests before this Evidence update.

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
