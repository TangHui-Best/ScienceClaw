# API Monitor 重新生成工具时 YAML 错误反馈

## 问题

工具的 YAML 定义校验失败后，API Monitor 页面会显示错误信息。用户可以点击"重新生成"来重试。然而，重新生成流程调用 LLM 时没有携带之前失败的上下文信息。LLM 无法知道之前哪里出错了，因此可能会反复生成同样有问题的 YAML。

## 根因

在 `manager.py:_generate_tool_for_candidate()` 中，`step_context` 字符串从 `candidate.step_metadata` 构建，然后传给 `generate_tool_definition()`。重新生成时，关联的已有工具的 `validation_errors`（包含具体的 YAML 解析错误）已经在 session 数据中可用，但从未被纳入 LLM 的 prompt。

## 方案

在 `_generate_tool_for_candidate()` 中，构建完 `step_context` 之后、调用 `generate_tool_definition()` 之前，检查关联的已有工具是否有 `validation_errors`。如果有，将错误信息追加到 `step_context` 中，让 LLM 收到错误反馈。

### 改动

**文件：`backend/rpa/api_monitor/manager.py`**

在 `_generate_tool_for_candidate()` 中（约第 2691-2709 行），增加将之前的 YAML 校验错误纳入 step_context 的逻辑：

```python
# 现有代码从 step_metadata 构建 step_context
step_context = ""
if candidate.step_metadata:
    lines = []
    for sm in candidate.step_metadata[:5]:
        lines.append(
            f"- 操作 '{sm.get('action_description', '')}' "
            f"在页面 {sm.get('page_url', '')} 触发了 {sm.get('call_count', 0)} 次调用"
        )
    step_context = "\n此 API 在以下操作中被观察到:\n" + "\n".join(lines)

# 新增：将之前的 YAML 校验错误纳入重新生成上下文
existing_tool = next(
    (tool for tool in session.tool_definitions if tool.generation_candidate_id == candidate.id),
    None,
)
if existing_tool and existing_tool.validation_errors:
    error_lines = "\n".join(f"- {e}" for e in existing_tool.validation_errors)
    step_context += f"\n\n之前的 YAML 定义校验失败，请修正以下错误：\n{error_lines}"
```

不改变函数签名，不新增参数。复用现有的 `step_context` 字段将错误反馈传递给 `generate_tool_definition()`。

### 影响范围

- 仅修改 `manager.py` 中的 `_generate_tool_for_candidate()` 方法
- 无 API 变更，无模型变更
- 仅在已有工具存在校验错误时触发（重新生成场景）
- 首次生成不受影响
