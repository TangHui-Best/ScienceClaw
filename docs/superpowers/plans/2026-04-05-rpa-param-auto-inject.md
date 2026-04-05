# 技能参数预配置与执行时自动注入

## 背景

凭据保险箱功能实现后，sensitive 参数在 `params.json` 中记录 `credential_id`，执行时由后端自动解密注入。但存在两个问题：

1. 导出技能时 `SKILL.md` 的 Input Schema 仍列出所有参数（包括 password），导致 AI agent 在对话中要求用户提供已自动注入的凭据参数
2. 普通参数（如 username）虽然在 `skill.py` 中有 `kwargs.get()` fallback，但 SKILL.md 仍将其列为参数，agent 每次执行都要求用户提供

## 方案

### 核心思路

将 `inject_credentials` 扩展：执行时从 `params.json` 读取所有预配置参数，**如果 kwargs 中没有对应值**，则自动填入：
- 有 `credential_id` 的参数 → 解密凭据注入
- 有 `original_value` 的普通参数 → 注入默认值

用户显式传参始终优先。同时修改 SKILL.md 生成逻辑，将有预配置的参数标记为可选。

## 改动文件

### 1. `ScienceClaw/backend/credential/vault.py`

扩展 `inject_credentials()` 函数：
- 新增 `if param_name in result: continue` — 用户显式传参优先
- 新增 `original_value` fallback — 无凭据的普通参数也自动注入默认值
- 跳过值为 `{{credential}}` 的占位符

### 2. `ScienceClaw/backend/rpa/skill_exporter.py`

修改 `export_skill()` 中 input_schema 生成逻辑：
- 有 `credential_id` 的 sensitive 参数：完全排除出 schema
- 有 `original_value` 的参数：在 schema 中设置 `default` 字段，不加入 `required`
- 在 SKILL.md 的 Usage 部分添加说明，告知 agent 凭据和默认参数已自动注入，可直接执行

### 3. 执行后端（无需额外改动）

`local_preview_backend.py` 和 `full_sandbox_backend.py` 已调用 `inject_credentials()`，扩展后的逻辑自动生效。

## 验证

1. 录制含用户名+密码的技能，绑定凭据后导出
2. 检查 SKILL.md：password 不在 schema 中，username 标记为可选带 default
3. 对话中调用技能，agent 直接执行 `python3 skill.py` 无需传参
4. 验证用户可以覆盖：`python3 skill.py --username=other` 仍生效
