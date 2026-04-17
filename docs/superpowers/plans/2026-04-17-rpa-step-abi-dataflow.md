# RPA Step ABI And Dataflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal step dataflow contract so recorded RPA steps can safely pass runtime results across later steps, while keeping `semantic_decision + act` closed inside one `ai_instruction` step instead of leaking helper navigation steps.

**Architecture:** Keep the current linear step list and ReAct architecture. Do not add DAG scheduling, Constraint Bag, or a general workflow engine. Extend the existing `RPAStep` schema with explicit reference fields (`value_from`, `url_from`, `target_from`), teach the generator to resolve those references from `_results`, and tighten `ai_instruction` act-mode so semantic selection steps either complete their own navigation internally or expose a structured target that runtime can materialize.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, Playwright, unittest

---

## File Map

**Modify**
- `RpaClaw/backend/rpa/manager.py`
  Purpose: extend `RPAStep` with minimal ABI fields for cross-step dataflow.
- `RpaClaw/backend/rpa/assistant.py`
  Purpose: preserve ABI fields through planner parsing, keep semantic-decision act steps closed, and distill away leaked helper navigation.
- `RpaClaw/backend/rpa/runtime_ai_instruction.py`
  Purpose: finish `semantic_decision + act` internally by materializing structured navigation targets and persisting result payloads.
- `RpaClaw/backend/rpa/generator.py`
  Purpose: resolve `*_from` bindings from `_results`, prefer references over recorded literals, and normalize ai-instruction act payloads during export.
- `RpaClaw/backend/tests/test_rpa_assistant.py`
  Purpose: planner/distill tests for ABI preservation and helper-step cleanup.
- `RpaClaw/backend/tests/test_rpa_ai_instruction_runtime.py`
  Purpose: runtime tests for semantic-decision act closure and structured target navigation.
- `RpaClaw/backend/tests/test_rpa_generator.py`
  Purpose: export tests for `value_from/url_from/target_from` resolution and ai-instruction act normalization.

**Do not modify in this plan**
- Frontend RPA pages
- Task scheduling
- General chat mode behavior

---

### Task 1: Introduce Minimal Step ABI Fields

**Files:**
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`

- [ ] **Step 1: Add the failing schema/parse tests**

```python
def test_parse_step_candidate_preserves_value_from_and_url_from():
    parsed = {
        "action": "fill",
        "description": "Fill email",
        "value_from": "contact_info.email",
        "target_hint": {"label": "Email"},
    }
    candidate = RPAReActAgent._parse_step_candidate(parsed, "Fill the form", False)
    assert candidate["structured_intent"]["value_from"] == "contact_info.email"


def test_parse_step_candidate_preserves_target_from():
    parsed = {
        "action": "click",
        "description": "Open selected repo",
        "target_from": "most_skill_related_repo",
    }
    candidate = RPAReActAgent._parse_step_candidate(parsed, "Open selected repo", False)
    assert candidate["structured_intent"]["target_from"] == "most_skill_related_repo"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_assistant.RPAReActAgentTests.test_parse_step_candidate_preserves_value_from_and_url_from
```

Expected: FAIL because `value_from/url_from/target_from` are not preserved by `_extract_structured_execute_intent`.

- [ ] **Step 3: Extend `RPAStep` and parser with ABI fields**

```python
class RPAStep(BaseModel):
    ...
    result_key: Optional[str] = None
    value_from: Optional[str] = None
    url_from: Optional[str] = None
    target_from: Optional[str] = None
```

```python
for key in (
    "target_hint",
    "collection_hint",
    "ordinal",
    "value",
    "result_key",
    "value_from",
    "url_from",
    "target_from",
):
    value = parsed.get(key)
    if value is not None:
        intent[key] = value
```

- [ ] **Step 4: Run focused assistant tests**

Run:

```bash
python -m py_compile RpaClaw/backend/rpa/manager.py RpaClaw/backend/rpa/assistant.py RpaClaw/backend/tests/test_rpa_assistant.py
```

Expected: no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/manager.py RpaClaw/backend/rpa/assistant.py RpaClaw/backend/tests/test_rpa_assistant.py
git commit -m "feat: add minimal rpa step abi fields"
```

---

### Task 2: Make Semantic-Decision Act Steps Close Internally

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/rpa/runtime_ai_instruction.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_ai_instruction_runtime.py`

- [ ] **Step 1: Add the failing distill/runtime tests**

```python
def test_distill_react_recorded_steps_drops_followup_navigation_after_act_ai_instruction():
    trace_steps = [
        {
            "action": "ai_instruction",
            "instruction_kind": "semantic_decision",
            "output_expectation": {"mode": "act"},
            "execution_hint": {"allow_navigation": True},
        },
        {"action": "navigate", "value": "https://github.com/example/repo"},
    ]
    distilled = _distill_react_recorded_steps("open best repo", trace_steps)
    assert len(distilled) == 1
    assert distilled[0]["action"] == "ai_instruction"
```

```python
async def test_execute_ai_instruction_materializes_navigation_target_for_act_mode():
    step = {
        "action": "ai_instruction",
        "instruction_kind": "semantic_decision",
        "output_expectation": {"mode": "act"},
        "execution_hint": {"allow_navigation": True},
        "result_key": "most_skill_related_repo",
    }
    plan = {
        "plan_type": "code",
        "code": (
            "async def run(page, results):\n"
            "    return {'success': True, 'output': {'repo_path': '/owner/repo'}}"
        ),
    }
```

- [ ] **Step 2: Run focused tests to confirm current gap**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_assistant.RPAAssistantRoutingTests.test_distill_react_recorded_steps_drops_followup_navigation_after_act_ai_instruction
```

Expected: FAIL before the helper-navigation cleanup is in place.

- [ ] **Step 3: Tighten the act contract in assistant/runtime**

```python
SEMANTIC_DECISION_ACT_PROMPT_SUFFIX = (
    "Complete the requested browser action inside this AI instruction. "
    "Do not stop after only identifying the best match or returning explanatory text. "
    "If you need to express the selected target in a structured result, use "
    "target_url, url, href, path, or repo_path."
)
```

```python
if parsed_kind == "semantic_decision" and output_expectation.get("mode") == "act":
    allow_navigation = True
    prompt = f"{normalized_prompt}\n\n{SEMANTIC_DECISION_ACT_PROMPT_SUFFIX}"
```

```python
navigation_target = _extract_navigation_target_from_value(getattr(page, "url", "") or "", final_result)
if not navigation_target and result_key:
    navigation_target = _extract_navigation_target_from_value(getattr(page, "url", "") or "", results.get(result_key))
if navigation_target:
    await page.goto(navigation_target, wait_until="domcontentloaded")
    await page.wait_for_load_state("domcontentloaded")
    final_result["action_performed"] = True
    final_result["navigation_target"] = navigation_target
```

- [ ] **Step 4: Remove leaked helper navigation from committed/exported traces**

```python
def _is_superseded_ai_instruction_followup_navigation(previous_step, current_step):
    if not _is_runtime_act_ai_instruction(previous_step):
        return False
    return str(current_step.get("action") or "").strip().lower() == "navigate"
```

```python
if distilled and _is_superseded_ai_instruction_followup_navigation(distilled[-1], step):
    continue
```

- [ ] **Step 5: Run focused syntax and smoke validation**

Run:

```bash
python -m py_compile RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/runtime_ai_instruction.py
```

Expected: no syntax errors.

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/runtime_ai_instruction.py RpaClaw/backend/tests/test_rpa_assistant.py RpaClaw/backend/tests/test_rpa_ai_instruction_runtime.py
git commit -m "fix: close semantic decision act steps inside runtime"
```

---

### Task 3: Teach the Generator to Consume Step References

**Files:**
- Modify: `RpaClaw/backend/rpa/generator.py`
- Test: `RpaClaw/backend/tests/test_rpa_generator.py`

- [ ] **Step 1: Add the failing generator tests**

```python
def test_generate_script_uses_url_from_binding_for_navigation():
    steps = [
        {"action": "ai_instruction", "result_key": "selected_repo", "instruction_kind": "semantic_decision", "output_expectation": {"mode": "act"}},
        {"action": "navigate", "description": "Open pull requests", "url_from": "selected_repo.repo_path", "value": "https://github.com/recorded/repo/pulls"},
    ]
```

```python
def test_generate_script_uses_value_from_binding_for_fill():
    steps = [
        {"action": "extract_text", "result_key": "contact_info"},
        {"action": "fill", "target": "{\"label\":\"Email\"}", "value_from": "contact_info.email"},
    ]
```

- [ ] **Step 2: Run focused generator tests and confirm failure**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_generator.PlaywrightGeneratorTests.test_generate_script_uses_url_from_binding_for_navigation
```

Expected: FAIL because generator still emits recorded literals.

- [ ] **Step 3: Add a small `_resolve_result_ref()` helper in generated scripts**

```python
def _resolve_result_ref(results, ref):
    if not isinstance(ref, str) or not ref.strip():
        return None
    current = results
    for part in ref.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None
    return current
```

- [ ] **Step 4: Prefer `url_from/value_from/target_from` over recorded literals**

```python
if step.get("url_from"):
    step_lines.append(f'    _resolved_url = _resolve_result_ref(_results, "{step["url_from"]}")')
    step_lines.append('    if not isinstance(_resolved_url, str) or not _resolved_url.strip():')
    step_lines.append('        raise RuntimeError("Missing bound navigation URL")')
    step_lines.append('    await current_page.goto(_resolved_url, wait_until="domcontentloaded")')
```

```python
if step.get("value_from"):
    step_lines.append(f'    _resolved_value = _resolve_result_ref(_results, "{step["value_from"]}")')
    step_lines.append('    if _resolved_value is None:')
    step_lines.append('        raise RuntimeError("Missing bound fill value")')
    step_lines.append('    await locator.fill(str(_resolved_value))')
```

- [ ] **Step 5: Re-run targeted generator tests**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_generator.PlaywrightGeneratorTests.test_generate_script_uses_url_from_binding_for_navigation RpaClaw.backend.tests.test_rpa_generator.PlaywrightGeneratorTests.test_generate_script_uses_value_from_binding_for_fill
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/generator.py RpaClaw/backend/tests/test_rpa_generator.py
git commit -m "feat: add generator support for bound step references"
```

---

### Task 4: Bridge Page1→Page2 Data Scenarios End-To-End

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/rpa/generator.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_generator.py`

- [ ] **Step 1: Add the failing cross-page flow tests**

```python
def test_extract_then_fill_flow_preserves_value_from_binding():
    trace_steps = [
        {"action": "ai_script", "description": "Extract contact info", "result_key": "contact_info"},
        {"action": "navigate", "value": "https://example.com/form"},
        {"action": "fill", "description": "Fill email", "value_from": "contact_info.email"},
    ]
```

```python
def test_semantic_selection_then_open_subpage_uses_runtime_result_not_recorded_repo():
    steps = [
        {"action": "ai_instruction", "instruction_kind": "semantic_decision", "output_expectation": {"mode": "act"}, "result_key": "selected_repo"},
        {"action": "navigate", "url_from": "selected_repo.repo_path"},
    ]
```

- [ ] **Step 2: Preserve and export bindings instead of collapsing them away**

```python
for key in ("value_from", "url_from", "target_from"):
    value = parsed.get(key)
    if value is not None:
        intent[key] = value
```

```python
normalized_step["assistant_diagnostics"]["uses_result_binding"] = bool(
    normalized_step.get("value_from") or normalized_step.get("url_from") or normalized_step.get("target_from")
)
```

- [ ] **Step 3: Run focused end-to-end generator/assistant checks**

Run:

```bash
python -m py_compile RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/generator.py
```

Expected: no syntax errors.

- [ ] **Step 4: Commit**

```bash
git add RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/generator.py RpaClaw/backend/tests/test_rpa_assistant.py RpaClaw/backend/tests/test_rpa_generator.py
git commit -m "feat: preserve cross-step data bindings for rpa flows"
```

---

### Task 5: Final Regression Pass

**Files:**
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_ai_instruction_runtime.py`
- Test: `RpaClaw/backend/tests/test_rpa_generator.py`

- [ ] **Step 1: Run syntax validation**

Run:

```bash
python -m py_compile RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/runtime_ai_instruction.py RpaClaw/backend/rpa/generator.py
```

Expected: no syntax errors.

- [ ] **Step 2: Run targeted generator suite**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_generator
```

Expected: PASS except any pre-existing local environment tests that require unavailable `playwright`.

- [ ] **Step 3: Run targeted runtime/assistant tests**

Run:

```bash
python -m unittest RpaClaw.backend.tests.test_rpa_ai_instruction_runtime RpaClaw.backend.tests.test_rpa_assistant
```

Expected: PASS except any pre-existing local environment tests that require unavailable `playwright`.

- [ ] **Step 4: Manual scenario verification**

Run these recorder scenarios manually:

```text
1. Trending page: 找到和 SKILL 最相关的项目打开
2. 当前 repo pulls 页面: 收集前 10 个 PR，输出严格数组
3. 页面 1 提取 email，页面 2 自动填入 email
```

Expected:
- Scenario 1 exports one ai_instruction step for the semantic selection action, without leaked helper navigation.
- Scenario 2 exports a stable ai_script array extraction step.
- Scenario 3 exports `value_from/url_from` bindings instead of hard-coded recorded literals.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/runtime_ai_instruction.py RpaClaw/backend/rpa/generator.py RpaClaw/backend/tests/test_rpa_assistant.py RpaClaw/backend/tests/test_rpa_ai_instruction_runtime.py RpaClaw/backend/tests/test_rpa_generator.py
git commit -m "refactor: add rpa step abi dataflow support"
```

---

## Self-Review

**Spec coverage**
- Covers semantic selection helper leakage.
- Covers cross-step result passing.
- Covers export-time consumption of runtime results instead of recorded literals.
- Does not introduce DAG scheduling or unrelated refactors.

**Placeholder scan**
- No `TODO`, `TBD`, or “similar to above”.
- Each task names exact files and commands.

**Type consistency**
- Producing side continues to use `result_key`.
- Consuming side uses only `value_from`, `url_from`, `target_from`.
- No alternative field names are introduced in later tasks.
