---
id: ADR-002
doc_kind: adr
status: accepted
scope: project
feature_ids: [F001]
feature_refs:
  - docs/features/F001-rpa-trace-source-convergence.md
decision_area: rpa-trace-compiler-strategy
created: 2026-05-15
updated: 2026-05-18
---

# ADR-002: Trace Evidence Drives Compiler Strategy

## Context

F001 and ADR-001 make `RPAAcceptedTrace` the single accepted RPA timeline. During trace-source convergence, a GitHub Trending recording exposed a second boundary: unifying the timeline into trace does not mean every trace can be compiled through the same deterministic replay strategy.

An AI extraction trace may contain an observed output such as `{"Star count": "48.2k"}` without structured snapshot field evidence. If the compiler treats that output label as a replay locator, it can invent false DOM assumptions. The recorded output is evidence that a value existed, not proof that the replay page has a stable field with that label.

## Decision

`RPAAcceptedTrace` remains the only accepted timeline carrier, but compiler strategy must be selected from the trace evidence profile, not from output shape alone.

Compiler strategy follows this priority:

1. Navigation side-effect evidence: render navigation waits or tab handling from trace signals/actions.
2. Structured snapshot evidence: render deterministic field extraction only from explicit `signals.extract_snapshot.fields`.
3. Runtime semantic evidence: preserve runtime AI when replay requires semantic judgment or deterministic evidence is missing.
4. Embedded AI code evidence: preserve bounded recording-time AI code when it is the best available replay body and can be safely generalized.
5. Dataflow evidence: prefer `_results` / `output_key` references over observed literals.
6. Output-only evidence: never invent DOM extraction from output keys alone.

## Alternatives

- Add a GitHub-specific `star_count` compiler rule. Rejected because GitHub is a validation sample, not an architecture source.
- Compile all AI extraction traces through runtime AI. Rejected because it discards valid structured snapshot evidence and weakens trace-first replay.
- Treat `trace.output` labels as fallback field locators. Rejected because it turns observed values into replay logic and can generate false DOM assumptions.
- Remove source/signals/AI execution metadata now that trace is the only timeline. Rejected because trace is the carrier, while these fields are the evidence needed to choose a safe compiler strategy.

## Consequences

- Tests that expected output-label fallback snapshot extraction must be updated; that behavior is no longer valid for the generic compiler.
- Structured extraction remains supported when the trace contains explicit field evidence.
- Weak extraction traces may replay through runtime AI until the recorder captures stronger snapshot facts.
- Final F001 readiness must include golden tests for both positive structured snapshot extraction and negative output-only extraction.

## Evidence

- Feature: [F001 RPA Trace Source Convergence](../features/F001-rpa-trace-source-convergence.md)
- Evidence: [EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md)
- Generalization notes: [TraceSkillCompiler Generalization](../rpa/trace-skill-compiler-generalization.md)
