# Snapshot Evidence Store Experiment

Status: Experimental

Branch scope: future independent exploration branch only.

This document records an exploratory architecture idea discussed during the Trace-first Recording refactor. It is not accepted as the mainline RPA architecture yet. Do not change existing RPA contracts, recorder behavior, compiler behavior, or AGENTS.md rules solely because this document exists.

The current baseline remains:

```text
Trace-first Recording + Post-hoc Skill Compilation
```

## Problem

The current recording runtime builds a raw page snapshot and then compresses it before the LLM sees the page context. This keeps prompt size bounded, but it also creates a fragile hidden requirement:

```text
The snapshot compressor must predict which page facts matter before the LLM reasons about the user's task.
```

Recent bug fixes have repeatedly touched snapshot behavior: over-filtering, missing form structure, missing detail fields, table/list projection gaps, and mismatches between raw snapshot facts and compact snapshot facts. These are not isolated bugs. They point to a boundary problem.

Different task shapes need different evidence:

- Detail extraction needs label/value fields and nearby section structure.
- Form fill needs visible editable controls, labels, placeholders, and actionability facts.
- Table and grid tasks need row/column structure, row-local actions, and repeated item boundaries.
- Candidate selection needs broad candidate summaries instead of only the top-ranked region.
- Dynamic lists need repeated item evidence and stable action locators.

A single up-front compression strategy can easily remove the exact facts needed by one of these task shapes.

## Core Idea

Upgrade snapshot handling from a one-time compressed prompt payload into a searchable page evidence store.

The goal is not to remove filtering. The goal is to move from:

```text
compress once -> hope the important facts survived -> generate code
```

to:

```text
build filtered evidence store -> provide lightweight catalogue -> retrieve needed evidence -> generate code
```

This keeps Trace-first unchanged. Recording still executes the current user command in the real browser and records factual traces. Post-hoc compilation still owns generalization. The experiment only changes how the recording-time planner accesses page evidence.

## Proposed Layers

### 1. Minimal Catalogue

The initial planner prompt should receive a small page catalogue, not the full raw DOM. The catalogue should include:

- URL and title.
- Frame overview.
- Region catalogue.
- Summary of available table, detail, form, list, and action areas.
- Retrieval instructions and available query tools.

The catalogue is a map. It should not pretend to contain every fact required to solve every task.

### 2. Near-raw Evidence Store

The evidence store should be generated from the raw snapshot with conservative filtering.

Filter out clearly meaningless or dangerous prompt noise:

- `script`, `style`, `noscript`.
- Large SVG/path payloads.
- Hidden layout junk with no useful text, role, action, or locator.
- Excessively long attributes.
- Random-looking class/id noise when better semantic locators exist.

Preserve facts that help browser automation:

- Visible text.
- Role, accessible name, label, placeholder, value, href.
- Form controls and actionability facts.
- Table rows, cells, headers, and row-local actions.
- Detail label/value fields.
- Container hierarchy, headings, and section boundaries.
- Frame path.
- Bounding boxes when useful for proximity reasoning.
- Locator candidates and selected locator hints.
- Internal ids for evidence lookup only.

Internal ids must not be rewritten into CSS selectors. They are for diagnosis and retrieval, not replay.

### 3. Bounded Retrieval

The planner may retrieve page evidence when the catalogue is insufficient.

Possible retrieval functions:

- `search_snapshot(query, scope=None, limit=8)`
- `search_actionables(query, limit=8)`
- `search_fields(query, limit=8)`
- `get_region(region_id)`
- `get_node(node_id)`

These functions may be implemented with local text search, scoring, or JSON indexing. The planner should not receive unrestricted filesystem access to raw DOM files.

Retrieval results should be short, structured snippets. They should expose evidence, not large DOM dumps.

## Guardrails

This experiment must not recreate the old open-ended ReAct loop.

Rules:

- Keep the recording path bounded.
- Default to one planning call when the catalogue is enough.
- Allow at most one or two snapshot retrieval rounds before first execution.
- Repair may retrieve more targeted evidence because it has concrete failure facts.
- Generated Python can use only `page` and `results`; it must not depend on snapshot files at replay time.
- A text or DOM match is not automatically an actionable locator.
- Prefer Playwright user-facing locators: role, label, text, visible form controls, row/column-relative locators, and explicit locator hints.
- Keep raw failure facts authoritative during repair.
- Do not add site-specific retrieval rules as the main strategy.

## Expected Performance Impact

This experiment may add overhead when a simple task would otherwise be solved from the initial prompt. The overhead comes mostly from extra LLM tool-call turns, not from local search itself.

Expected outcome if bounded retrieval is implemented correctly:

- Simple navigation, click, and fill tasks: roughly neutral or slightly slower.
- Complex forms, detail pages, dynamic tables, and candidate selection: likely faster overall because fewer first attempts fail.
- Repair cases: likely faster and more accurate because the planner can retrieve facts related to the actual failure instead of relying on a lossy compact snapshot.
- Long-term maintenance: likely cheaper because fewer bug fixes need to tune one global compressor for every task shape.

The experiment should measure:

- First-attempt success rate.
- Average recording step latency.
- Repair rate.
- Token usage per step.
- Retrieval calls per step.
- Cases where raw evidence existed but retrieval failed to surface it.
- Cases where retrieval surfaced evidence but planner ignored or misused it.

## Estimated Implementation Size

Minimum viable experiment:

- Evidence store builder: 200-350 lines.
- Retrieval functions and scoring: 150-250 lines.
- Recording runtime integration: 150-250 lines.
- Debug diagnostics: 100-150 lines.
- Focused tests: 150-300 lines.

Estimated total: 600-1000 lines of effective code.

A broader implementation with richer indexing, cache invalidation, debug UI, iframe and Shadow DOM tooling, and more retrieval modes may grow to 1500-2500 lines.

The first experiment should stay small. It should prove whether searchable evidence reduces snapshot-related failures before becoming a larger subsystem.

## Suggested Experiment Plan

Do not replace the existing compact snapshot immediately.

Phase 1:

1. Keep `build_page_snapshot()` as the raw evidence source.
2. Keep `compact_recording_snapshot()` but reduce its role toward catalogue generation.
3. Add an evidence store beside the compact snapshot.
4. Add a small retrieval API for `search_snapshot`, `search_actionables`, and `get_region`.
5. Log every retrieval query and result in recording debug artifacts.
6. Compare raw snapshot, catalogue, retrieval results, planner output, and execution result after failures.

Phase 2:

1. Add task-shape-specific retrieval helpers only when Phase 1 shows repeated gaps.
2. Use failure facts to guide repair retrieval.
3. Measure whether retrieval reduces repair frequency and prompt size.

Phase 3:

1. Decide whether the experiment should become mainline.
2. If accepted, update `docs/rpa/trace-first-architecture.md` and AGENTS.md explicitly.
3. If rejected, keep useful diagnostics and remove planner-facing retrieval behavior.

## Acceptance Criteria

The experiment should not be accepted into the mainline unless it shows clear gains:

- Lower or equal average recording latency on representative tasks.
- Higher first-attempt success rate on forms, detail extraction, list selection, and dynamic tables.
- Fewer snapshot compressor special-case fixes.
- No return to unbounded multi-step ReAct behavior.
- No replay dependency on recording-time snapshot files.
- Clear diagnostics for whether a failure came from raw capture, indexing, retrieval, planning, or execution.

## Non-goals

- Do not redesign Trace-first Recording.
- Do not move post-hoc generalization into the recording runtime.
- Do not build a heavy contract layer during recording.
- Do not let experience rules or site templates dominate planning.
- Do not expose arbitrary filesystem grep as the planner interface.
- Do not treat raw DOM as more authoritative than user-visible browser facts.

## Current Decision

Record the idea as an experiment only.

No branch has been created for this yet. The likely future path is to finish the current Trace-first refactor first, then create an independent exploration branch from that validated baseline.
