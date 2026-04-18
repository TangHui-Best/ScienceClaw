# RPA Contract-first SOP-to-SKILL Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full contract-first RPA SOP-to-SKILL compiler core so recording, testing, and exported replay use validated contracts, committed artifacts, typed blackboard dataflow, structured runtime AI output, and replay-equivalent Skill artifacts.

**Architecture:** Add a contract-first pipeline alongside the existing RPA implementation, then route the recorder through it once the full core is available. The pipeline is `BaseSnapshot -> Planner StepContract -> Compiler Artifact -> Executor -> Validator -> Committer -> Skill Builder`, with `skill.py` wrapping committed artifacts instead of regenerating behavior from descriptions.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI backend, Playwright async API, existing RPA modules under `RpaClaw/backend/rpa`, pytest/unittest tests.

---

## Completion Bar

This plan is complete only when all of these are true:

- Contract-first sessions can record a deterministic GitHub Trending ranking flow without runtime AI.
- Contract-first sessions can record a runtime semantic selection flow where runtime AI writes structured JSON to blackboard and later deterministic steps consume it.
- Exported `skill.py` wraps committed artifacts and preserves blackboard refs instead of regenerating logic from descriptions.
- `skill.contract.json` is exported with committed StepContracts, artifacts, validation policies, blackboard schema, and attempt evidence.
- Recording-time validation and replay structural validation both run.
- The old ReAct path remains behind compatibility behavior until the contract-first path passes the full test suite.

## File Structure

- Create `RpaClaw/backend/rpa/contract_models.py`: Pydantic v2 models for StepContract, artifacts, blackboard, validation, attempts, and replay metadata.
- Create `RpaClaw/backend/rpa/blackboard.py`: typed blackboard read/write, dotted refs, URL/value template resolution.
- Create `RpaClaw/backend/rpa/snapshot_views.py`: BaseSnapshot adapter over existing snapshot output and in-memory SnapshotView projections.
- Create `RpaClaw/backend/rpa/locator_compiler.py`: Playwright locator contract to stable locator payload selection.
- Create `RpaClaw/backend/rpa/artifact_quality.py`: quality gates for primitive, deterministic script, and runtime AI artifacts.
- Create `RpaClaw/backend/rpa/contract_compiler.py`: compiles StepContracts into artifacts using controlled patterns.
- Create `RpaClaw/backend/rpa/contract_executor.py`: executes artifacts during recording/test.
- Create `RpaClaw/backend/rpa/contract_validator.py`: RecordingValidator, ReplayValidator, output schema checks, evidence checks.
- Create `RpaClaw/backend/rpa/contract_pipeline.py`: orchestration for plan/compile/execute/validate/commit attempts.
- Create `RpaClaw/backend/rpa/contract_skill_builder.py`: exports `skill.py` and `skill.contract.json` from committed artifacts.
- Modify `RpaClaw/backend/rpa/manager.py`: store contract-first committed steps and blackboard state in RPA sessions.
- Modify `RpaClaw/backend/rpa/assistant.py`: add contract-first agent entry point and keep legacy ReAct as compatibility.
- Modify `RpaClaw/backend/rpa/skill_exporter.py`: include `skill.contract.json`.
- Modify `RpaClaw/backend/route/rpa.py`: route recorder/test/export through contract-first pipeline once enabled.
- Add tests under `RpaClaw/backend/tests/test_rpa_contract_*.py`.

---

### Task 1: Contract Models

**Files:**
- Create: `RpaClaw/backend/rpa/contract_models.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_models.py`

- [ ] **Step 1: Write failing model tests**

Create tests that prove the core schema exists and rejects invalid runtime AI output contracts.

```python
import unittest
from pydantic import ValidationError

from backend.rpa.contract_models import (
    ArtifactKind,
    ExecutionStrategy,
    FailureClass,
    RuntimePolicy,
    StepContract,
)


class ContractModelTests(unittest.TestCase):
    def test_step_contract_uses_six_core_blocks(self):
        contract = StepContract(
            id="step_1",
            description="Open selected repo PRs",
            intent={"goal": "open_selected_repo_prs", "business_object": "github_repository"},
            inputs={"refs": ["selected_project.url"], "params": {}},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )

        self.assertEqual(contract.operator.execution_strategy, ExecutionStrategy.PRIMITIVE_ACTION)
        self.assertEqual(contract.inputs.refs, ["selected_project.url"])

    def test_runtime_ai_requires_structured_output_contract(self):
        with self.assertRaises(ValidationError):
            StepContract(
                id="step_ai",
                description="Select semantic project",
                intent={"goal": "select_project"},
                inputs={"refs": [], "params": {"query": "SKILL"}},
                target={"type": "visible_collection", "collection": "github_trending_repositories"},
                operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
                outputs={"blackboard_key": None, "schema": None},
                validation={"must": []},
                runtime_policy=RuntimePolicy(
                    requires_runtime_ai=True,
                    runtime_ai_reason="Semantic relevance is required",
                ),
            )

    def test_failure_class_is_small_routing_surface(self):
        self.assertEqual(FailureClass.ARTIFACT_FAILED.value, "artifact_failed")
        self.assertEqual(ArtifactKind.DETERMINISTIC_SCRIPT.value, "deterministic_script")
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_models.py -p no:cacheprovider`

Expected: import failure for `backend.rpa.contract_models`.

- [ ] **Step 3: Implement models**

Implement enums and Pydantic models in `contract_models.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ExecutionStrategy(str, Enum):
    PRIMITIVE_ACTION = "primitive_action"
    DETERMINISTIC_SCRIPT = "deterministic_script"
    RUNTIME_AI = "runtime_ai"


class ArtifactKind(str, Enum):
    PRIMITIVE_ACTION = "primitive_action"
    DETERMINISTIC_SCRIPT = "deterministic_script"
    RUNTIME_AI = "runtime_ai"


class FailureClass(str, Enum):
    CONTRACT_INVALID = "contract_invalid"
    SNAPSHOT_STALE = "snapshot_stale"
    ARTIFACT_FAILED = "artifact_failed"
    VALIDATION_FAILED = "validation_failed"


class RuntimePolicy(BaseModel):
    requires_runtime_ai: bool = False
    runtime_ai_reason: str = ""
    allow_side_effect: bool = False
    side_effect_reason: str = ""


class ContractIntent(BaseModel):
    goal: str
    business_object: str = ""
    user_visible_summary: str = ""


class ContractInputs(BaseModel):
    refs: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)


class ContractTarget(BaseModel):
    type: str
    value: Optional[Any] = None
    url_template: Optional[str] = None
    collection: Optional[str] = None
    fields: List[str] = Field(default_factory=list)
    locator: Optional[Dict[str, Any]] = None


class ContractOperator(BaseModel):
    type: str
    execution_strategy: ExecutionStrategy
    selection_rule: Optional[Dict[str, Any]] = None


class ContractOutputs(BaseModel):
    blackboard_key: Optional[str] = None
    schema: Optional[Any] = None


class ContractValidation(BaseModel):
    must: List[Dict[str, Any]] = Field(default_factory=list)


class StepContract(BaseModel):
    id: str
    description: str = ""
    intent: ContractIntent
    inputs: ContractInputs = Field(default_factory=ContractInputs)
    target: ContractTarget
    operator: ContractOperator
    outputs: ContractOutputs = Field(default_factory=ContractOutputs)
    validation: ContractValidation = Field(default_factory=ContractValidation)
    runtime_policy: RuntimePolicy = Field(default_factory=RuntimePolicy)
    reserved: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_runtime_ai_contract(self):
        if self.operator.execution_strategy == ExecutionStrategy.RUNTIME_AI:
            if not self.runtime_policy.requires_runtime_ai:
                raise ValueError("runtime_ai strategy requires runtime_policy.requires_runtime_ai=true")
            if not self.runtime_policy.runtime_ai_reason.strip():
                raise ValueError("runtime_ai strategy requires runtime_ai_reason")
            if not self.outputs.blackboard_key or self.outputs.schema is None:
                raise ValueError("runtime_ai strategy requires structured outputs")
        return self
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_models.py -p no:cacheprovider`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_models.py RpaClaw/backend/tests/test_rpa_contract_models.py
git commit -m "feat: add rpa contract models"
```

---

### Task 2: Blackboard and Dataflow References

**Files:**
- Create: `RpaClaw/backend/rpa/blackboard.py`
- Test: `RpaClaw/backend/tests/test_rpa_blackboard.py`

- [ ] **Step 1: Write failing blackboard tests**

```python
import unittest

from backend.rpa.blackboard import Blackboard, resolve_template


class BlackboardTests(unittest.TestCase):
    def test_resolves_nested_ref(self):
        board = Blackboard()
        board.write("selected_project", {"url": "https://github.com/a/b", "repo": "b"})
        self.assertEqual(board.resolve_ref("selected_project.url"), "https://github.com/a/b")

    def test_resolves_url_template_without_hardcoding_recorded_value(self):
        board = Blackboard(values={"selected_project": {"url": "https://github.com/a/b"}})
        self.assertEqual(
            resolve_template("{selected_project.url}/pulls", board),
            "https://github.com/a/b/pulls",
        )

    def test_missing_ref_raises_key_error_with_path(self):
        board = Blackboard(values={"selected_project": {}})
        with self.assertRaisesRegex(KeyError, "selected_project.url"):
            board.resolve_ref("selected_project.url")
```

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_blackboard.py -p no:cacheprovider`

Expected: import failure for `backend.rpa.blackboard`.

- [ ] **Step 3: Implement blackboard**

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Blackboard:
    values: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    runtime_params: Dict[str, Any] = field(default_factory=dict)

    def write(self, key: str, value: Any, schema: Any = None) -> None:
        if not key or not isinstance(key, str):
            raise ValueError("blackboard key must be a non-empty string")
        self.values[key] = value
        if schema is not None:
            self.schema[key] = schema

    def resolve_ref(self, ref: str) -> Any:
        if not isinstance(ref, str) or not ref.strip():
            raise KeyError(str(ref))
        path = ref.strip().split(".")
        current: Any = self.values
        for segment in path:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            if isinstance(current, list) and segment.isdigit():
                index = int(segment)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
            raise KeyError(ref)
        return current


_TEMPLATE_REF = re.compile(r"\{([^{}]+)\}")


def resolve_template(template: str, board: Blackboard) -> str:
    def replace(match: re.Match[str]) -> str:
        return str(board.resolve_ref(match.group(1).strip()))

    return _TEMPLATE_REF.sub(replace, template or "")
```

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_blackboard.py -p no:cacheprovider`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/blackboard.py RpaClaw/backend/tests/test_rpa_blackboard.py
git commit -m "feat: add rpa contract blackboard"
```

---

### Task 3: BaseSnapshot Adapter and Views

**Files:**
- Create: `RpaClaw/backend/rpa/snapshot_views.py`
- Test: `RpaClaw/backend/tests/test_rpa_snapshot_views.py`

- [ ] **Step 1: Write failing snapshot tests**

```python
import unittest

from backend.rpa.snapshot_views import BaseSnapshot, build_base_snapshot_from_legacy


class SnapshotViewTests(unittest.TestCase):
    def test_builds_action_and_extraction_views_from_legacy_snapshot(self):
        legacy = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "actionable_nodes": [
                {"id": "n1", "role": "link", "name": "Repo A", "href": "/a/repo", "is_visible": True}
            ],
            "content_nodes": [{"id": "c1", "text": "Repo description"}],
            "containers": [{"id": "box1", "container_kind": "repo_card", "child_actionable_ids": ["n1"]}],
            "frames": [{"frame_path": [], "collections": [{"kind": "repo_cards", "items": [{"name": "Repo A"}]}]}],
        }

        snapshot = build_base_snapshot_from_legacy(legacy)

        self.assertIsInstance(snapshot, BaseSnapshot)
        self.assertEqual(snapshot.url, "https://github.com/trending")
        self.assertEqual(snapshot.action_view()["nodes"][0]["name"], "Repo A")
        self.assertEqual(snapshot.extraction_view()["collections"][0]["kind"], "repo_cards")

    def test_views_include_truncation_metadata_when_budget_is_exceeded(self):
        legacy = {
            "url": "x",
            "title": "x",
            "actionable_nodes": [{"id": str(i), "role": "link", "name": f"Link {i}"} for i in range(130)],
        }

        snapshot = build_base_snapshot_from_legacy(legacy)
        view = snapshot.action_view(max_nodes=10)

        self.assertEqual(len(view["nodes"]), 10)
        self.assertTrue(view["truncated"])
```

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_views.py -p no:cacheprovider`

Expected: import failure for `snapshot_views`.

- [ ] **Step 3: Implement snapshot adapter**

Create a BaseSnapshot dataclass that preserves evidence and derives views without re-reading the browser.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_views.py -p no:cacheprovider`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/snapshot_views.py RpaClaw/backend/tests/test_rpa_snapshot_views.py
git commit -m "feat: add rpa base snapshot views"
```

---

### Task 4: LocatorCompiler

**Files:**
- Create: `RpaClaw/backend/rpa/locator_compiler.py`
- Test: `RpaClaw/backend/tests/test_rpa_locator_compiler.py`

- [ ] **Step 1: Write failing locator tests**

Cover role/name priority, exact href, scoped row/card locator, and random-id rejection.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_locator_compiler.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement LocatorCompiler**

Implement a compiler that returns locator payloads compatible with the existing generator/runtime locator payload style:

```python
{"method": "role", "role": "link", "name": "Pull requests", "exact": False}
{"method": "css", "value": "a[href=\"/owner/repo\"]"}
{"method": "nested", "parent": {...}, "child": {...}}
```

Reject:

```python
{"method": "css", "value": "a[href*=\"owner/repo\"]"}
{"method": "css", "value": "#input-172993"}
```

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_locator_compiler.py -p no:cacheprovider`

Expected: all locator tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/locator_compiler.py RpaClaw/backend/tests/test_rpa_locator_compiler.py
git commit -m "feat: add rpa locator compiler"
```

---

### Task 5: Artifact Quality Gate

**Files:**
- Create: `RpaClaw/backend/rpa/artifact_quality.py`
- Test: `RpaClaw/backend/tests/test_rpa_artifact_quality.py`

- [ ] **Step 1: Write failing quality gate tests**

Tests must reject broad href click, invalid Python script, runtime AI without structured outputs, and deterministic scripts that call LLM.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_artifact_quality.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement quality gate**

Return structured `ArtifactQualityResult` with `passed`, `failure_class`, `failure_type`, `message`, and `repair_hint`.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_artifact_quality.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/artifact_quality.py RpaClaw/backend/tests/test_rpa_artifact_quality.py
git commit -m "feat: add rpa artifact quality gate"
```

---

### Task 6: Contract Compiler

**Files:**
- Create: `RpaClaw/backend/rpa/contract_compiler.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_compiler.py`

- [ ] **Step 1: Write failing compiler tests**

Cover:

- primitive navigate from `{selected_project.url}/pulls`;
- deterministic GitHub max-stars extraction artifact;
- deterministic PR record extraction artifact;
- runtime semantic select artifact with structured output contract.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_compiler.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement compiler**

Compiler must use controlled patterns before any free-form code:

- `navigate`
- `extract_repeated_records`
- `rank_collection_numeric_max`
- `runtime_semantic_select`
- `fill_form_fields`

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_compiler.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_compiler.py RpaClaw/backend/tests/test_rpa_contract_compiler.py
git commit -m "feat: add rpa contract compiler"
```

---

### Task 7: Contract Executor

**Files:**
- Create: `RpaClaw/backend/rpa/contract_executor.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_executor.py`

- [ ] **Step 1: Write failing executor tests**

Use fake page objects to verify:

- primitive navigate resolves blackboard template;
- deterministic script writes blackboard output;
- runtime AI result is schema-validated and written to blackboard;
- runtime AI direct side effect is rejected unless allowed.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_executor.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement executor**

Executor should return structured `ExecutionResult` and never commit steps directly.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_executor.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_executor.py RpaClaw/backend/tests/test_rpa_contract_executor.py
git commit -m "feat: add rpa contract executor"
```

---

### Task 8: RecordingValidator and ReplayValidator

**Files:**
- Create: `RpaClaw/backend/rpa/contract_validator.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_validator.py`

- [ ] **Step 1: Write failing validator tests**

Cover:

- `[]` fails when min records required;
- `Navigation Menu` fails `not_generic_chrome_text`;
- URL validation succeeds;
- blackboard key validation succeeds;
- replay structural validation catches missing input refs and regenerated description-only artifacts.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_validator.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement validators**

Implement:

- `validate_recording_step(contract, artifact, execution_result, blackboard, snapshot)`
- `validate_replay_export(committed_steps, exported_manifest)`

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_validator.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_validator.py RpaClaw/backend/tests/test_rpa_contract_validator.py
git commit -m "feat: add rpa contract validators"
```

---

### Task 9: Contract Pipeline and AttemptRecord

**Files:**
- Create: `RpaClaw/backend/rpa/contract_pipeline.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Cover:

- successful attempt commits `StepContract + Artifact + ValidationEvidence`;
- artifact quality failure produces attempt record and does not commit;
- validation failure routes back with `failure_class=validation_failed`;
- snapshot stale failure requests recapture and does not ask compiler to guess.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_pipeline.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement pipeline**

Implement a small orchestration object. It should accept injected planner/compiler/executor/validator callables for testability.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_pipeline.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_pipeline.py RpaClaw/backend/tests/test_rpa_contract_pipeline.py
git commit -m "feat: add rpa contract pipeline"
```

---

### Task 10: Contract-first Skill Builder

**Files:**
- Create: `RpaClaw/backend/rpa/contract_skill_builder.py`
- Modify: `RpaClaw/backend/rpa/skill_exporter.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_skill_builder.py`

- [ ] **Step 1: Write failing export tests**

Cover:

- `skill.contract.json` is written;
- `skill.py` contains committed deterministic artifact code;
- exported script resolves blackboard refs dynamically;
- exported script does not regenerate from description;
- ReplayValidator catches missing committed step.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_skill_builder.py -p no:cacheprovider`

Expected: import failure.

- [ ] **Step 3: Implement Skill Builder**

Generated `skill.py` must include:

- blackboard initialization;
- committed artifact functions;
- runtime AI helper import only when a runtime AI artifact exists;
- step-level error reporting;
- optional debug validation.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_skill_builder.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/contract_skill_builder.py RpaClaw/backend/rpa/skill_exporter.py RpaClaw/backend/tests/test_rpa_contract_skill_builder.py
git commit -m "feat: export contract-first rpa skills"
```

---

### Task 11: Recorder Integration

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Test: `RpaClaw/backend/tests/test_rpa_contract_recorder_integration.py`

- [ ] **Step 1: Write failing integration tests**

Cover:

- route/session calls contract-first pipeline when enabled;
- legacy ReAct path remains available for compatibility;
- committed steps update recorder UI payload with strategy, contract id, validation summary;
- failed attempts are not returned as recorded steps.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_recorder_integration.py -p no:cacheprovider`

Expected: failures due missing integration.

- [ ] **Step 3: Implement integration**

Add a feature flag such as `RPA_AGENT_MODE=contract` with default set to contract after tests pass. Keep legacy mode available as `legacy_react`.

- [ ] **Step 4: Run tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_recorder_integration.py -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/assistant.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_contract_recorder_integration.py
git commit -m "feat: integrate contract-first rpa recorder"
```

---

### Task 12: Full Scenario Regression Tests

**Files:**
- Create: `RpaClaw/backend/tests/test_rpa_contract_full_scenarios.py`

- [ ] **Step 1: Write full scenario tests using fakes**

Cover:

- GitHub Trending max-star deterministic flow.
- GitHub Trending SKILL semantic selection plus PR extraction flow.
- Cross-page extraction and fill dataflow flow.

The tests should assert:

- deterministic flow exports no runtime AI call;
- semantic flow has one runtime AI artifact that writes `selected_project`;
- following PR navigation uses `{selected_project.url}/pulls`;
- PR extraction result writes `pr_list`;
- exported manifest preserves artifacts and validation policies.

- [ ] **Step 2: Run failing tests**

Run: `set PYTHONPATH=RpaClaw && python -m pytest RpaClaw/backend/tests/test_rpa_contract_full_scenarios.py -p no:cacheprovider`

Expected: failures until integration is complete.

- [ ] **Step 3: Fix scenario integration failures by contract layer**

If a scenario fails, repair the layer named by the failing assertion:

- Missing blackboard key: update `contract_executor.py` to write the artifact output through `Blackboard.write`.
- Lost `input_refs`: update `contract_skill_builder.py` to serialize refs into `skill.contract.json` and generated `skill.py`.
- Runtime AI output is natural language only: update the RuntimeAIArtifact compiler/executor path to require `outputs.schema` JSON and reject plain text.
- Deterministic flow calls runtime AI: update the test planner fixture and `contract_compiler.py` to use `deterministic_script` for numeric ranking contracts.
- Exported script hard-codes a selected project URL: update `contract_skill_builder.py` to emit `resolve_template("{selected_project.url}/pulls", board)`.

Do not add local semantic keyword classifiers. If a test requires new semantics, add explicit contract fields and planner output handling.

- [ ] **Step 4: Run full contract test suite**

Run:

```bash
set PYTHONPATH=RpaClaw && python -m pytest ^
  RpaClaw/backend/tests/test_rpa_contract_models.py ^
  RpaClaw/backend/tests/test_rpa_blackboard.py ^
  RpaClaw/backend/tests/test_rpa_snapshot_views.py ^
  RpaClaw/backend/tests/test_rpa_locator_compiler.py ^
  RpaClaw/backend/tests/test_rpa_artifact_quality.py ^
  RpaClaw/backend/tests/test_rpa_contract_compiler.py ^
  RpaClaw/backend/tests/test_rpa_contract_executor.py ^
  RpaClaw/backend/tests/test_rpa_contract_validator.py ^
  RpaClaw/backend/tests/test_rpa_contract_pipeline.py ^
  RpaClaw/backend/tests/test_rpa_contract_skill_builder.py ^
  RpaClaw/backend/tests/test_rpa_contract_recorder_integration.py ^
  RpaClaw/backend/tests/test_rpa_contract_full_scenarios.py ^
  -p no:cacheprovider
```

Expected: all contract-first tests pass.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/tests/test_rpa_contract_full_scenarios.py RpaClaw/backend/rpa RpaClaw/backend/route/rpa.py
git commit -m "test: cover contract-first rpa full scenarios"
```

---

### Task 13: Final Verification and Documentation Update

**Files:**
- Modify: `docs/superpowers/specs/2026-04-18-rpa-contract-first-sop-compiler-design.md` if implementation decisions differ.
- Modify: `RpaClaw/backend/tests` only if test command compatibility requires it.

- [ ] **Step 1: Run syntax checks**

Run:

```bash
python -m py_compile ^
  RpaClaw/backend/rpa/contract_models.py ^
  RpaClaw/backend/rpa/blackboard.py ^
  RpaClaw/backend/rpa/snapshot_views.py ^
  RpaClaw/backend/rpa/locator_compiler.py ^
  RpaClaw/backend/rpa/artifact_quality.py ^
  RpaClaw/backend/rpa/contract_compiler.py ^
  RpaClaw/backend/rpa/contract_executor.py ^
  RpaClaw/backend/rpa/contract_validator.py ^
  RpaClaw/backend/rpa/contract_pipeline.py ^
  RpaClaw/backend/rpa/contract_skill_builder.py
```

Expected: exit code 0.

- [ ] **Step 2: Run diff check**

Run: `git diff --check`

Expected: exit code 0.

- [ ] **Step 3: Run targeted existing regression tests**

Run:

```bash
set PYTHONPATH=RpaClaw && python -m pytest ^
  RpaClaw/backend/tests/test_rpa_generator.py ^
  RpaClaw/backend/tests/test_rpa_assistant_runtime_locators.py ^
  -p no:cacheprovider
```

Expected: existing generator and locator tests pass.

- [ ] **Step 4: Update design doc only if implementation diverged**

If an implementation decision differs from the spec, update the spec with the final decision and the reason. Do not leave the spec stale.

- [ ] **Step 5: Final commit**

```bash
git add docs/superpowers/specs/2026-04-18-rpa-contract-first-sop-compiler-design.md RpaClaw/backend
git commit -m "chore: finalize contract-first rpa compiler"
```

---

## Self-Review Checklist

- The plan implements the five complete core scenarios from the spec.
- The plan directly addresses recording-time operation failures through Artifact Quality Gate and controlled compiler patterns.
- The plan directly addresses recording-success/replay-failure through committed artifacts and replay equivalence checks.
- Runtime AI is structured and writes blackboard data.
- Cross-step dataflow uses typed blackboard refs.
- Local rules are limited to guardrails and validation, not semantic planning.
- The exported Skill runtime does not run the SOP Planner or Step Compiler.
