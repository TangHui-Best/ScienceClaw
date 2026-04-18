# RPA Contract-first SOP-to-SKILL Compiler Design

Date: 2026-04-18

## 1. Background

The RPA recorder is evolving from a browser-control assistant into a SOP-to-SKILL compiler.

The product goal is not to make every exported Skill behave like a runtime browser agent. The goal is:

```text
Use AI heavily during recording and compilation.
Export a Skill that runs mostly through deterministic Playwright/Python logic.
Use runtime AI only for steps that genuinely require current-page semantic judgment.
```

The current implementation proved useful capabilities, including structured actions, ai_script, ai_instruction, immediate recording-time execution, DOM snapshot compression, and script generation isolation. However, it also exposed architectural drift:

- Step type selection is split across planner prompts, local heuristics, coercion, repair, generator behavior, and runtime planners.
- Natural-language descriptions are often treated as executable contracts.
- Repair happens too late and often asks the agent to guess another step instead of repairing the failed layer.
- Runtime AI can become a fallback for uncertain logic instead of a clearly justified semantic node.
- Successful recording traces can still export brittle scripts that hard-code recorded URLs, selectors, or entities.

This design resets the architecture around a contract-first compiler pipeline.

## 2. Non-negotiable Principles

1. Contract is the semantic authority.

   `description` is user-facing. Compiler, executor, validator, repair, and Skill export must primarily consume structured contracts.

2. Strategy is planner-owned.

   The Planner chooses `execution_strategy`. Local code may enforce hard guardrails, but must not become the main semantic classifier.

3. Runtime AI is explicit, structured, and expensive.

   Runtime AI is valid for current DOM plus semantic judgment. It must not be a generic fallback. It must produce structured JSON into blackboard.

4. Machine-consumed results must be structured.

   Any value used by later steps, validators, generated scripts, or UI execution state must be JSON-compatible. Natural language is allowed only as `reason`, `summary`, or `explanation`.

5. Commit is validation-gated.

   A step is committed only when the Validator proves the contract was satisfied. "No exception" is not success.

6. Failure evidence is structured.

   Compiler, executor, and validator failures must produce typed evidence that can be passed to the next repair attempt.

7. BaseSnapshot is captured once per page state.

   The system captures one filtered BaseSnapshot and derives in-memory views for planning, compilation, runtime AI, and validation. It must avoid repeatedly fetching the DOM unless the page state changes or the snapshot is stale.

## 3. Core Product Scope

This is not an MVP. The core version must fully support these five product scenarios:

1. Deterministic script main path.

   Dynamic page data plus deterministic rules, such as ranking, filtering, extraction, aggregation, and row pairing, must be carried by deterministic Python Playwright scripts and exported without runtime token use.

2. Runtime semantic step.

   Dynamic page data plus semantic judgment must be supported by runtime AI, but only as an explicit semantic node with structured output written to blackboard.

3. Cross-step dataflow.

   Outputs from previous steps must drive later URLs, fills, extractions, and scripts through typed blackboard references.

4. LocatorCompiler.

   Random IDs, dynamic classes, ambiguous links, scoped rows/cards/forms, and Playwright strict mode must be handled through a controlled locator compiler.

5. Validator.

   Every step must be validated against contract evidence, including URL changes, schema validation, visible locators, record quality, page state changes, or modal state.

The following areas are reserved in schema but not fully implemented in this core:

- pagination_policy
- control_flow
- risk_policy
- frame_policy
- file_policy
- human_checkpoint
- retry_policy

Reserved fields must not become half-working product behavior. They exist to prevent future schema-breaking rewrites.

## 4. System Architecture

The pipeline is:

```text
User SOP
-> BaseSnapshot capture
-> SOP Planner proposes StepContract
-> SnapshotView derivation
-> Step Compiler generates Artifact
-> Execution Sandbox executes candidate Artifact
-> Validator checks evidence
-> Committer stores only validated steps
-> Skill Builder exports skill.py + skill.contract.json
```

### 4.1 SOP Planner

Responsibilities:

- Understand the global SOP goal.
- Propose one step contract at a time.
- Choose `execution_strategy`.
- Define input references, output contracts, validation policy, and runtime policy.
- Revise the same contract when given structured failure evidence.

The Planner does not generate final Playwright scripts directly.

### 4.2 Snapshot Service

Responsibilities:

- Capture one BaseSnapshot from the current page state.
- Filter noise such as script/style/svg/hidden nodes.
- Preserve interaction-relevant, extraction-relevant, form-relevant, semantic, and validation-relevant data.
- Derive in-memory SnapshotViews.
- Decide when the snapshot is stale.

### 4.3 Step Compiler

Responsibilities:

- Consume StepContract, SnapshotView, and blackboard schema.
- Compile one Artifact for the chosen strategy.
- Use controlled Playwright patterns.
- Never reinterpret business semantics from `description` when contract fields exist.

Artifacts:

- PrimitiveActionArtifact
- DeterministicScriptArtifact
- RuntimeAIArtifact

### 4.4 Execution Sandbox

Responsibilities:

- Execute compiled artifacts during recording/test/export runtime.
- Return structured execution evidence.
- Avoid committing anything directly.

### 4.5 Validator

Responsibilities:

- Validate contract evidence.
- Validate output schema.
- Validate blackboard writes.
- Classify failure type.
- Decide if a step is committable.

### 4.6 Committer

Responsibilities:

- Commit only validated contracts and artifacts.
- Exclude failed attempts, repair traces, and temporary planner thoughts from exported Skill.
- Keep debug evidence available for diagnostics.

### 4.7 Skill Builder

Responsibilities:

- Export `skill.py`.
- Export `skill.contract.json`.
- Preserve deterministic runtime behavior.
- Keep runtime AI calls only for RuntimeAIArtifact nodes.

## 5. StepContract v1

```json
{
  "id": "step_2",
  "description": "Open the selected repository pull requests page",
  "step_goal": "open_selected_repo_prs",
  "operation": "navigate",
  "execution_strategy": "primitive_action",
  "page_scope": {
    "type": "current_page"
  },
  "input_refs": ["selected_project.url"],
  "params": {
    "url_template": "{selected_project.url}/pulls"
  },
  "selection_rule": null,
  "locator_contract": null,
  "output_contract": null,
  "validation_policy": {
    "must": [
      {"type": "url_contains", "value": "/pulls"}
    ]
  },
  "runtime_policy": {
    "requires_runtime_ai": false,
    "runtime_ai_reason": ""
  },
  "risk_policy": {
    "side_effect_level": "low",
    "confirmation_required": false
  },
  "reserved": {
    "pagination_policy": null,
    "control_flow": null,
    "frame_policy": null,
    "file_policy": null,
    "human_checkpoint": null,
    "retry_policy": null
  }
}
```

### 5.1 Execution Strategy

Allowed values:

- `primitive_action`
- `deterministic_script`
- `runtime_ai`

Local hard guardrails:

- `primitive_action` cannot carry ranking, batch extraction, aggregation, cross-element pairing, or multi-record collection.
- `deterministic_script` cannot carry a contract that explicitly requires runtime semantic judgment.
- `runtime_ai` must provide `runtime_ai_reason` and structured `output_contract`.

The system does not implement a local strategy fallback engine. If the chosen strategy fails validation, structured failure evidence is returned to the Planner, which revises the same contract.

## 6. RuntimeAIArtifact and Structured Output

Runtime AI is allowed when correctness depends on runtime DOM plus semantic judgment.

Runtime AI must output structured JSON to blackboard. Natural language may appear only as fields such as `reason`, `summary`, or `explanation`.

Example contract:

```json
{
  "id": "step_1",
  "description": "Find the GitHub Trending repository most related to SKILL",
  "step_goal": "select_skill_related_project",
  "operation": "select",
  "execution_strategy": "runtime_ai",
  "page_scope": {
    "type": "visible_collection",
    "collection": "github_trending_repositories"
  },
  "selection_rule": {
    "type": "semantic_relevance",
    "query": "SKILL",
    "fields": ["repo_name", "description"]
  },
  "output_contract": {
    "blackboard_key": "selected_project",
    "schema": {
      "owner": "string",
      "repo": "string",
      "full_name": "string",
      "url": "url",
      "reason": "string"
    }
  },
  "runtime_policy": {
    "requires_runtime_ai": true,
    "runtime_ai_reason": "The selection depends on semantic relevance, not only exact text matching."
  },
  "validation_policy": {
    "must": [
      {"type": "blackboard_key_exists", "ref": "selected_project.url"},
      {"type": "url_like", "ref": "selected_project.url"}
    ]
  }
}
```

Required output:

```json
{
  "selected_project": {
    "owner": "SimoneAvogadro",
    "repo": "android-reverse-engineering-skill",
    "full_name": "SimoneAvogadro/android-reverse-engineering-skill",
    "url": "https://github.com/SimoneAvogadro/android-reverse-engineering-skill",
    "reason": "The repository name and description are most relevant to SKILL."
  }
}
```

Later steps must consume blackboard fields, not natural-language explanations.

## 7. Blackboard v1

The blackboard is the typed memory layer between steps.

```json
{
  "values": {
    "selected_project": {
      "owner": "SimoneAvogadro",
      "repo": "android-reverse-engineering-skill",
      "full_name": "SimoneAvogadro/android-reverse-engineering-skill",
      "url": "https://github.com/SimoneAvogadro/android-reverse-engineering-skill",
      "reason": "..."
    },
    "pr_list": [
      {"title": "Add wttr.in to Weather APIs", "creator": "puneetrwtz"}
    ]
  },
  "schema": {
    "selected_project.url": "url",
    "pr_list": "array<object>"
  },
  "runtime_params": {}
}
```

Rules:

- Every machine-consumed output must be written to blackboard.
- Later steps reference values through `input_refs`.
- Generated scripts must resolve refs deterministically.
- Natural-language history is not a data source.

Example deterministic follow-up:

```json
{
  "id": "step_2",
  "step_goal": "open_selected_project_pulls",
  "operation": "navigate",
  "execution_strategy": "primitive_action",
  "input_refs": ["selected_project.url"],
  "params": {
    "url_template": "{selected_project.url}/pulls"
  }
}
```

Generated script pattern:

```python
repo_url = results["selected_project"]["url"].rstrip("/")
await page.goto(f"{repo_url}/pulls", wait_until="domcontentloaded")
```

## 8. BaseSnapshot and SnapshotViews v1

### 8.1 BaseSnapshot

BaseSnapshot is captured once per page state and filtered at source.

It should include:

- url
- title
- frame summary
- actionable nodes
- content nodes
- repeated collections
- form controls
- table/list/card structures
- locator candidates
- accessibility role/name data
- visibility, enabled state, bbox, and hierarchy
- stable hrefs and URL patterns
- compact main content summary

It should exclude or compress:

- script/style/svg
- hidden noise
- tracking pixels
- massive raw text blobs
- unstable generated IDs when better semantic identifiers exist
- repeated decorative nodes

### 8.2 SnapshotViews

Derived in memory:

- `overview_view`: compact page summary for Planner.
- `action_view`: interactive nodes for primitive actions and LocatorCompiler.
- `extraction_view`: lists, tables, cards, repeated structures for deterministic scripts.
- `semantic_view`: main content and semantic snippets for runtime AI.
- `form_view`: labels, inputs, placeholders, validation errors.
- `validation_view`: URL, title, key locators, output evidence.

DOM is recaptured only when:

- navigation occurs
- user manually changes page state
- artifact execution materially changes DOM
- Validator marks snapshot as stale
- the next contract explicitly requires fresh page state

## 9. LocatorCompiler v1

LocatorCompiler converts locator contracts and snapshot nodes into stable Playwright locators.

Priority:

1. testid, data-testid, data-cy
2. role plus accessible name
3. label, placeholder, alt, title
4. text within scoped container
5. row/card/form scoped locator
6. stable exact href or URL pattern
7. structural CSS
8. nth or coordinate fallback with diagnostic reason

Rules:

- Do not prefer random IDs or dynamic classes.
- Do not click broad contains href selectors such as `a[href*="owner/repo"]`.
- Use exact href or direct `goto` for stable navigation targets.
- Treat Playwright strict mode violation as `locator_ambiguous`.
- For row/card actions, locate the container first, then locate the target inside it.
- Store locator candidates and selected candidate rationale.

## 10. DeterministicScriptArtifact v1

Deterministic scripts are for dynamic page data plus deterministic rules.

Examples:

- find max star count
- extract first 10 PR titles and creators
- filter rows by explicit status
- compare dates
- pair fields inside repeated cards
- navigate using a URL from blackboard
- fill fields from blackboard values

Rules:

- Use Python Playwright by default.
- Avoid JavaScript and `page.evaluate` unless explicitly justified.
- Prefer scoped locators over global selectors.
- Return JSON-compatible output matching `output_contract`.
- Do not hard-code recorded entities unless the contract marks them fixed.
- Do not use LLM at exported Skill runtime.

## 11. Validator v1

ValidationPolicy supports:

- `url_matches`
- `url_contains`
- `locator_visible`
- `locator_count`
- `page_changed`
- `modal_opened`
- `output_schema_valid`
- `blackboard_key_exists`
- `min_valid_records`
- `not_generic_chrome_text`

ValidationResult:

```json
{
  "status": "passed",
  "stage": "validator",
  "evidence": [
    {"type": "url_contains", "expected": "/pulls", "actual": "https://github.com/x/y/pulls"},
    {"type": "output_schema_valid", "ref": "pr_list"}
  ]
}
```

Failure example:

```json
{
  "status": "failed",
  "stage": "validator",
  "failure_type": "output_schema_invalid",
  "message": "Expected a non-empty array of PR records with title and creator.",
  "details": {
    "ref": "pr_list",
    "actual": [],
    "required_fields": ["title", "creator"]
  },
  "repair_hint": "Compile a row-scoped PR extraction script against the current pull request list."
}
```

## 12. AttemptRecord and Failure Evidence

Every compile/execute/validate attempt produces an AttemptRecord.

```json
{
  "attempt_id": "step_3_attempt_1",
  "step_id": "step_3",
  "contract": {},
  "strategy": "deterministic_script",
  "snapshot_id": "snapshot_123",
  "artifact": {},
  "compile_result": {},
  "execution_result": {},
  "validation_result": {},
  "failure_evidence": {},
  "next_action": "repair_artifact"
}
```

Failure taxonomy:

- `contract_bad`
- `strategy_guardrail_violation`
- `snapshot_stale`
- `locator_not_found`
- `locator_ambiguous`
- `script_compile_error`
- `script_runtime_error`
- `runtime_ai_output_invalid`
- `runtime_ai_action_missing`
- `validation_failed`
- `permission_or_login_required`
- `user_intervention_required`

Repair routing:

- `contract_bad`: Planner revises contract.
- `strategy_guardrail_violation`: Planner revises strategy in contract.
- `snapshot_stale`: recapture BaseSnapshot.
- `locator_not_found` or `locator_ambiguous`: LocatorCompiler repairs artifact.
- `script_compile_error` or `script_runtime_error`: ScriptCompiler repairs artifact.
- `runtime_ai_output_invalid`: RuntimeAI compiler/prompt repairs schema output.
- `validation_failed`: Planner or Compiler repairs based on evidence.

The second compiler attempt receives structured failure evidence, not only a natural-language error string.

## 13. Exported Skill Runtime

The exported Skill contains:

```text
skill.py
skill.contract.json
optional debug metadata
```

Runtime behavior:

- Primitive actions run directly.
- Deterministic scripts run directly.
- Runtime AI nodes call LLM only for those nodes.
- Blackboard is initialized from runtime parameters and previous step outputs.
- Validation can run in normal or debug mode.

The generated `skill.py` should be driven by exported contract metadata where practical, rather than hand-expanded traces only.

## 14. GitHub Validation Scenarios

### Scenario A: Deterministic ranking

User goal:

```text
Open https://github.com/trending, find the project with the most stars, open latest issue, extract title.
```

Expected design:

- navigate to trending: primitive_action
- find max stars: deterministic_script
- open issues from selected repo URL: primitive_action using blackboard
- extract latest issue title: deterministic_script or primitive extract if stable
- no runtime AI required

### Scenario B: Runtime semantic selection with deterministic continuation

User goal:

```text
Open GitHub Trending, find the project most related to SKILL, open its PR page, collect first 10 PR title and creator.
```

Expected design:

- navigate to trending: primitive_action
- select most SKILL-related project: runtime_ai with structured `selected_project`
- open PR page: primitive_action using `{selected_project.url}/pulls`
- collect PR records: deterministic_script

### Scenario C: Cross-step extraction and fill

User goal:

```text
Extract data from page A and fill corresponding fields on page B.
```

Expected design:

- extraction step writes typed values into blackboard
- navigation step opens page B
- fill step consumes blackboard refs
- validation checks field values or success state

## 15. Migration Plan

Phase 1: Add contract-first data models alongside existing RPA models.

Phase 2: Implement BaseSnapshot and SnapshotView adapter over the existing snapshot code.

Phase 3: Implement Planner output contract and disable local semantic step-type coercion in the new pipeline.

Phase 4: Implement Compiler for primitive_action and deterministic_script.

Phase 5: Implement RuntimeAIArtifact with mandatory structured blackboard output.

Phase 6: Implement Validator and AttemptRecord.

Phase 7: Export `skill.contract.json` and update `skill.py` generation to consume blackboard refs.

Phase 8: Gate old ReAct path behind compatibility mode and make contract-first the default RPA Agent path.

## 16. Open Decisions

Resolved:

- Runtime AI must output structured JSON into blackboard.
- Natural language cannot be the only machine-consumed output.
- Strategy is planner-owned; local code only applies hard guardrails.
- DOM uses one BaseSnapshot with in-memory views, not multiple browser DOM captures per step.
- The core version fully implements five core scenarios, not an MVP subset.

Still to decide before implementation:

1. Exact Pydantic model names and file placement.
2. Whether `skill.contract.json` is mandatory for all exported Skills or only contract-first Skills.
3. How much validation should run during normal exported Skill execution versus debug/test mode.
4. Whether old recorded sessions should be migrated or only new sessions use contract-first pipeline.

