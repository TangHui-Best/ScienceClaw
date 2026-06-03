---
id: ADR-002
doc_kind: adr
status: accepted
scope: feature
feature_refs:
  - docs/features/F001-rpa-trace-source-convergence.md
decision_area: rpa-compiler
created: 2026-05-15
updated: 2026-05-27
---

# ADR-002: Trace Evidence Drives Compiler Strategy

## Context

F001 和 ADR-001 解决的是“accepted timeline 由谁承载”，但这还不够。即使所有事实都进了 trace，compiler 仍然可能因为证据类型判断错误而生成假确定性逻辑。典型例子是 AI 提取 trace 只有 observed output，却没有可靠 snapshot field/anchor evidence；如果此时根据输出字段名去发明 DOM locator，trace-first 只是在更漂亮地复制错误。

## Decision

compiler strategy 由 trace 上的证据画像决定，而不是由输出长相、页面样本或站点经验决定。

优先级如下：

1. navigation / popup / download 等副作用证据；
2. 可靠的 structured snapshot evidence；
3. 运行时语义证据，必要时保留 runtime AI；
4. 有边界的 embedded AI code evidence；
5. dataflow evidence；
6. output-only evidence 永远不能单独发明确定性 DOM 提取逻辑。

换句话说，trace 是唯一载体，但不是“只要进了 trace，什么都能确定性编译”。

## Alternatives

- Compile from output field names. Rejected because output labels are observations, not DOM evidence.
- Force every replay into runtime AI. Rejected because strong structured traces should compile deterministically.
- Add site-specific extraction templates. Rejected because the boundary is trace evidence quality, not one site.

## Consequences

- compiler、repair 和 selected-region follow-up 都必须持续区分“结构化字段”“自由文本”“section anchor”“action side effect”“弱输出证据”。
- 后续 patch 不应通过扩大关键词、模板或经验 selector 库来掩盖证据缺口，而应回到证据分类边界本身。
- 验证要覆盖正反两类案例：有强证据时能稳定确定性编译，无强证据时能诚实回退 runtime AI。

## Evidence

- Feature: `docs/features/F001-rpa-trace-source-convergence.md`
- Feature: `docs/features/F011-rpa-region-scoped-snapshot.md`
- Evidence: `docs/evidence/EV-001-rpa-trace-source-convergence.md`
- Evidence: `docs/evidence/EV-011-rpa-region-scoped-snapshot.md`
- Generalization notes: `docs/rpa/trace-skill-compiler-generalization.md`
- Legacy design: `docs/superpowers/specs/2026-05-26-rpa-selected-region-text-extract-design.md`
