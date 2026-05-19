# 10 天高强度开发复盘：把开发过程变成可复用的工程记忆

## 一组先看得见的数据

过去 10 天，这个项目在当前分支 HEAD 可达历史里沉淀了：

```text
提交数：162 个
新增：47,283 行
删除：4,829 行
净增：42,454 行
```

提交类型分布也很能说明开发节奏：

```text
fix：83 个
feat：36 个
docs：19 个
Merge：16 个
refactor：4 个
Revert：2 个
chore：2 个
```

如果拆开看：

```text
后端代码：新增 11,135 / 删除 1,365 / 净增 9,770
前端代码：新增 10,332 / 删除 3,000 / 净增 7,332
测试代码：新增 13,827 / 删除 409 / 净增 13,418
文档/设计：新增 11,973 / 删除 52 / 净增 11,921
其它：新增 16 / 删除 3 / 净增 13
```

也就是说，如果只看后端 + 前端产品代码，大约是：

```text
新增：21,467 行
删除：4,365 行
净增：17,102 行
```

如果把测试也算作开发代码，不算文档，则是：

```text
新增：35,294 行
删除：4,774 行
净增：30,520 行
```

更有意思的不是行数本身，而是这些行数背后的组织方式：最近 10 天里，提交不是一个巨大的功能包，而是被拆成了大量可以追踪的小步；功能不是直接凭感觉写，而是伴随着设计、计划、修复、回滚、边界文档和项目军规一起演进。

这篇复盘记录的是这套开发方式里值得复用的习惯。

## 1. 高频小步提交：commit 不只是版本点，也是开发日志

最近的提交历史里，`fix` 有 83 个、`feat` 有 36 个、`docs` 有 19 个，说明开发不是单纯堆功能，而是在持续实现、修复、记录和校准。很多提交都围绕具体问题命名：

- `fix: preserve mixed RPA trace ordering`
- `fix: compile tab switch traces`
- `fix: support Jalor grid snapshot tables`
- `docs: design trace-first RPA recording`
- `docs: plan structured rpa snapshot`
- `docs: record Jalor grid recording regression notes`

这种提交方式的价值不是“看起来很勤奋”，而是让 git 历史具备调试价值。

当后续出现问题时，不需要在一个巨大提交里猜测 bug 是怎么来的，而是可以沿着提交主题回到具体阶段：是 popup、多 tab、download、iframe、snapshot、locator、timeline，还是 trace compiler 引入的问题。

好的 commit 应该回答三件事：

```text
这一步解决了什么问题？
它属于哪个阶段？
如果后面出 bug，应该从哪里开始怀疑？
```

高频提交不是把开发切碎，而是把思考留下坐标。

## 2. 阶段性交接写清楚决策，而不是只写结果

这个项目里一个很好的习惯是：在 commit、PR、新会话、阶段收尾时，不只写“改了什么”，还会写：

- 采用了什么方案。
- 为什么采用。
- 放弃了什么方案。
- 为什么放弃。
- 遇到了哪些坑。
- 后续接手要注意什么。

例如 Trace-first RPA 的路线不是突然出现的。它背后有明确的判断：

```text
录制阶段先真实操作浏览器并记录事实 trace。
泛化、去硬编码、回放验证放到后置 Skill 编译阶段。
不要在录制时构建重型 Contract-first 中间层。
```

这个决策非常重要，因为它不是局部代码实现，而是在定义系统主路径。

如果只记录“实现了 trace-first”，下一个人很容易重新引入 Contract-first 的复杂度；但如果记录了“为什么不在录制期做重型 contract”，未来维护者就能理解边界，而不是重复踩坑。

## 3. 设计先行，但不把 spec/plan 当形式主义

最近 10 天里，很多关键变化都有 `docs: design ...` 和 `docs: plan ...` 先行：

- Trace-first RPA recording
- RPA MCP semantic inference
- RPA tool studio IA
- manual recording single-source
- random locator conservative replacement
- structured snapshot
- RPA flow guide

这说明设计文档不是事后补门面，而是用来承载真实分歧：

- 主路径应该 trace-first 还是 contract-first？
- repair 应该几轮？
- runtime AI 应该保留在哪些步骤？
- selector 稳定性问题应该预拦截，还是执行后基于失败事实 repair？
- snapshot 压缩应该用统一 TopK，还是按任务形态区分？

这里最好的习惯是：设计不是“列功能”，而是“定边界”。

真正有用的设计文档应该帮后续开发者回答：

```text
这个系统现在坚持什么？
它明确不做什么？
什么情况下才允许重新打开这个决策？
```

## 4. 敢于回滚：不要在错误路径上继续补丁

最近历史里可以看到明确的 revert：

- `Revert "fix: support Jalor grid snapshot tables"`
- `Revert "fix: preserve hover trigger across body clicks"`

这是一种非常健康的工程习惯。

很多系统复杂度不是一开始设计出来的，而是因为一个局部修复不够好，然后继续在它上面补第二个、第三个规则。等回头看时，主路径已经被 fallback、关键词匹配、站点经验和临时补丁占满。

敢于回滚的本质是承认：

```text
一个补丁如果开始污染主路径，它就不再是修复，而是在制造新的架构债务。
```

回滚不是倒退，它是保护系统边界。

## 5. 把失败当成事实资产，而不是噪声

RPA 方向里最容易犯的错，是看到失败后立刻补经验规则：

- 这个 selector 看起来不稳定，先拦掉。
- 这个站点有特殊结构，加一个模板。
- 这个页面容易慢，多等几秒。
- 这个字段经常空，加一个 fallback。

但这个项目沉淀出的原则更清醒：

```text
失败事实优先，经验提示辅助。
```

repair 输入必须保留：

- 原始错误日志。
- 当前 URL/title。
- 失败代码或计划摘要。
- 执行结果。
- 当前页面状态。
- snapshot 差异。

经验可以作为 advisory hint，但不能替代事实。

这个习惯的长期价值很大：系统不会因为一个偶发 case 就变成经验规则引擎，后续修复也更接近 root cause。

## 6. 先判断信息是否进入 snapshot，再修 planner

RPA/Agent 系统里，LLM 选错区域、提取错数据、操作错元素时，最直觉的做法是改 prompt。

但项目军规里沉淀了一个更好的诊断顺序：

```text
先比较 raw snapshot 和 compact snapshot，再修 planner。
```

如果 raw snapshot 里有目标信息，而 compact snapshot 压缩后丢了，那么问题不是 planner 不聪明，而是 planner 根本没拿到信息。

这条规则很重要，因为它防止我们在错误层修问题：

- snapshot 压缩丢信息，却去改 prompt。
- 候选列表缺横向摘要，却去补 selector。
- 数据流没建起来，却去写 observed value。

好的诊断顺序会减少无效优化。

## 7. 不为单一站点反向塑造架构

最近的开发中出现了 GitHub、Jalor、百度等具体案例，但沉淀下来的规则不是“某站点怎么处理”，而是：

```text
站点只能作为验证案例，不能成为核心抽象本身。
```

这是一条很高级的习惯。

因为单一站点的问题往往很诱人：加一个关键词、一个模板、一个特殊 selector，好像马上就能过。但一旦这种东西成为主路径，系统就会从“泛化能力”滑向“经验规则库”。

更好的做法是先问：

```text
这个 case 背后的通用问题是什么？
是跨步骤数据依赖？
是录制现场值去硬编码？
是动态列表候选选择？
是可见可编辑元素定位？
是表格结构提取？
```

先抽象通用问题，再把站点案例作为验证样本。

## 8. 军规及时进入 AGENTS.md

这个项目最值得复用的习惯之一，是把反复踩坑后的经验升级为项目级 `AGENTS.md` 规则。

例如：

- RPA 录制主路径坚持 Trace-first。
- 禁止做经验规则驱动的 Agent。
- 失败事实优先，经验提示辅助。
- 安全拦截和稳定性建议必须分层。
- Fallback 只能救急，不能反客为主。
- 方案设计必须面向泛化场景。
- 先比较 raw snapshot 和 compact snapshot，再修 planner。
- snapshot 压缩必须区分任务形态。
- 不要加“拦住但不解决”的校验。

这些不是普通开发偏好，而是会直接改变未来 agent 行为的约束。

一个经验是否应该进入 AGENTS.md，可以用这个标准判断：

```text
如果下一个 agent 不知道这条规则，是否很可能重复犯错？
这条规则是否足够具体，能改变它的行动顺序？
它是否保护了项目的长期架构边界？
```

如果答案是肯定的，就值得沉淀。

## 9. 文档分层：设计、计划、军规、回归笔记各归其位

这个项目的文档不是堆在一个地方，而是逐渐形成了分层：

- `docs/superpowers/specs/`：记录设计选择。
- `docs/superpowers/plans/`：记录实施计划。
- `docs/rpa/`：记录长期架构、策略和专项分析。
- `AGENTS.md`：记录 future agent 必须遵守的项目规则。
- commit/PR body：记录局部变更上下文。

这个分层很重要。

如果所有内容都写进 AGENTS.md，规则会变得臃肿；如果所有内容都只写进 commit，长期约束又不容易被新会话读取；如果只有 spec 没有军规，后续 agent 可能看过设计却仍然在执行时走偏。

好的沉淀不是多写文档，而是放到正确的位置。

## 10. 从项目经验沉淀到可复用 Skill

这 10 天真正值得带到下一个项目的，不只是 RPA 的具体实现，而是一套开发连续性方法：

```text
高频小步提交，让 git 历史能定位问题。
阶段性交接，记录为什么这样做。
设计先定边界，再进入实现。
遇到错误路径敢于回滚。
失败事实优先，不让经验规则主导系统。
重复踩坑后升级为项目军规。
把一次项目里的好习惯，沉淀为下一个项目可复用的 Skill。
```

因此，这次最终沉淀出了一个新的 Codex skill：

```text
development-continuity
```

它的目标是：

```text
Preserve engineering memory across commits, PRs, long sessions, agent handoffs,
architecture pivots, repeated bug fixes, and project-rule updates.
```

它不是用来替代 `brainstorming`、`writing-plans` 或 `verification-before-completion` 的。那些 skill 分别负责需求澄清、实施计划和完成前验证。

`development-continuity` 负责的是另一层东西：

```text
把开发过程中的关键判断、放弃路线、坑点、验证证据和项目规则，
保存成下一个会话、下一个 agent、下一个项目都能继承的工程记忆。
```

它会在这些场景触发：

- 准备 commit、PR、merge 或新会话交接。
- 完成一个非平凡功能。
- 发生架构方向转变。
- 出现 revert、backup、fallback 或临时绕路。
- 同类 bug 多次出现。
- 发现某条经验应该进入 AGENTS.md。
- 一个功能积累了足够多提交，需要阶段性小结。

配套模板包括：

- `handoff-template.md`
- `adr-template.md`
- `agents-rule-template.md`
- `commit-pr-template.md`

这也是这次复盘最重要的结论：

```text
真正可复用的不是某一个补丁，而是让补丁背后的决策、证据和教训不会丢失的机制。
```

当开发过程能被持续压缩成工程记忆，项目就不再只是代码仓库，而会变成一个越来越懂自己的系统。
