---
status: active
updated: 2026-05-24
---

# Backlog

## Active Branch Map

当前 RPA 相关工作保持三条活跃分支，避免区域选择、iframe 修复和 Harness 验证再次混线。

| Branch | Purpose | Base / State | Notes |
| --- | --- | --- | --- |
| `codex/rpa-region-selection-optimization-v2` | 区域选择功能优化 | 基于 `upstream/master` 新建，当前所在分支 | 用于继续优化区域选择体验、准确性、交互和 snapshot 选择效果。不要混入 iframe 专项修复。 |
| `codex/rpa-iframe-frame-context-fix-v2` | iframe / frame context bug 修复 | 基于已合入区域选择功能后的 `upstream/master` | 用于专门处理 iframe 场景失败。旧 `codex/rpa-frame-context-facts` 只作为历史参考。 |
| `codex/rpa-harness-region-integration` | Harness + 区域选择协同验证 | 已推送，包含 live-agent eval、F012/EV-012 和 LL-001 复盘 | 用作内网 Harness 验证和实现参考，不作为区域选择优化主开发分支。 |

## Historical Reference Branches

以下分支原则上不再继续开发，只在需要查历史实现或恢复上下文时参考：

- `codex/rpa-region-context-refine-main`
- `codex/rpa-region-scoped-snapshot-master-pr`
- `codex/rpa-frame-context-facts`
- `codex/rpa-trace-first-harness`

## Next Actions

- 区域选择优化：继续在 `codex/rpa-region-selection-optimization-v2` 上推进。下一步把 `/section-texts` 手动 fixture 接入 runner-backed eval case，或保存一次手动 region selection 录制/编译 artifact，证明可靠 section/container anchor 走确定性编译，缺 anchor 的自由文本走 runtime AI 且不嵌入录制现场文本。
- iframe 修复：先建立可复现 iframe scenario，再进入 `codex/rpa-iframe-frame-context-fix-v2`。
- Harness 验证：内网运行 live-agent eval 时参考 `codex/rpa-harness-region-integration` 上的 F012/EV-012 和 `docs/rpa/harness/live-agent-eval.md`。

## Active

### Live Agent Eval For RPA Harness Internal Validation

- Source: user needs Harness to validate the real natural-language SOP -> `RecordingRuntimeAgent` -> accepted trace -> Skill path before using it on the internal machine.
- Feature: `docs/features/F012-live-agent-eval-for-rpa-harness.md`
- Evidence: `docs/evidence/EV-012-live-agent-eval-for-rpa-harness.md`
- Doc: `docs/rpa/harness/live-agent-eval.md`
- Status: implementation completed on `codex/rpa-harness-region-integration`; awaiting internal LLM validation and iframe-specific scenario authoring.

Next actions:

- On the internal machine, run `python -m backend.rpa.harness.run_live_agent_eval` with controlled live scenarios and real model configuration.
- Add an iframe scenario fixture before repairing frame context in the new v2 branch, so the bugfix is driven by a reproducible failure rather than by copying historical branch changes.
- Keep generated assets at `candidate-lite` until expected signals, sensitivity, and generalization boundaries are reviewed.

### Post-F002 RPA Harness Follow-ups

- Source Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: follow-up backlog after F002 completion.

Next actions:

- Curate the first candidate/golden asset set using the F003 governance metadata, not the existing direct Agent chat runner.
- Curate high-quality draft captures into candidate/golden regression assets after sensitivity review.
- Add page-pattern and core-chain coverage tags so the team can answer which page forms and RPA core paths are represented.
- Make runner defaults consume governed scenario assets for Offline Core-Chain Regression and prepare them for future Skill Replay E2E.
- Keep asset validation as an offline Evidence gate, not a recording-time blocker.
- Treat historical draft asset findings as asset-governance evidence:
  - `missing-entry-checkpoint` on two older draft Full SOP assets.
  - `empty-after-html` on one older draft click-navigation step.
- Route `compiler-hardcoded-observed-value` to a separate RPA Agent / `TraceSkillCompiler` generalization feature; do not count it as unfinished F002 Harness infrastructure.

## Recently Completed

### F010 Assisted Asset Review And Promotion Pipeline

- Feature: `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`
- Evidence: `docs/evidence/EV-010-assisted-asset-review-and-promotion-pipeline.md`
- Plan: `docs/rpa/harness/f010-assisted-asset-review-and-promotion-plan.md`
- Target asset: `data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e`
- Status: completed; F010 commit/push is being handled from the current branch.
- Result: new captures can generate Chinese-first `review.md` Review Packets,
  start as non-blocking `candidate-lite`, and move to active blocking
  `candidate` after explicit human expected/sensitivity confirmation.
- Real bootstrap signal: blocking governed baseline now selects both
  `hcap-4be6265f43eb42dfa259182207aa64cc` and
  `hcap-de463b7bb608482e9b5bcdd5b78a224e`; latest governed regression has
  `snapshot_failed=0`, `compiler_failed=0`, `skill_replay_failed=0`, and
  `stateful_sop_failed=0`.
- Residual risk: the new asset's sensitivity label remains `local-only` even
  though sensitivity review is confirmed; changing the sensitivity
  classification itself should be a separate explicit workflow if needed.

### F009 Stateful SOP Capture-to-Skill Regression Runner

- Feature: `docs/features/F009-stateful-sop-capture-to-skill-regression-runner.md`
- Evidence: `docs/evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md`
- Status: completed.
- Result: governed regression now includes a `stateful_sop` runner that uses a
  governed Full SOP asset as the recording input boundary, rebuilds
  session-style accepted traces, compiles one full SOP Skill, and replays it
  through controlled captured HTML without live GitHub or direct Agent chat.
- Real bootstrap signal: `stateful_sop_checked=1`, `stateful_sop_failed=0`,
  `accepted_trace_count=3`, `fork_count=Fork 1.3k`.
- Residual risk: baseline remains one candidate asset; Harness v1
  infrastructure should pause expansion and shift to user asset recording plus
  RPA Agent core fixes validated by assets.

### F008 Skill Replay E2E Runner

- Feature: `docs/features/F008-skill-replay-e2e-runner.md`
- Evidence: `docs/evidence/EV-008-skill-replay-e2e-runner.md`
- Status: completed.
- Result: governed regression now compiles trace evidence into generated Skills,
  executes them against controlled captured-HTML replay pages/providers, and
  reports `skill_replay_checked=3` plus `skill_replay_failed=0` for the real
  bootstrap candidate asset.
- Implementation commit:
  `5afab4f876daf7e5d8ef392ff9c6ac0fdb97ab01`.
- Residual risk: replay is still per-step captured HTML replay, not full
  stateful SOP replay; baseline remains one candidate asset and still reports
  `single-candidate-asset-baseline`.

### F007 Production Snapshot Core-chain Regression

- Feature: `docs/features/F007-production-snapshot-core-chain-regression.md`
- Evidence: `docs/evidence/EV-007-production-snapshot-core-chain-regression.md`
- Status: completed.
- Result: governed offline snapshot regression now runs captured HTML through
  the production DOM/raw snapshot JS and `compact_recording_snapshot`, reports
  source/raw/compact signal preservation, and exposes snapshot quality plus
  average compact/raw compression in JSON and human summaries.
- Residual risk: baseline remains one candidate asset and still reports
  `single-candidate-asset-baseline`; Skill Replay E2E remains F008.

### F006 Observable Governed Regression Report

- Feature: `docs/features/F006-observable-governed-regression-report.md`
- Evidence: `docs/evidence/EV-006-observable-governed-regression-report.md`
- Status: completed.
- Result: governed offline regression now emits a machine-readable
  `observability` contract and `--format summary` human report covering asset
  qualification, coverage, runner signals, blast radius, and confidence risks.

### F005 First Governed Candidate Asset

- Feature: `docs/features/F005-first-governed-candidate-asset.md`
- Evidence: `docs/evidence/EV-005-first-governed-candidate-asset.md`
- Asset: `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`
- Status: completed.
- Result: first repo-safe `candidate` asset is selected by the F004 governed
  offline report and passes validation, snapshot, compiler, and blast-radius
  checks.

### F004 Governed Offline Regression Asset Pool

- Feature: `docs/features/F004-governed-offline-regression-asset-pool.md`
- Evidence: `docs/evidence/EV-004-governed-offline-regression-asset-pool.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: completed.
- Result: Offline Core-Chain Regression now has a governed default report over
  active reviewed candidate/golden assets, with explicit excluded-asset reasons
  and a `no-governed-offline-assets` failure when the baseline is empty.

### F003 Golden Scenario Asset Model

- Feature: `docs/features/F003-golden-scenario-asset-model.md`
- Evidence: `docs/evidence/EV-003-golden-scenario-asset-model.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: completed.
- Result: Scenario assets now have governance metadata for promotion status, runner eligibility, core-chain coverage, expected-signal review, and sensitivity review; validation and catalog reporting consume those fields.

### F002 RPA Harness v0

- Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Status: completed after post-stabilization Full SOP validation.
- Completion asset: `data/rpa_harness_assets_bootstrap/hcap-ef3f5d7107ef4b1586dd533c6c7f8d41`

### Harness closeout process miss

- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Trigger: user reported F01-F14 implementation lacked Feature/Evidence materials.
- Recovery: create F002, EV-002, LL-001, this Backlog, and a project-level rule.
