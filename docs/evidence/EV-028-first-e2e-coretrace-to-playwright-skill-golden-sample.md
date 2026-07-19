---
id: EV-028
doc_kind: evidence
scope: project
feature_refs:
  - F026-rpa-agent-scienceclaw-host-rebuild
created: 2026-07-17
---

# EV-028：首个 E2E CoreTrace 到 Playwright SKILL Golden Sample 验证

## Supports Claim

本 Evidence 支撑以下有限声明：首个阶段一 E2E 已经被串成一套静态自洽、可恢复、可作为后续实现目标的 Golden Sample。该样例包含 Skill Definition、24 条 CoreTrace、Replay A/B Input 和四文件生成 SKILL，并通过现有 CoreTrace Schema、跨 Trace 基础语义、Python 语法、来源摘要和录制值硬编码检查。

## Verification Scope

本次验证覆盖：

- 外部设计目录与 ScienceClaw worktree 内九个样例文件逐文件 SHA-256 一致；
- `coretrace.timeline.json` 符合 CoreTrace v0.1 JSON Schema；
- Timeline 顺序、Trace 唯一性、PageRef 生命周期、Skill Input 引用、`filter_binding` 和变量生产消费；
- Manifest 的 Trace 数量与 Timeline Hash；
- 24 条 CoreTrace 与 24 个生成步骤函数的一一对应；
- `skill.py` 与 `browser_segment.py` 的 Python AST 语法；
- 生成产物不存在两组 fixture 的订单号、金额、随机任务 URL 或 token。

不覆盖 Runtime 接口实现、Compiler 实现、浏览器动态执行、Replay A/B、eval-app 后端 Oracle 或产品代码集成。

## Checks

```text
jsonschema.Draft202012Validator(core_trace_schema).iter_errors(timeline)

静态语义检查：
sequence / trace_id / PageRef / Skill Input / filter_binding /
Variable producer-consumer / Manifest source / step function mapping

Python AST：
ast.parse(skill.py)
ast.parse(browser_segment.py)

硬编码扫描：
PO-2026-05017 / PO-2026-06042 / 128600.50 / 10150.75 /
task-7f28d3 / token=

外部目录与仓库镜像逐文件 SHA-256 比对
```

## Results

- Pass：样例包共九个文件，外部材料与仓库镜像逐文件一致。
- Pass：CoreTrace v0.1 Schema 校验通过，Timeline 共 24 条 Trace。
- Pass：24 条 Trace 对应 24 个步骤函数。
- Pass：Page 生命周期只包含宿主初始 `main` 和 `trace_100` 产生的 `acceptance_detail`。
- Pass：变量生产集合为 `采购订单` 与 `验收结果`；六个 `采购订单.*` 叶子消费均位于根对象生产之后。
- Pass：Timeline SHA-256 为 `f9b29a4e68bde242075e3cbb91048a3a90c922140049062fea91620007b156aa`，与 Manifest 一致。
- Pass：两个 Python 文件通过 AST 语法解析。
- Pass：生成 SKILL 未命中两组 fixture 订单号、金额、随机任务 URL 或 token。

## Artifacts

- [Golden Sample 说明](../superpowers/specs/examples/first-e2e-coretrace-to-playwright-skill/README.md)
- [完整 CoreTrace Timeline](../superpowers/specs/examples/first-e2e-coretrace-to-playwright-skill/coretrace.timeline.json)
- [生成的浏览器段](../superpowers/specs/examples/first-e2e-coretrace-to-playwright-skill/generated-skill/browser_segment.py)
- [F026：RPA Agent 基于 ScienceClaw 宿主重构](../features/F026-rpa-agent-scienceclaw-host-rebuild.md)
- 外部设计材料：`E:\RPA-Agent\docs\design\examples\RPA Agent首个E2E CoreTrace到Playwright SKILL完整示例`

## Limitations

本 Evidence 证明的是设计样例的静态一致性，不证明任何动态能力已经完成。特别是：

- `rpa_agent.runtime` 及示例调用的 RunContext 服务尚未实现；
- 现有 Compiler 尚不能生成该产物；
- eval-app 页面和 Oracle 是否已经满足样例 Locator 契约未在本次验证；
- 页面成功提示仍只是辅助输出，不能代替后端 Oracle；
- Python 语法通过不代表模块可导入或 Skill 可运行。

因此 F026 继续保持 `In Progress`，首个产品能力的完成证据必须来自同一生成 SKILL 的 Replay A、Replay B 和后端 Oracle。

## Notes

Golden Sample 约束的是行为契约，不要求后续 Compiler 生成逐字符相同的 Python。Runtime API 的具体签名仍可在实现中优化，但不能改变 CoreTrace 唯一事实源、运行值隔离、动作前准备 Effect、每条 Trace 独立解析 Scope、失败不回退 Agent 和不兼容旧链路等已确认原则。
