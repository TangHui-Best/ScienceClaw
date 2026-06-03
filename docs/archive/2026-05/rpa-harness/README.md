# RPA Harness 2026-05 Archive

> 生命周期说明：本目录是 archived historical material。这些文件可以解释
> F013-F018 当时如何执行，但不能作为当前接管、资产 promotion 或资产池 readiness
> 的入口。当前入口是 `docs/rpa/harness/internal-handoff-and-freeze-guide.md`、
> `docs/rpa/harness/RPA-Harness-v1-设计.md` 和 canonical Feature/Evidence。

本目录保存已经完成或被新入口取代的 RPA Harness 历史计划。它们仍可用于审计实现过程、恢复上下文或理解某个阶段的取舍，但不再作为当前内网接管、资产治理或运行诊断的入口。

当前入口：

- `docs/rpa/harness/internal-handoff-and-freeze-guide.md`
- `docs/rpa/harness/RPA-Harness-v1-设计.md`
- `docs/rpa/harness/usage-and-triage-guide.md`
- `docs/rpa/harness/资产录制与审查最小流程.md`

归档原因：

- F013-F018 phase/closeout plan 的执行目的已经完成。
- F018 已经把 v1 closeout 收束到 `RPA-Harness-v1-设计.md`。
- F023 进一步把内网接管和封箱状态收束到单入口，避免未来 Agent 在历史 phase plan 中误读当前资产池状态。

使用规则：

- 需要理解历史实现时可以读取这些计划。
- 需要判断当前该跑什么命令、如何 promotion、资产是否可信时，不要从本目录开始。
- 如果本目录内容与当前入口冲突，以当前入口和 Feature/Evidence 状态为准。
