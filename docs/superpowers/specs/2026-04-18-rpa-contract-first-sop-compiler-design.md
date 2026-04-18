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

8. The exported Skill is already compiled.

   `skill.py` is the runtime execution authority. `skill.contract.json` is the semantic/debug/regeneration authority. Normal Skill execution must not re-run the SOP Planner or Step Compiler.

9. Runtime AI should decide, not click, by default.

   Runtime AI should normally produce structured decisions or extracted values. Browser side effects after semantic decisions should be materialized by deterministic follow-up steps whenever practical.

10. Architecture must resist heuristic creep.

    Local rules may reject impossible contracts, validate evidence, normalize obvious syntax, or protect against unsafe actions. Local rules must not become a hidden semantic planner.

## 2.1 Requirements Traceability

The architecture is justified only if it satisfies these product requirements:

| Requirement | Architectural response |
| --- | --- |
| Convert SOP into reusable Skill | StepContract + Artifact + Skill Builder |
| Minimize runtime token cost | deterministic `skill.py` as default; runtime AI only for explicit nodes |
| Support dynamic page data | deterministic scripts can read current DOM at runtime without LLM |
| Support runtime semantic judgment | RuntimeAIArtifact with structured blackboard output |
| Support cross-step dependencies | typed blackboard + `input_refs` |
| Survive random DOM ids/classes | BaseSnapshot evidence + LocatorCompiler |
| Avoid "recorded OK, replay broken" | Validator-gated commit + exported contract metadata |
| Avoid repeated architectural rewrites | hard invariants, failure taxonomy, versioned schemas |

If a future change improves one requirement by violating another, it must be treated as an architectural review item, not a local bug fix.

## 2.2 Heavyweight Architecture Deviations

These are red lines. If implementation starts drifting toward any of them, the team should stop and review the design before adding another patch.

1. Runtime Skill execution becomes an agent loop.

   A Skill may call runtime AI inside explicit RuntimeAIArtifact nodes, but normal execution must not ask a planner to rediscover the SOP.

2. `description` becomes the primary input to compiler or validator.

   Descriptions are for humans. Machine behavior must be driven by StepContract fields.

3. Local keyword rules start choosing business semantics.

   Local rules may enforce guardrails but must not decide that "most related" means keyword matching, or that a field should be extracted because a Chinese word appeared in a sentence.

4. Failed attempts are committed as steps.

   Only validated contracts and artifacts are committed. Failed attempts remain diagnostics.

5. Runtime AI directly performs browser side effects when a decision-plus-deterministic-action split is possible.

   This reintroduces selector instability and token-heavy runtime behavior.

6. Snapshot views discard evidence needed by compiler or validator.

   LLM-facing views may be compressed. Local evidence used for locator compilation and validation must remain structured and traceable.

7. Skill export hard-codes runtime-selected entities without a fixed-entity contract.

   Recorded URLs, selected repos, row values, and similar entities must flow through blackboard unless the contract explicitly declares them fixed.

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

## 3.1 Primary Failure Modes to Eliminate

The design is not complete unless it directly eliminates the two historical failure modes observed in prior versions.

### Failure mode A: recording-time browser operation fails repeatedly

Symptoms:

- The Agent understands the instruction but generated code cannot operate the page reliably.
- Generated Playwright code has unstable selectors, bad waits, invalid `page.evaluate` JavaScript, or brittle DOM assumptions.
- Repair repeats the same guessing pattern with slightly different code.

Architectural response:

- Compiler must be contract-driven, not free-form description-driven.
- Deterministic scripts should prefer controlled templates and Playwright best practices over unrestricted code generation.
- Artifact Quality Gate must reject obviously brittle or invalid artifacts before execution.
- Failure evidence must point repair to the failing layer, such as locator, wait condition, output schema, or script syntax.

### Failure mode B: recording succeeds but exported replay fails

Symptoms:

- The recording-time action completes, but generated `skill.py` cannot replay the same behavior.
- Export regenerates behavior from descriptions instead of preserving the validated artifact.
- Dynamic values selected during recording are accidentally hard-coded into replay scripts.
- Replay loses blackboard refs, validation policy, locator candidates, or runtime AI output schema.

Architectural response:

- The committed unit is `StepContract + Artifact + ValidationEvidence`, not only a step description.
- Skill Builder wraps committed artifacts; it must not re-plan or regenerate behavior from natural language.
- Export must preserve blackboard refs, runtime parameters, validation policy, and runtime AI output schemas.
- Recording-to-replay equivalence must be checked before a Skill is considered testable.

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
- Propose one step contract at a time through a structured planner envelope.
- Choose `execution_strategy` as part of the step operator.
- Define input references, output contracts, validation policy, and runtime policy in separate fields.
- Revise the same contract when given structured failure evidence.

The Planner does not generate final Playwright scripts directly.

Planner output envelope:

```json
{
  "sop_context": {
    "global_goal": "Open GitHub Trending, select the SKILL-related repo, collect PR records",
    "final_outputs": ["pr_list"],
    "known_constraints": ["output PR records as a strict array"]
  },
  "current_step": {
    "intent": {},
    "inputs": {},
    "target": {},
    "operator": {},
    "outputs": {},
    "validation": {}
  },
  "strategy_rationale": {
    "execution_strategy": "deterministic_script",
    "reason": "The task is deterministic extraction from repeated PR rows."
  },
  "dataflow_updates": {
    "new_blackboard_keys": ["pr_list"],
    "consumed_blackboard_keys": ["selected_project.url"]
  }
}
```

The envelope may be produced by one LLM call, but the fields must remain separate so failures can be routed precisely. For example, an invalid output schema is not the same problem as a wrong business intent.

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
- Prefer templates and constrained code generation for common browser automation patterns.
- Produce artifact metadata needed for export equivalence checks.

Artifacts:

- PrimitiveActionArtifact
- DeterministicScriptArtifact
- RuntimeAIArtifact

Controlled compiler patterns:

- navigate by resolved URL or URL template
- click by LocatorCompiler-selected locator
- fill by field mapping and blackboard refs
- extract one field from locator
- extract repeated records from scoped rows/cards
- rank/filter repeated records by deterministic rule
- build URL from blackboard ref
- runtime semantic select/extract with structured output

Free-form Playwright code generation is reserved for cases that do not fit a controlled pattern and must carry an explicit compiler rationale.

### 4.4 Execution Sandbox

Responsibilities:

- Execute compiled artifacts during recording/test/export runtime.
- Return structured execution evidence.
- Avoid committing anything directly.

### 4.5 Validator

Responsibilities:

- Validate recording-time contract evidence.
- Validate output schema.
- Validate blackboard writes.
- Classify failure type.
- Decide if a step is committable.

There are two validation moments:

- RecordingValidator: validates a candidate artifact against the current recording page before commit.
- ReplayValidator: validates that exported `skill.py` preserves committed artifacts, dataflow, and validation policy, and can run in the test/replay environment.

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
  "intent": {
    "goal": "open_selected_repo_prs",
    "business_object": "github_repository",
    "user_visible_summary": "Open the PR page for the repository selected by the previous step"
  },
  "inputs": {
    "refs": ["selected_project.url"],
    "params": {}
  },
  "target": {
    "type": "url",
    "url_template": "{selected_project.url}/pulls"
  },
  "operator": {
    "type": "navigate",
    "execution_strategy": "primitive_action"
  },
  "outputs": {
    "blackboard_key": null,
    "schema": null
  },
  "validation": {
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

Field ownership:

- `intent`: business meaning and user-visible purpose.
- `inputs`: blackboard references and runtime parameters required by this step.
- `target`: the object, URL, collection, form field, row, card, or semantic scope this step operates on.
- `operator`: the action family and execution strategy.
- `outputs`: blackboard write contract.
- `validation`: evidence required before commit.

`operation` and `params` should not become catch-all fields. If a new behavior does not fit the six blocks above, it should trigger schema review instead of being stuffed into generic metadata.

### 5.1 Execution Strategy

Allowed values:

- `primitive_action`
- `deterministic_script`
- `runtime_ai`

Local hard guardrails:

- `primitive_action` cannot carry ranking, batch extraction, aggregation, cross-element pairing, or multi-record collection.
- `deterministic_script` cannot carry a contract that explicitly requires runtime semantic judgment.
- `runtime_ai` must provide `runtime_ai_reason` and structured `outputs`.

The system does not implement a local strategy fallback engine. If the chosen strategy fails validation, structured failure evidence is returned to the Planner, which revises the same contract.

## 6. RuntimeAIArtifact and Structured Output

Runtime AI is allowed when correctness depends on runtime DOM plus semantic judgment.

Runtime AI must output structured JSON to blackboard. Natural language may appear only as fields such as `reason`, `summary`, or `explanation`.

Default RuntimeAI operators:

- `semantic_select`
- `semantic_extract`
- `semantic_classify`
- `semantic_summarize`

RuntimeAI should not directly perform browser side effects by default. If the semantic result can be represented as structured data, the next browser operation should be a deterministic follow-up step.

Preferred pattern:

```text
RuntimeAIArtifact: choose selected_project and write selected_project.url
PrimitiveActionArtifact: navigate to {selected_project.url}
DeterministicScriptArtifact: extract PR records from the selected project
```

Discouraged pattern:

```text
RuntimeAIArtifact: choose selected_project and click it inside the same runtime AI plan
```

Direct runtime AI side effects are allowed only when all are true:

- the target cannot be represented as structured data for a deterministic follow-up;
- the browser action itself depends on current semantic interpretation;
- the contract explicitly sets `runtime_policy.allow_side_effect = true`;
- the contract includes `runtime_policy.side_effect_reason`;
- validation evidence proves the side effect happened.

Example contract:

```json
{
  "id": "step_1",
  "description": "Find the GitHub Trending repository most related to SKILL",
  "intent": {
    "goal": "select_skill_related_project",
    "business_object": "github_repository"
  },
  "inputs": {
    "refs": [],
    "params": {"query": "SKILL"}
  },
  "target": {
    "type": "visible_collection",
    "collection": "github_trending_repositories",
    "fields": ["repo_name", "description"]
  },
  "operator": {
    "type": "semantic_select",
    "execution_strategy": "runtime_ai",
    "selection_rule": {
      "type": "semantic_relevance",
      "query": "SKILL",
      "fields": ["repo_name", "description"]
    }
  },
  "outputs": {
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
    "runtime_ai_reason": "The selection depends on semantic relevance, not only exact text matching.",
    "allow_side_effect": false
  },
  "validation": {
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
  "description": "Open the selected project pull requests page",
  "intent": {
    "goal": "open_selected_project_pulls",
    "business_object": "github_repository"
  },
  "inputs": {
    "refs": ["selected_project.url"],
    "params": {}
  },
  "target": {
    "type": "url",
    "url_template": "{selected_project.url}/pulls"
  },
  "operator": {
    "type": "navigate",
    "execution_strategy": "primitive_action"
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

BaseSnapshot has two layers:

1. `evidence`

   Structured local evidence used by LocatorCompiler, ScriptCompiler, Validator, and debug tooling. This layer may be larger than the LLM-facing views and must preserve enough information to compile and validate reliably.

2. `views`

   Budgeted projections derived from evidence for specific consumers. These are optimized for LLM context control and human-readable diagnostics.

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

Evidence preservation requirements:

- Preserve stable node identifiers inside the snapshot.
- Preserve locator candidates, not only the selected locator.
- Preserve href, role, accessible name, visible text excerpt, bbox, visibility, enabled state, and frame path.
- Preserve repeated collection structure and sample items.
- Preserve form label/control relationships.
- Preserve enough ancestry to support scoped locators.

View budget guidance:

```json
{
  "overview_view": {"token_budget": 4000},
  "action_view": {"max_nodes": 120},
  "extraction_view": {"max_collections": 8, "max_items_per_collection": 25},
  "semantic_view": {"token_budget": 8000},
  "form_view": {"max_fields": 100},
  "validation_view": {"max_evidence_items": 50}
}
```

Budgets are not correctness rules. If a page exceeds a budget, the view must include truncation metadata so the Planner or Compiler can request a fresh or focused snapshot when needed.

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
- Return JSON-compatible output matching the contract `outputs.schema`.
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

## 12. Artifact Quality Gate

Before an artifact is executed during recording, it must pass a lightweight quality gate. The gate is not a semantic classifier. It rejects artifacts that are known to cause recording-time failures or replay divergence.

### 12.1 PrimitiveActionArtifact checks

- target locator or URL must be present;
- click/fill/extract locators must come from LocatorCompiler;
- broad href contains selectors are rejected for clicks;
- navigation must have a resolved URL, URL template, or blackboard ref;
- extraction must declare where output will be written if later steps consume it.

### 12.2 DeterministicScriptArtifact checks

- Python code must compile;
- script entrypoint must match the expected signature;
- extraction scripts must return JSON-compatible values matching `outputs.schema`;
- scripts must not call LLMs;
- scripts must not use filesystem, shell, or network unless an explicit future file/network policy allows it;
- scripts should not use `page.evaluate` unless the artifact includes a rationale;
- scripts must preserve blackboard refs instead of hard-coding runtime-selected values;
- scripts must include enough waits or locator-based synchronization for navigation or dynamic content.

### 12.3 RuntimeAIArtifact checks

- `runtime_ai_reason` must be present;
- `outputs.blackboard_key` and `outputs.schema` must be present;
- side effects are disallowed unless `runtime_policy.allow_side_effect` is true and justified;
- runtime AI prompt must require JSON output conforming to `outputs.schema`;
- runtime AI result must be validated before being written to blackboard.

Artifacts that fail the quality gate return `failure_class = artifact_failed` with a specific `failure_type`, such as `script_compile_error`, `locator_ambiguous`, or `runtime_ai_output_invalid`.

## 13. Recording-to-Replay Equivalence

Recording success is insufficient unless the exported Skill preserves the same validated behavior.

The committed unit is:

```text
StepContract + Artifact + ValidationEvidence
```

It is not:

```text
description + generator prompt + best-effort replay code
```

Export rules:

- Skill Builder must wrap committed artifacts, not regenerate behavior from natural-language descriptions.
- Export may add runtime scaffolding such as `main()`, browser setup, blackboard initialization, and step error handling.
- Export must not replace blackboard refs with recording-time concrete values unless the contract declares a fixed value.
- Export must preserve RuntimeAIArtifact output schema.
- Export must preserve validation policy and enough debug metadata to explain failures.
- Export must preserve artifact IDs so replay logs can map failures back to committed steps.

Structural equivalence checks before replay:

- every exported step maps to one committed step ID;
- every committed step has an exported artifact;
- blackboard input refs are preserved;
- outputs schemas are preserved;
- runtime parameters are not replaced by recorded values;
- runtime AI nodes are not expanded into deterministic code unless explicitly recompiled through the compiler pipeline;
- deterministic artifacts are not regenerated from `description`;
- validation policies are present in debug/test mode.

ReplayValidator runs after export and before declaring the Skill testable. It should catch missing refs, lost schemas, hard-coded selected entities, and regenerated behavior before browser replay begins when possible.

## 14. AttemptRecord and Failure Evidence

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
  "failure_evidence": {
    "failure_class": "artifact_failed",
    "failure_type": "locator_ambiguous",
    "stage": "executor",
    "message": "The click locator matched multiple links.",
    "details": {},
    "repair_hint": "Use exact href or direct navigation."
  },
  "next_action": "repair_artifact"
}
```

Core failure classes:

- `contract_invalid`
- `snapshot_stale`
- `artifact_failed`
- `validation_failed`

The orchestration loop routes by `failure_class`, not by dozens of fine-grained failure types.

Fine-grained failure types:

- `strategy_guardrail_violation`
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

- `contract_invalid`: Planner revises contract.
- `snapshot_stale`: recapture BaseSnapshot.
- `artifact_failed`: Compiler repairs artifact using failure evidence.
- `validation_failed`: Validator provides evidence; Planner or Compiler repairs depending on whether the contract or artifact caused the mismatch.

The second compiler attempt receives structured failure evidence, not only a natural-language error string.

## 15. Exported Skill Runtime

The exported Skill contains:

```text
skill.py
skill.contract.json
optional debug metadata
```

Runtime authority:

- `skill.py` is the execution authority.
- `skill.contract.json` is the semantic, debug, regeneration, migration, and review authority.
- Normal Skill execution must not invoke the SOP Planner.
- Normal Skill execution must not invoke the Step Compiler.
- RuntimeAIArtifact nodes may call the runtime semantic executor only for that node.
- The runtime semantic executor must obey the node's structured output contract.

Runtime behavior:

- Primitive actions run directly.
- Deterministic scripts run directly.
- Runtime AI nodes call LLM only for those nodes.
- Blackboard is initialized from runtime parameters and previous step outputs.
- Validation can run in normal or debug mode.

The generated `skill.py` should be driven by exported contract metadata where practical, rather than hand-expanded traces only.

The exported `skill.py` must not rely on reinterpreting natural-language descriptions. If a value is required at runtime, it must come from runtime parameters, blackboard, compiled constants, or the current page.

## 16. GitHub Validation Scenarios

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

## 17. Architectural Invariants for Future Iterations

The following invariants are intended to prevent a third architectural rewrite:

1. New capabilities extend contracts before extending prompt behavior.

   If a future scenario needs pagination, multi-tab handling, downloads, or human confirmation, the contract schema must gain or activate an explicit field before prompts start handling it implicitly.

2. Every new execution behavior must declare its authority.

   It must be clear whether behavior is decided by Planner, Compiler, RuntimeAIArtifact, Skill runtime parameters, or user intervention.

3. Every machine-consumed value has a schema.

   If later code reads it, it belongs in blackboard, runtime params, contract metadata, or validation evidence.

4. Every repair loop has bounded ownership.

   Planner repairs contracts. Compiler repairs artifacts. Snapshot Service refreshes stale observations. Validator reports evidence. No layer should repair another layer by guessing.

5. Every exported Skill should be inspectable.

   A user should be able to inspect the Skill and understand which steps are deterministic, which steps call runtime AI, what data flows between steps, and what validation evidence is expected.

6. Debuggability is product behavior, not developer convenience.

   If a Skill fails, the UI should be able to show the failing step, failure class, failure type, relevant evidence, and suggested repair direction.

## 18. Migration Plan

Phase 1: Add contract-first data models alongside existing RPA models.

Phase 2: Implement BaseSnapshot and SnapshotView adapter over the existing snapshot code.

Phase 3: Implement Planner output contract and disable local semantic step-type coercion in the new pipeline.

Phase 4: Implement Compiler for primitive_action and deterministic_script.

Phase 5: Implement RuntimeAIArtifact with mandatory structured blackboard output.

Phase 6: Implement Validator and AttemptRecord.

Phase 7: Export `skill.contract.json` and update `skill.py` generation to consume blackboard refs.

Phase 8: Gate old ReAct path behind compatibility mode and make contract-first the default RPA Agent path.

## 19. Open Decisions

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
