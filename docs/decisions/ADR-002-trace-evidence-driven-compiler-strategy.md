---
doc_kind: adr
id: ADR-002
title: Trace Evidence Drives Compiler Strategy
status: accepted
feature_ids: [F001]
date: 2026-05-15
---

# ADR-002 Trace Evidence Drives Compiler Strategy

## Context

F001 and ADR-001 make `RPAAcceptedTrace` the single accepted RPA timeline. During trace-source convergence, a GitHub Trending recording exposed a second boundary: unifying the timeline into trace does not mean every trace can be compiled through the same deterministic replay strategy.

The problematic shape is an AI extraction trace with an observed output such as `{"Star count": "48.2k"}` but without structured snapshot field evidence. If the compiler treats that output label as a replay locator, it can generate internal-detail XPath code such as an `aui-form-item` ancestor lookup on a GitHub page. That is a false abstraction: the recorded output is evidence that a value existed, not proof that the replay page has an AUI detail field with that label.

## Decision

`RPAAcceptedTrace` remains the only accepted timeline carrier, but compiler strategy must be selected from evidence profile, not from output shape alone.

The compiler may deterministically render snapshot extraction only when `signals.extract_snapshot.fields` contains usable structured field evidence from the recording snapshot. Observed `trace.output` keys are not sufficient to invent field locators.

Compiler strategy should follow this priority:

1. Navigation side-effect evidence: render `expect_navigation`, `wait_for_url`, or tab handling from trace signals/actions.
2. Structured snapshot evidence: render deterministic field extraction only from explicit `extract_snapshot.fields`.
3. Runtime semantic evidence: preserve runtime AI when replay requires semantic judgment or when deterministic evidence is missing.
4. Embedded AI code evidence: preserve bounded recording-time AI code when it is the best available replay body and can be safely generalized.
5. Dataflow evidence: prefer `_results` / `output_key` references over observed literals.
6. Output-only evidence: never invent DOM extraction from output keys alone.

## Rejected Options

- Add a GitHub-specific `star_count` compiler rule. Rejected because GitHub is a validation sample, not an architecture source.
- Compile all AI extraction traces through runtime AI. Rejected because it discards valid structured snapshot evidence and weakens trace-first replay.
- Treat `trace.output` labels as fallback field locators. Rejected because it turns observed values into replay logic and can generate false DOM assumptions.
- Remove source/signals/AI execution metadata now that trace is the only timeline. Rejected because trace is the carrier, while these fields are the evidence needed to choose a safe compiler strategy.

## Consequences

- Existing tests that expected output-label fallback snapshot extraction must be updated; that behavior is no longer valid for the generic compiler.
- Structured AUI/detail extraction remains supported when the trace contains explicit structured field evidence.
- Weak extraction traces may replay through runtime AI instead of deterministic code until the recorder captures stronger snapshot facts.
- Final F001 readiness must include golden tests for both positive structured snapshot extraction and negative output-only extraction.

## Links

- Feature: `docs/features/F001-rpa-trace-source-convergence.md`
- Evidence: `docs/evidence/EV-001-rpa-trace-source-convergence.md`
- Generalization notes: `docs/rpa/trace-skill-compiler-generalization.md`
