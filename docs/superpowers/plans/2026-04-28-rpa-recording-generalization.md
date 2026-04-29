# RPA Recording Generalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI recording traces and exported scripts more robust to runtime data changes without adding eval-case-specific behavior.

**Architecture:** Add backward-compatible structured metadata and generic helpers around the existing trace-first runtime. Runtime changes stay in `recording_runtime_agent.py`; trace schema changes stay in `trace_models.py`; export-time dynamic reuse stays in `trace_skill_compiler.py`.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, Playwright async APIs.

---

## File Structure

- Modify `RpaClaw/backend/rpa/recording_runtime_agent.py`: robust planner JSON parsing, field normalization, generic mixed-effect evidence handling.
- Modify `RpaClaw/backend/rpa/trace_models.py`: optional binding and postcondition models on accepted traces.
- Modify `RpaClaw/backend/rpa/trace_skill_compiler.py`: generic dynamic parameter and helper rendering when trace metadata exists.
- Modify `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`: focused parser, extract, and effect verifier tests.
- Modify `RpaClaw/backend/tests/test_rpa_trace_models.py`: serialization tests for new metadata.
- Modify `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`: compiler tests for dynamic binding behavior.

### Task 1: Runtime Plan Parsing And Snapshot Normalization

**Files:**
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`

- [ ] **Step 1: Add failing parser tests**

Add tests that show `_parse_json_object` accepts fenced JSON with trailing prose and accepts the first valid JSON object when extra text follows it.

- [ ] **Step 2: Add failing extract field normalization tests**

Add tests that show `_snapshot_plan_fields({"fields": {"Project": "Apollo"}})` returns `[{"label": "Project", "value": "Apollo"}]` and preserves list input unchanged.

- [ ] **Step 3: Verify RED**

Run:

```bash
uv run pytest tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_accepts_trailing_text_after_fenced_json tests/test_rpa_recording_runtime_agent.py::test_parse_json_object_accepts_first_json_object_with_trailing_text tests/test_rpa_recording_runtime_agent.py::test_snapshot_plan_fields_accepts_mapping_values -q
```

Expected: tests fail before implementation.

- [ ] **Step 4: Implement robust parsing and normalization**

Use `json.JSONDecoder().raw_decode()` after extracting the best candidate string. Extend `_snapshot_plan_fields` to accept dict maps and convert entries into `{"label": key, "value": value}`.

- [ ] **Step 5: Verify GREEN**

Run the same focused tests and confirm they pass.

### Task 2: Generic Mixed Effect Evidence

**Files:**
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`

- [ ] **Step 1: Add failing mixed-effect tests**

Add tests for `_ensure_expected_effect` showing that `expected_effect="mixed"` accepts a successful `effect.action_performed`, non-empty structured output, and download signal without URL change.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_rpa_recording_runtime_agent.py::test_ensure_expected_effect_accepts_mixed_action_evidence_without_navigation tests/test_rpa_recording_runtime_agent.py::test_ensure_expected_effect_accepts_mixed_structured_output_without_navigation tests/test_rpa_recording_runtime_agent.py::test_ensure_expected_effect_accepts_mixed_download_signal_without_navigation -q
```

Expected: tests fail before implementation.

- [ ] **Step 3: Implement evidence classifier**

Add a small helper that detects generic action evidence from result `effect`, `signals.download`, and meaningful non-empty output. Use it for `mixed` before attempting target URL auto-navigation. Keep strict navigation behavior for `expected_effect="navigate"`.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and confirm they pass.

### Task 3: Trace Metadata For Dynamic Bindings

**Files:**
- Modify: `RpaClaw/backend/rpa/trace_models.py`
- Test: `RpaClaw/backend/tests/test_rpa_trace_models.py`

- [ ] **Step 1: Add failing metadata serialization tests**

Add tests that construct `RPAAcceptedTrace` with `input_bindings`, `output_bindings`, and `postcondition`, then assert `model_dump()` preserves the metadata.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/test_rpa_trace_models.py::test_trace_preserves_dynamic_binding_metadata -q
```

Expected: test fails because fields do not exist.

- [ ] **Step 3: Implement optional metadata fields**

Add Pydantic models or `Dict[str, Any]` fields:

- `input_bindings: Dict[str, Any]`
- `output_bindings: Dict[str, Any]`
- `postcondition: Dict[str, Any]`

Defaults must use `Field(default_factory=dict)`.

- [ ] **Step 4: Verify GREEN**

Run the focused test and confirm it passes.

### Task 4: Compiler Dynamic Binding Helpers

**Files:**
- Modify: `RpaClaw/backend/rpa/trace_skill_compiler.py`
- Test: `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`

- [ ] **Step 1: Add failing compiler tests**

Add tests that compile a trace with embedded AI code containing a recorded business value and an `input_bindings` entry for that value. Assert generated code uses `kwargs.get("invoice_number", "INV-001")` or equivalent parameter expression instead of the literal inside the interaction code.

- [ ] **Step 2: Add generic helper rendering test**

Add a test that a trace postcondition with `kind="table_row_exists"` causes the compiler output to include a generic `_find_table_row_by_headers` helper, without app-specific identifiers.

- [ ] **Step 3: Verify RED**

Run:

```bash
uv run pytest tests/test_rpa_trace_skill_compiler.py::test_compiler_parameterizes_declared_business_binding_in_ai_code tests/test_rpa_trace_skill_compiler.py::test_compiler_renders_generic_table_row_helper_for_postcondition -q
```

Expected: tests fail before implementation.

- [ ] **Step 4: Implement dynamic binding rewrite**

Use trace `input_bindings` as an additional parameter lookup source when rendering embedded AI code. Only rewrite values declared in metadata. Do not infer eval-specific IDs or rewrite stable UI labels.

- [ ] **Step 5: Implement generic helper inclusion**

When any trace contains `postcondition.kind == "table_row_exists"`, include a small helper that scopes a table by header text and finds a row by dynamic key values.

- [ ] **Step 6: Verify GREEN**

Run the focused compiler tests and confirm they pass.

### Task 5: Focused Regression Run

**Files:**
- No production file changes expected.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_rpa_recording_runtime_agent.py tests/test_rpa_trace_models.py tests/test_rpa_trace_skill_compiler.py -q
```

- [ ] **Step 2: Document environment failures if present**

If async pytest plugin issues persist in the worktree baseline, record that as an environment limitation and run the focused synchronous tests individually where possible.
