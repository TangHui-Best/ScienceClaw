# API Monitor YAML 错误反馈 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重新生成工具时，将之前的 YAML 校验错误反馈给 LLM，避免反复生成同样的错误 YAML。

**Architecture:** 在 `_generate_tool_for_candidate()` 中，调用 `generate_tool_definition()` 前，从已有工具的 `validation_errors` 读取错误信息，追加到 `step_context` 中传给 LLM。

**Tech Stack:** Python, AsyncIO

---

### Task 1: 在 _generate_tool_for_candidate 中注入 YAML 错误反馈

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2691-2699`

- [ ] **Step 1: 在 step_context 构建之后、generate_tool_definition 调用之前，追加已有的 YAML 校验错误**

将 `manager.py` 第 2691-2699 行从：

```python
        step_context = ""
        if candidate.step_metadata:
            lines = []
            for sm in candidate.step_metadata[:5]:
                lines.append(
                    f"- 操作 '{sm.get('action_description', '')}' "
                    f"在页面 {sm.get('page_url', '')} 触发了 {sm.get('call_count', 0)} 次调用"
                )
            step_context = "\n此 API 在以下操作中被观察到:\n" + "\n".join(lines)

        try:
```

改为：

```python
        step_context = ""
        if candidate.step_metadata:
            lines = []
            for sm in candidate.step_metadata[:5]:
                lines.append(
                    f"- 操作 '{sm.get('action_description', '')}' "
                    f"在页面 {sm.get('page_url', '')} 触发了 {sm.get('call_count', 0)} 次调用"
                )
            step_context = "\n此 API 在以下操作中被观察到:\n" + "\n".join(lines)

        # 将之前的 YAML 校验错误纳入重新生成上下文，避免 LLM 重复同样的错误
        _prev_tool = next(
            (t for t in session.tool_definitions if t.generation_candidate_id == candidate.id),
            None,
        )
        if _prev_tool and _prev_tool.validation_errors:
            step_context += "\n\n之前的 YAML 定义校验失败，请修正以下错误：\n" + "\n".join(
                f"- {e}" for e in _prev_tool.validation_errors
            )

        try:
```

- [ ] **Step 2: 提交**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "fix: 重新生成工具时将之前的YAML校验错误反馈给LLM"
```
