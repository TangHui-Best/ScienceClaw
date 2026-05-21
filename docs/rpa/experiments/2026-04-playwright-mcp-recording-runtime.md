# Playwright MCP Recording Runtime Experiment

Status: Experimental

Branch scope: future independent exploration branch only.

This document records a second exploratory path for the RPA recording runtime: using Playwright MCP as the primary browser observation and interaction layer. It is not accepted as the mainline RPA architecture yet. Do not change existing RPA contracts, recorder behavior, compiler behavior, or AGENTS.md rules solely because this document exists.

The current baseline remains:

```text
Trace-first Recording + Post-hoc Skill Compilation
```

Related experiment:

- `docs/rpa/experiments/2026-04-snapshot-evidence-store.md`

## Why This Is Worth Exploring

The current RPA recording runtime builds its own page snapshot, compresses it, and asks the planner to generate Python Playwright code from that compressed evidence. Recent failures show that a hand-rolled DOM/snapshot compressor can become fragile when task shape changes.

Playwright MCP may offer a better observation primitive. According to the official Playwright MCP documentation, it exposes browser automation tools through MCP and lets LLMs interact with web pages using structured accessibility snapshots rather than screenshots or raw DOM.

Official references:

- Playwright MCP getting started: <https://playwright.dev/docs/getting-started-mcp>
- Playwright MCP snapshots: <https://playwright.dev/mcp/snapshots>
- Playwright MCP browser automation guide: <https://playwright.dev/agents/playwright-mcp-browser-automation>
- Playwright MCP repository: <https://github.com/microsoft/playwright-mcp>

The important idea is that the LLM sees a user-facing accessibility tree with interactive element refs. It can then call tools such as click/type against those refs during the current page state.

## Hypothesis

Playwright MCP can replace part of our self-built recording-time snapshot compression and interaction layer.

The strongest hypothesis:

```text
For many recording-time natural-language browser operations, accessibility snapshot refs are a better action surface than our custom compact DOM snapshot.
```

If true, this could reduce:

- Custom snapshot compression logic.
- Task-shape-specific filtering bugs.
- Selector hallucination from internal DOM ids.
- Prompt size for common interaction tasks.
- The need to maintain our own actionability projection layer.

## What Must Not Change

This experiment should not change the architectural baseline:

- Recording remains Trace-first.
- Recording executes one current user command, not the whole SOP.
- Accepted traces remain factual records.
- Failed attempts remain diagnostics.
- Post-hoc compilation remains responsible for replay generalization.
- Final `skill.py` must not depend on MCP element refs.
- Runtime AI is preserved only for genuinely semantic replay steps.

## Key MCP Strengths

### Accessibility Snapshot

Playwright MCP snapshots are based on the accessibility tree. This is closer to what a user can perceive and operate than raw DOM.

Advantages:

- Lower noise than raw HTML.
- Roles, labels, names, and text are first-class evidence.
- Interactive elements get refs that can be used by MCP tools.
- Most actions return an updated snapshot after page changes.
- Screenshots can be combined when visual context matters.

### Ref-based Current-page Interaction

MCP refs are useful for the recording-time action itself. The model can choose an element it just saw and act on that exact element.

This avoids a common failure mode in our current planner:

```text
The planner sees text or an internal id, rewrites it into a selector, and the selector is not actually actionable.
```

### Existing Browser Tool Surface

MCP already provides common browser tools such as navigation, click, typing, screenshot, tab handling, and verification tools. This may reduce our need to maintain equivalent recording-time wrappers.

## Critical Boundaries

### MCP Refs Are Not Replay Selectors

MCP element refs are only valid within a current snapshot lifecycle. After navigation or DOM updates, refs are refreshed.

Therefore:

- Refs may be used to complete the recording-time action.
- Refs may be stored as evidence.
- Refs must not be compiled into final replay code.

The compiler still needs stable Playwright code, semantic locators, URL/dataflow generalization, or runtime AI where appropriate.

### Accessibility Snapshot Is Not Full Business Evidence

Accessibility snapshots are strong for visible interaction, but may not capture every fact needed by RPA skills:

- Hidden default values.
- Non-accessible custom widgets.
- Business-specific data attributes.
- Complex virtualized table structure.
- Precise row/column metadata.
- Detail fields rendered without useful accessible names.
- Canvas, charts, image-heavy, or visually encoded pages.

For these cases, Playwright MCP may need to be combined with screenshots, raw snapshot evidence, or targeted Playwright evaluation.

### MCP Is Not a Trace Compiler

MCP can help operate the browser. It does not solve:

- `_results` / `output_key` dataflow.
- Cross-step dependency inference.
- Recording-time observed value de-hardcoding.
- Stable subpage URL generalization.
- Deterministic replay code generation.
- Skill packaging.

Those remain RpaClaw responsibilities.

### Avoid Reintroducing an Open-ended ReAct Loop

Playwright MCP is naturally good at iterative browser-agent loops. That is useful, but it is also the exact shape that previously caused slow recording and low accuracy when used without strict bounds.

This experiment must keep the loop bounded:

```text
snapshot -> plan/action -> execute -> trace
```

At most one bounded repair remains the default policy.

## Industry-practice Notes

The official Playwright MCP docs position accessibility snapshots as the core browser-state representation for LLM interaction. This supports the direction of moving away from raw DOM as the primary model input.

The Playwright MCP repository also distinguishes MCP from CLI/skill workflows. Its README notes that MCP is useful for specialized agentic loops with persistent state and rich introspection, while CLI/skill workflows can be more token-efficient for high-throughput coding agents.

This matters for RpaClaw:

- Our recording runtime is a specialized browser-agent loop, so MCP may fit.
- Our full system is also a trace compiler and skill generator, so MCP should not become the entire architecture.
- Token and latency overhead must be measured, not assumed away.

## Candidate Architectures

### Option A: MCP as Observation Only

Use MCP `browser_snapshot` to get accessibility snapshots, but keep execution through our existing Playwright page/runtime.

Pros:

- Lowest integration risk.
- Lets us compare MCP snapshot quality against our raw/compact snapshot.
- Keeps trace recorder and browser session mostly unchanged.

Cons:

- Must map MCP snapshot evidence back to our Playwright page context.
- Does not fully benefit from ref-based MCP actions.

Use this if the first goal is snapshot quality evaluation.

### Option B: MCP for Recording-time Actions, RpaClaw for Trace and Compilation

Use MCP tools for recording-time browser operation. After each action, convert the MCP action result into RpaClaw accepted traces and diagnostics.

Pros:

- Uses MCP refs for the action surface.
- Reduces custom click/fill/navigation wrappers.
- Directly tests whether MCP improves natural-language recording.

Cons:

- Requires careful trace normalization.
- Must preserve enough evidence to compile stable Playwright code later.
- Browser/session ownership may become more complex.

This is the most interesting MVP if integration is feasible.

### Option C: MCP-first Recording Runtime

Use MCP as the primary browser runtime for natural-language recording, including observation, action, screenshots, and possibly verification.

Pros:

- Maximum reuse of Playwright MCP.
- Removes the largest amount of custom recording-time snapshot logic.

Cons:

- Highest risk.
- May reintroduce multi-round agent latency.
- Harder to keep existing manual/AI mixed recording contracts.
- Still does not eliminate compiler responsibilities.

This should not be the first implementation step.

## Recommended Experiment Shape

Start with Option A or a very small Option B.

Recommended first experiment:

1. Keep current Trace-first runtime as baseline.
2. Add a diagnostic-only MCP snapshot capture for selected recording steps.
3. Compare MCP accessibility snapshot against current raw snapshot and compact snapshot.
4. Use the same test pages/tasks that exposed snapshot bugs:
   - Form fill.
   - Detail extraction.
   - Dynamic table extraction.
   - Candidate/list selection.
   - Search result navigation.
5. Record whether MCP snapshot contains the target evidence and actionable refs.

Only after this comparison should we try MCP-driven actions.

## Evaluation Questions

Observation quality:

- Does MCP snapshot include the target visible text?
- Does it include the right interactive element?
- Is the accessible name useful enough for the instruction?
- Does it avoid irrelevant hidden DOM better than our compact snapshot?
- Does it miss business fields our raw snapshot currently captures?

Action quality:

- Can the model complete common click/fill/select tasks with refs?
- Does it reduce selector timeout and actionability failures?
- Does it handle iframes and dialogs better or worse than our runtime?
- Does it preserve enough evidence for trace compilation?

Performance:

- How many LLM/tool turns per recording step?
- How many tokens does the snapshot consume?
- How much latency does MCP server/tool transport add?
- Does reduced repair offset added tool overhead?

Compilation:

- Can we infer stable replay locators from MCP evidence?
- Do we still need our own raw snapshot for compiler generalization?
- Can accepted traces distinguish MCP refs from replayable locators clearly?

Security and robustness:

- Can page text in accessibility snapshots cause prompt-injection-like behavior?
- Can MCP tools be restricted to current browser actions only?
- How do we prevent arbitrary external navigation or file access beyond existing RPA policy?

## Acceptance Criteria

Do not adopt MCP as a mainline recording component unless it demonstrates:

- Better or equal first-attempt success rate than current runtime on representative RPA tasks.
- Lower or acceptable average recording latency.
- Clear reduction in snapshot compression special-case code.
- No replay dependency on MCP refs.
- Clean conversion from MCP actions to RpaClaw accepted traces.
- Clear diagnostics for failures.
- Compatibility with manual/AI mixed recording.
- No return to open-ended ReAct behavior.

## Non-goals

- Do not replace TraceSkillCompiler with MCP.
- Do not compile MCP refs into `skill.py`.
- Do not abandon raw trace evidence before measuring MCP coverage.
- Do not move SOP-level planning back into recording runtime.
- Do not introduce unlimited tool loops.
- Do not assume accessibility snapshots cover every enterprise/internal UI.

## Relationship To Snapshot Evidence Store Experiment

These two experiments answer different questions.

Snapshot Evidence Store asks:

```text
Can our own raw snapshot become a searchable evidence layer instead of a one-time compact prompt?
```

Playwright MCP Recording Runtime asks:

```text
Can Playwright's accessibility snapshot and MCP action refs replace much of our custom recording-time snapshot/action layer?
```

They are not mutually exclusive.

Possible final outcomes:

- MCP snapshot is good enough for most interactions, and raw evidence store remains only for extraction/compilation diagnostics.
- Evidence store outperforms MCP on business-heavy pages, and MCP is rejected.
- MCP is used for observation/action, while evidence store is retained for post-hoc compiler evidence.
- Both are rejected in favor of improving the current compact snapshot.

## Current Decision

Record this as an exploration path only.

No branch has been created for this yet. The likely future path is:

1. Finish and validate the current Trace-first refactor.
2. Create an independent exploration branch.
3. Run a diagnostic MCP snapshot comparison before attempting runtime replacement.
4. Decide whether MCP deserves an implementation MVP.
