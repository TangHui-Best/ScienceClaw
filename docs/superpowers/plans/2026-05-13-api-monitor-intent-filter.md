# API Monitor AI 意图二次过滤 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 API Monitor 新增 AI 意图二次过滤，将置信度评分前置并移除 business_path 启发式，只对通过两轮评分的候选生成工具定义。

**Architecture:** 第一轮基于规则评分（满分100，移除 business_path），第二轮 AI 意图判断（仅扣分 -25）。两轮评分都在 LLM 工具定义生成之前执行。未通过的候选标记为 `confidence_rejected` 或 `intent_filtered`，前端展示并支持强制生成。

**Tech Stack:** Python/FastAPI (backend), Vue 3/TypeScript (frontend), LangChain (LLM calls)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `RpaClaw/backend/rpa/api_monitor/models.py` | 新增 `intent`、`rejection_reason`、`intent_filter_reason` 字段和新状态 |
| Modify | `RpaClaw/backend/rpa/api_monitor/confidence.py` | 移除 business_path、调整分值、新增 `summarize_rejection_reasons` |
| Create | `RpaClaw/backend/rpa/api_monitor/intent_filter.py` | AI 意图相关性判断模块 |
| Modify | `RpaClaw/backend/rpa/api_monitor/manager.py` | 置信度前置、意图过滤集成、强制生成 |
| Modify | `RpaClaw/backend/route/api_monitor.py` | 新增 intent、force-generate 端点 |
| Modify | `RpaClaw/frontend/src/api/apiMonitor.ts` | 新增类型和 API 函数 |
| Modify | `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue` | 意图输入 UI、候选状态展示 |
| Modify | `RpaClaw/frontend/src/locales/zh.ts` | 中文翻译 |
| Modify | `RpaClaw/frontend/src/locales/en.ts` | 英文翻译 |

---

### Task 1: 数据模型变更

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py`

- [ ] **Step 1: 在 `ApiMonitorSession` 新增 `intent` 字段**

在 `ApiMonitorSession` 类（约第160行）中，在 `active_tab_id` 之前添加：

```python
    intent: Optional[str] = None
```

- [ ] **Step 2: 在 `ApiToolGenerationCandidate` 新增字段和状态**

在 `ApiToolGenerationCandidate` 类（约第91行）中，在 `updated_at` 之前添加：

```python
    rejection_reason: Optional[str] = None
    intent_filter_reason: Optional[str] = None
```

状态值 `status` 字段的注释（约第100行）更新为：

```python
    status: GenerationStatus = "pending"  # pending, running, generated, failed, rate_limited, stale, confidence_rejected, intent_filtered
```

注意：`status` 字段类型是 `str`，不需要修改类型定义，只需更新注释。

- [ ] **Step 3: 在 `AnalyzeSessionRequest` 新增 `intent` 字段**

在 `AnalyzeSessionRequest` 类（约第224行）中，在 `model_id` 之前添加：

```python
    intent: Optional[str] = None
```

- [ ] **Step 4: 新增 `UpdateSessionIntentRequest` 和 `ForceGenerateRequest` 模型**

在 `AnalyzeSessionRequest` 类之后添加：

```python
class UpdateSessionIntentRequest(BaseModel):
    intent: str = ""

class ForceGenerateRequest(BaseModel):
    model_id: Optional[str] = None
```

同时更新文件顶部的 import，确保 `BaseModel` 和 `Optional` 已导入（应该已存在）。

- [ ] **Step 5: 更新路由文件的 import**

在 `RpaClaw/backend/route/api_monitor.py` 第18-26行的 import 中，将新增的 `UpdateSessionIntentRequest` 和 `ForceGenerateRequest` 添加到导入列表：

```python
from backend.rpa.api_monitor.models import (
    AnalyzeSessionRequest,
    ApiMonitorSession,
    StartSessionRequest,
    NavigateRequest,
    PublishMcpRequest,
    UpdateToolRequest,
    UpdateToolSelectionRequest,
    UpdateSessionIntentRequest,
    ForceGenerateRequest,
)
```

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/route/api_monitor.py
git commit -m "feat: 新增 intent、rejection_reason、intent_filter_reason 模型字段和请求模型"
```

---

### Task 2: 置信度评分调整

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/confidence.py`

- [ ] **Step 1: 移除 `BUSINESS_PATH_MARKERS`**

删除第27-33行的 `BUSINESS_PATH_MARKERS` 元组定义。

- [ ] **Step 2: 调整 `score_api_candidate` 中的分值**

在 `score_api_candidate` 函数中做以下修改：

a) 将 `action_window_matched` 的加分从 `+30` 改为 `+35`（约第83-86行）：

```python
    if action_window_matched:
        score += 35
        breakdown["action_window"] = 35
```

b) 删除 `business_path` 相关的加分逻辑（约第96-101行）：

```python
    # 删除以下代码块：
    # if business_path:
    #     score += 25
    #     breakdown["business_path"] = 25
    #     reasons.append("路径疑似业务接口")
    # else:
    #     breakdown["business_path"] = 0
```

同时删除第79行的 `business_path = any(marker in path for marker in BUSINESS_PATH_MARKERS)` 变量赋值。

c) 将 `json_response` 的加分从 `+20` 改为 `+25`（约第103-108行）：

```python
    if json_response:
        score += 25
        breakdown["json_response"] = 25
```

d) 简化 `response_richness`：将 `_score_response_richness` 调用替换为固定 +10（约第122-126行）：

```python
    if body and body.strip():
        score += 10
        breakdown["response_richness"] = 10
        reasons.append("有响应内容")
    else:
        breakdown["response_richness"] = 0
```

- [ ] **Step 3: 删除 `_score_response_richness` 函数**

删除第182-199行的 `_score_response_richness` 函数定义。

- [ ] **Step 4: 新增 `summarize_rejection_reasons` 函数**

在 `confidence.py` 文件末尾（`_dedupe` 函数之后）添加：

```python
NEGATIVE_LABELS: dict[str, str] = {
    "injected_source": "来源为注入脚本或扩展",
    "noise_path": "路径疑似后台请求",
    "no_action_window": "不在动作时间窗口内",
    "has_source": "缺少来源证据",
}


def summarize_rejection_reasons(result: ConfidenceResult) -> str:
    negatives = [
        (key, val) for key, val in result.breakdown.items() if val < 0
    ]
    negatives.sort(key=lambda kv: kv[1])
    parts = [
        f"{NEGATIVE_LABELS.get(key, key)}({val})"
        for key, val in negatives
    ]
    return f"置信度不足（{result.score}/100）：{'、'.join(parts)}" if parts else f"置信度不足（{result.score}/100）"
```

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/confidence.py
git commit -m "refactor: 移除 business_path，调整评分权重，新增淘汰理由生成"
```

---

### Task 3: AI 意图过滤模块

**Files:**
- Create: `RpaClaw/backend/rpa/api_monitor/intent_filter.py`

- [ ] **Step 1: 创建 `intent_filter.py`**

创建文件 `RpaClaw/backend/rpa/api_monitor/intent_filter.py`，内容如下：

```python
"""AI-based intent relevance filter for API Monitor tool candidates."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from .llm_analyzer import _call_llm
from .models import CapturedApiCall

logger = logging.getLogger(__name__)

INTENT_FILTER_SYSTEM = """\
You are an API relevance evaluator. Given a user's intent and an API endpoint, \
determine if the API is relevant to achieving the user's goal.

Rules:
- Be conservative: if you are unsure whether the API is relevant, respond "relevant"
- Consider the API's purpose based on its URL path, method, request body, and response
- An API is "not_relevant" only if you are confident it serves a completely different purpose \
  from the user's stated intent

Return a JSON object with exactly two fields:
- "relevant": boolean (true or false)
- "reason": string (brief explanation in Chinese, one sentence)
"""

INTENT_FILTER_USER = """\
用户意图：{intent}

API 端点：{method} {url}

请求体摘要：
{request_summary}

响应摘要：
{response_summary}

置信度理由：
{confidence_reasons}

判断此 API 是否与用户意图相关。返回 JSON。
"""


@dataclass(frozen=True)
class IntentFilterResult:
    relevant: bool
    reason: str


def _build_request_summary(calls: list[CapturedApiCall]) -> str:
    first = calls[0]
    body = first.request.body or ""
    if len(body) > 500:
        body = body[:500] + "..."
    return body if body else "(无请求体)"


def _build_response_summary(calls: list[CapturedApiCall]) -> str:
    first = calls[0]
    if not first.response:
        return "(无响应)"
    parts = [f"状态码: {first.response.status}"]
    if first.response.content_type:
        parts.append(f"Content-Type: {first.response.content_type}")
    body = first.response.body or ""
    if body:
        if len(body) > 500:
            body = body[:500] + "..."
        parts.append(f"响应体: {body}")
    return "\n".join(parts)


async def filter_by_intent(
    calls: list[CapturedApiCall],
    intent: str,
    confidence_reasons: list[str],
    *,
    model_config: Optional[dict] = None,
) -> IntentFilterResult:
    """Use LLM to judge whether an API candidate is relevant to user intent."""
    first = calls[0]
    user_prompt = INTENT_FILTER_USER.format(
        intent=intent,
        method=first.request.method,
        url=first.request.url,
        request_summary=_build_request_summary(calls),
        response_summary=_build_response_summary(calls),
        confidence_reasons="\n".join(f"- {r}" for r in confidence_reasons),
    )

    raw = await _call_llm(INTENT_FILTER_SYSTEM, user_prompt, model_config)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    try:
        parsed = json.loads(raw)
        relevant = bool(parsed.get("relevant", True))
        reason = str(parsed.get("reason", ""))
    except (json.JSONDecodeError, AttributeError):
        logger.warning("[IntentFilter] Failed to parse LLM response: %s", raw[:200])
        relevant = True
        reason = ""

    return IntentFilterResult(relevant=relevant, reason=reason)
```

- [ ] **Step 2: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/intent_filter.py
git commit -m "feat: 新增 AI 意图过滤模块 intent_filter.py"
```

---

### Task 4: Manager 核心流程改造 — 置信度前置与意图过滤

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`

- [ ] **Step 1: 添加 import**

在文件顶部的 import 区域（约第47行 `from .llm_analyzer import ...` 附近），添加：

```python
from .intent_filter import filter_by_intent
```

并在同区域的 `confidence` import 中确保 `summarize_rejection_reasons` 被导入：

```python
from .confidence import score_api_candidate, dedup_key_for_tool, summarize_rejection_reasons
```

（如果当前只导入了 `score_api_candidate`，则追加 `summarize_rejection_reasons`。）

- [ ] **Step 2: 修改 `_generate_tools_from_calls` — 置信度前置**

在 `_generate_tools_from_calls` 方法（约第1622行）中，替换 `for key, group_calls in groups.items():` 循环体（约第1667-1713行）为：

```python
        for key, group_calls in groups.items():
            # Take up to 5 samples per group
            samples = group_calls[:5]
            first = samples[0]
            method = first.request.method
            url_pattern = first.url_pattern or first.request.url

            # Round 1: Rule-based confidence scoring (before LLM generation)
            confidence_result = score_api_candidate(samples)

            if confidence_result.score < 80:
                # Create candidate as confidence_rejected, skip LLM generation
                candidate = self._create_rejected_candidate(
                    session_id, key, method, url_pattern, samples,
                    confidence_result, dom_context=dom_context,
                    page_url=session.target_url or "",
                )
                session.generation_candidates.append(candidate)
                self._emit_analysis_event(
                    session_id, "api_candidate_confidence_rejected",
                    {**self._candidate_event_payload(candidate), "score": confidence_result.score},
                )
                continue

            # Round 2: AI intent filter (only when intent is provided)
            intent = session.intent
            final_score = confidence_result.score
            if intent and intent.strip():
                try:
                    intent_result = await filter_by_intent(
                        samples, intent.strip(), confidence_result.reasons,
                        model_config=model_config,
                    )
                    if not intent_result.relevant:
                        final_score = confidence_result.score - 25

                        candidate = self._create_rejected_candidate(
                            session_id, key, method, url_pattern, samples,
                            confidence_result, dom_context=dom_context,
                            page_url=session.target_url or "",
                            status="intent_filtered",
                            intent_filter_reason=intent_result.reason,
                            adjusted_score=final_score,
                        )
                        session.generation_candidates.append(candidate)
                        self._emit_analysis_event(
                            session_id, "api_candidate_intent_filtered",
                            {
                                **self._candidate_event_payload(candidate),
                                "score": final_score,
                                "intent_filter_reason": intent_result.reason,
                            },
                        )
                        continue
                except Exception as exc:
                    logger.warning("[ApiMonitor] Intent filter failed for %s: %s", key, exc)
                    # Fall through to generate (conservative: don't block on AI failure)

            # Generate tool definition via LLM
            try:
                yaml_def = await generate_tool_definition(
                    method=method,
                    url_pattern=url_pattern,
                    samples=samples,
                    page_context=session.target_url or "",
                    dom_context=dom_context,
                    model_config=model_config,
                )

                name, description = self._parse_yaml_metadata(yaml_def)

                tool = ApiToolDefinition(
                    session_id=session_id,
                    name=name,
                    description=description,
                    method=method,
                    url_pattern=url_pattern,
                    yaml_definition=yaml_def,
                    source_calls=[c.id for c in samples],
                    source=source,
                    confidence=confidence_result.confidence,
                    score=confidence_result.score,
                    selected=True,
                    confidence_reasons=confidence_result.reasons,
                    source_evidence=confidence_result.evidence_summary,
                )

                session.tool_definitions.append(tool)
                tools.append(tool)

                logger.info(
                    "[ApiMonitor] Generated tool '%s' for %s %s (score: %d)",
                    name, method, url_pattern, confidence_result.score,
                )

            except Exception as exc:
                logger.warning(
                    "[ApiMonitor] Failed to generate tool for %s: %s",
                    key, exc,
                )
```

- [ ] **Step 3: 添加 `_create_rejected_candidate` 辅助方法**

在 `_apply_confidence_to_tool` 函数（约第350行，是模块级函数）之后，添加一个新的模块级函数：

```python
def _create_rejected_candidate(
    session_id: str,
    dedup_key: str,
    method: str,
    url_pattern: str,
    samples: List[CapturedApiCall],
    confidence_result,
    *,
    dom_context: str = "",
    page_url: str = "",
    status: str = "confidence_rejected",
    intent_filter_reason: Optional[str] = None,
    adjusted_score: Optional[int] = None,
) -> ApiToolGenerationCandidate:
    import json as _json
    dom_dict: Dict = {}
    if dom_context:
        try:
            dom_dict = _json.loads(dom_context)
        except (json.JSONDecodeError, TypeError):
            pass
    candidate = ApiToolGenerationCandidate(
        session_id=session_id,
        dedup_key=dedup_key,
        method=method,
        url_pattern=url_pattern,
        source_call_ids=[c.id for c in samples],
        sample_call_ids=[c.id for c in samples[:5]],
        status=status,
        capture_dom_context=dom_dict,
        capture_page_url=page_url,
        rejection_reason=summarize_rejection_reasons(confidence_result) if status == "confidence_rejected" else None,
        intent_filter_reason=intent_filter_reason,
    )
    return candidate
```

- [ ] **Step 4: 修改 `_generate_tool_for_candidate` — 置信度前置**

在 `_generate_tool_for_candidate` 方法（约第2131行）中，在获取 samples 之后、设置 `candidate.status = "running"` 之前（约第2153行），添加置信度前置判断：

在 `generated_sample_ids = {call.id for call in samples}` 之后，`candidate.status = "running"` 之前，插入：

```python
        # Round 1: Confidence scoring before LLM generation
        confidence_result = score_api_candidate(
            samples,
            action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
        )
        if confidence_result.score < 80:
            candidate.status = "confidence_rejected"
            candidate.rejection_reason = summarize_rejection_reasons(confidence_result)
            candidate.updated_at = datetime.now()
            session.updated_at = datetime.now()
            self._emit_analysis_event(
                session_id, "api_candidate_confidence_rejected",
                {**self._candidate_event_payload(candidate), "score": confidence_result.score},
            )
            return None

        # Round 2: AI intent filter
        intent = session.intent
        if intent and intent.strip():
            try:
                intent_result = await filter_by_intent(
                    samples, intent.strip(), confidence_result.reasons,
                    model_config=model_config,
                )
                if not intent_result.relevant:
                    final_score = confidence_result.score - 25
                    candidate.status = "intent_filtered"
                    candidate.intent_filter_reason = intent_result.reason
                    candidate.updated_at = datetime.now()
                    session.updated_at = datetime.now()
                    self._emit_analysis_event(
                        session_id, "api_candidate_intent_filtered",
                        {
                            **self._candidate_event_payload(candidate),
                            "score": final_score,
                            "intent_filter_reason": intent_result.reason,
                        },
                    )
                    return None
            except Exception as exc:
                logger.warning("[ApiMonitor] Intent filter failed for candidate %s: %s", candidate_id, exc)
```

然后修改后面的 `_apply_confidence_to_tool` 调用。将原来的：

```python
        tool = _apply_confidence_to_tool(
            tool, samples,
            action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
        )
```

替换为直接使用已有的 `confidence_result`：

```python
        tool.confidence = confidence_result.confidence
        tool.score = confidence_result.score
        tool.selected = True
        tool.confidence_reasons = confidence_result.reasons
        tool.source_evidence = confidence_result.evidence_summary
```

- [ ] **Step 5: 更新 `_candidate_event_payload` 添加新字段**

在 `_candidate_event_payload` 方法（约第454行）中，在返回的 dict 中添加：

```python
    def _candidate_event_payload(self, candidate: ApiToolGenerationCandidate) -> dict:
        return {
            "candidate_id": candidate.id,
            "dedup_key": candidate.dedup_key,
            "method": candidate.method,
            "url_pattern": candidate.url_pattern,
            "status": candidate.status,
            "source_call_count": len(candidate.source_call_ids),
            "tool_id": candidate.tool_id,
            "error": candidate.error,
            "retry_after": candidate.retry_after.isoformat() if candidate.retry_after else None,
            "rejection_reason": candidate.rejection_reason,
            "intent_filter_reason": candidate.intent_filter_reason,
        }
```

- [ ] **Step 6: 新增 `force_generate_candidate` 方法**

在 `retry_generation_candidate` 方法（约第2371行）之后添加：

```python
    def force_generate_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
    ) -> ApiToolGenerationCandidate:
        session = self._require_session(session_id)
        candidate = next(
            (item for item in session.generation_candidates if item.id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("Generation candidate not found")
        if candidate.status not in ("confidence_rejected", "intent_filtered"):
            raise ValueError("Only rejected/filtered candidates can be force-generated")
        candidate.status = "pending"
        candidate.error = ""
        candidate.retry_after = None
        candidate.rejection_reason = None
        candidate.intent_filter_reason = None
        candidate.updated_at = datetime.now()
        self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
        return candidate
```

- [ ] **Step 7: 修改 `_run_generation_candidate` 的重试状态判断**

在 `_run_generation_candidate` 方法（约第2044行）中，约第2082行，将：

```python
    if followup_requested and candidate and candidate.status in ("pending", "stale", "failed"):
```

改为：

```python
    if followup_requested and candidate and candidate.status in ("pending", "stale", "failed", "confidence_rejected", "intent_filtered"):
```

- [ ] **Step 8: 修改 `reconcile_generation_candidates` 排除已淘汰状态**

在 `reconcile_generation_candidates` 方法（约第2347行）中，约第2358行，将：

```python
    if created or candidate.status in ("pending", "failed", "rate_limited", "stale"):
```

改为：

```python
    if created or candidate.status in ("pending", "failed", "rate_limited", "stale", "confidence_rejected", "intent_filtered"):
```

- [ ] **Step 9: 修改 `start_recording` 和 `analyze_page`/`analyze_directed_page` 接收 intent**

a) `start_recording` 方法（约第724行）添加 `intent` 参数：

```python
    async def start_recording(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
        intent: Optional[str] = None,
    ) -> None:
```

在方法体中，`session.status = "recording"` 之前添加：

```python
        session.intent = intent
```

b) `analyze_page` 方法（约第894行）添加 `intent` 参数：

```python
    async def analyze_page(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
        intent: Optional[str] = None,
    ) -> AsyncGenerator[Dict, None]:
```

在方法体开头添加：

```python
        session = self._require_session(session_id)
        session.intent = intent
```

c) `analyze_directed_page` 方法（约第1032行）已接收 `instruction` 参数，在方法体开头添加：

```python
        session = self._require_session(session_id)
        session.intent = instruction
```

注意：检查 `analyze_directed_page` 是否已有 `session = self._require_session(session_id)` 调用，避免重复。如果有，只需在其后添加 `session.intent = instruction`。

- [ ] **Step 10: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "feat: 置信度前置 + AI 意图过滤集成到 manager 核心流程"
```

---

### Task 5: API 路由变更

**Files:**
- Modify: `RpaClaw/backend/route/api_monitor.py`

- [ ] **Step 1: 修改 `analyze_session` 路由传递 intent**

在 `analyze_session` 路由（约第235行）中，在 `instruction = payload.instruction.strip()` 之后，提取 intent：

```python
    intent = payload.intent or instruction or None
```

然后在调用 `analyze_page` 和 `analyze_directed_page` 时传入 `intent`：

将 `source = api_monitor_manager.analyze_page(session_id, model_config=model_config)` 改为：

```python
                source = api_monitor_manager.analyze_page(session_id, model_config=model_config, intent=intent)
```

将 `api_monitor_manager.analyze_directed_page(session_id, instruction=instruction, ...)` 改为：

```python
                    api_monitor_manager.analyze_directed_page(
                        session_id,
                        instruction=instruction,
                        mode=mode_config.key,
                        business_safety=mode_config.business_safety,
                        model_config=model_config,
                    )
```

注意：`analyze_directed_page` 内部会用 `instruction` 设置 `session.intent`，无需额外传参。

- [ ] **Step 2: 修改 `start_recording` 路由接收 intent**

将 `start_recording` 路由（约第322行）改为：

```python
@router.post("/session/{session_id}/record/start")
async def start_recording(
    session_id: str,
    request: UpdateSessionIntentRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
):
    session = api_monitor_manager.get_session(session_id)
    _verify_session_owner(session, current_user)
    model_config = await _resolve_user_model_config(str(current_user.id))
    intent = request.intent if request else None
    await api_monitor_manager.start_recording(session_id, model_config=model_config, intent=intent)
    return {"status": "success"}
```

- [ ] **Step 3: 新增 `update_session_intent` 路由**

在 `retry_generation_candidate` 路由（约第379行）之后添加：

```python
@router.put("/session/{session_id}/intent")
async def update_session_intent(
    session_id: str,
    request: UpdateSessionIntentRequest,
    current_user: User = Depends(get_current_user),
):
    session = api_monitor_manager.get_session(session_id)
    _verify_session_owner(session, current_user)
    session.intent = request.intent or None
    session.updated_at = __import__('datetime').datetime.now()
    return {"status": "success", "intent": session.intent}
```

- [ ] **Step 4: 新增 `force_generate_candidate` 路由**

在 `update_session_intent` 路由之后添加：

```python
@router.post("/session/{session_id}/generation-candidates/{candidate_id}/force-generate")
async def force_generate_candidate(
    session_id: str,
    candidate_id: str,
    request: ForceGenerateRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
):
    session = api_monitor_manager.get_session(session_id)
    _verify_session_owner(session, current_user)
    model_config = await _resolve_user_model_config(
        str(current_user.id),
        model_id=request.model_id if request else None,
    )
    try:
        candidate = api_monitor_manager.force_generate_candidate(
            session_id,
            candidate_id,
            model_config=model_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "candidate": candidate.model_dump(mode="json")}
```

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/route/api_monitor.py
git commit -m "feat: 新增 intent/force-generate API 端点，修改录制和分析路由"
```

---

### Task 6: 前端类型和 API 函数

**Files:**
- Modify: `RpaClaw/frontend/src/api/apiMonitor.ts`

- [ ] **Step 1: 扩展 `ApiToolGenerationStatus` 类型**

在第12行，将类型定义扩展：

```typescript
export type ApiToolGenerationStatus =
  | 'pending'
  | 'running'
  | 'generated'
  | 'failed'
  | 'rate_limited'
  | 'stale'
  | 'confidence_rejected'
  | 'intent_filtered'
```

- [ ] **Step 2: 扩展 `ApiToolGenerationCandidate` 接口**

在 `ApiToolGenerationCandidate` 接口（第20行）中，在 `updated_at` 之前添加：

```typescript
  rejection_reason?: string | null
  intent_filter_reason?: string | null
```

- [ ] **Step 3: 扩展 `ApiMonitorSession` 接口**

在 `ApiMonitorSession` 接口（第90行）中，在 `target_url` 之后添加：

```typescript
  intent?: string | null
```

- [ ] **Step 4: 扩展 `AnalyzeSessionPayload` 接口**

在 `AnalyzeSessionPayload` 接口（第116行）中，在 `model_id` 之前添加：

```typescript
  intent?: string
```

- [ ] **Step 5: 修改 `analyzeSession` 函数传递 intent**

在 `analyzeSession` 函数（第256行）中，修改 `body` 对象：

```typescript
  const body = {
    mode: payload.mode || 'free',
    instruction: payload.instruction || '',
    intent: payload.intent || '',
    ...(payload.model_id ? { model_id: payload.model_id } : {}),
  }
```

- [ ] **Step 6: 修改 `startRecording` 函数接收 intent**

将 `startRecording` 函数（第290行）改为：

```typescript
export async function startRecording(sessionId: string, intent?: string): Promise<void> {
  await apiClient.post(`/api-monitor/session/${sessionId}/record/start`, { intent: intent || '' })
}
```

- [ ] **Step 7: 新增 `updateSessionIntent` 和 `forceGenerateCandidate` 函数**

在文件末尾（`retryGenerationCandidate` 函数之后）添加：

```typescript
/**
 * Update the intent description for a session.
 */
export async function updateSessionIntent(sessionId: string, intent: string): Promise<void> {
  await apiClient.put(`/api-monitor/session/${sessionId}/intent`, { intent })
}

/**
 * Force-generate a tool definition for a rejected/filtered candidate.
 */
export async function forceGenerateCandidate(
  sessionId: string,
  candidateId: string,
): Promise<ApiToolGenerationCandidate> {
  const response = await apiClient.post(
    `/api-monitor/session/${sessionId}/generation-candidates/${candidateId}/force-generate`,
  )
  return response.data.candidate
}
```

- [ ] **Step 8: Commit**

```bash
git add RpaClaw/frontend/src/api/apiMonitor.ts
git commit -m "feat: 前端类型和 API 函数扩展 — intent、force-generate"
```

---

### Task 7: 前端 UI 变更

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`

- [ ] **Step 1: 添加 intent 相关的 ref**

在 `analysisInstruction` ref（约第93行）之后添加：

```typescript
const analysisIntent = ref('')
```

- [ ] **Step 2: 修改 `analyzeSession` 调用传递 intent**

找到 `analyzeSession` 的调用处（搜索 `analyzeSession(`），在 payload 中添加 `intent`：

```typescript
analysisCleanup = analyzeSession(sessionId.value, handleAnalysisEvent, {
  mode: analysisMode.value,
  instruction: analysisInstruction.value,
  intent: analysisIntent.value,
  ...(selectedModelId.value ? { model_id: selectedModelId.value } : {}),
})
```

- [ ] **Step 3: 修改 `startRecording` 调用传递 intent**

找到 `startRecording` 的调用处（搜索 `startRecording(`），改为：

```typescript
await startRecording(sessionId.value, analysisIntent.value)
```

- [ ] **Step 4: 修改 `visibleGenerationCandidates` 过滤条件**

将 `visibleGenerationCandidates` computed（约第74行）改为包含新的状态：

```typescript
const visibleGenerationCandidates = computed(() =>
  generationCandidates.value.filter((candidate) =>
    candidate.status !== 'generated' || !candidate.tool_id
  ),
);
```

（无需修改，当前逻辑已包含所有非 generated 的候选。）

- [ ] **Step 5: 修改 `getCandidateStatusLabel` 添加新状态标签**

将 `getCandidateStatusLabel` 函数（约第997行）扩展：

```typescript
const getCandidateStatusLabel = (status: ApiToolGenerationCandidate['status']) => {
  if (status === 'pending') return '等待生成'
  if (status === 'running') return '生成中'
  if (status === 'rate_limited') return '限流重试中'
  if (status === 'failed') return '生成失败'
  if (status === 'stale') return '等待更新'
  if (status === 'confidence_rejected') return '置信度不足'
  if (status === 'intent_filtered') return 'AI 过滤'
  return '已生成'
}
```

- [ ] **Step 6: 修改 `getCandidateStatusClass` 添加新状态样式**

将 `getCandidateStatusClass` 函数（约第1006行）扩展：

```typescript
const getCandidateStatusClass = (status: ApiToolGenerationCandidate['status']) => {
  if (status === 'running' || status === 'pending') return 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300'
  if (status === 'rate_limited') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300'
  if (status === 'failed') return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
  if (status === 'confidence_rejected') return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300'
  if (status === 'intent_filtered') return 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-500/30 dark:bg-purple-500/10 dark:text-purple-300'
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300'
}
```

- [ ] **Step 7: 在候选列表模板中添加拒绝理由展示和强制生成按钮**

找到候选列表模板（约第1316-1350行），将整个 `v-for="candidate in visibleGenerationCandidates"` 的 div 内容替换为：

```vue
<div
  v-for="candidate in visibleGenerationCandidates"
  :key="candidate.id"
  class="rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 shadow-sm dark:border-white/10 dark:bg-white/[0.04]"
>
  <div class="flex items-center gap-3">
    <span class="text-[10px] font-bold px-2 py-0.5 rounded-md" :class="getMethodClass(candidate.method)">
      {{ candidate.method }}
    </span>
    <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--text-primary)]">
      {{ candidate.url_pattern }}
    </span>
    <span class="shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-bold" :class="getCandidateStatusClass(candidate.status)">
      {{ getCandidateStatusLabel(candidate.status) }}
    </span>
  </div>
  <!-- Rejection/intent filter reason -->
  <div v-if="candidate.rejection_reason || candidate.intent_filter_reason" class="mt-1.5 text-[10px] text-orange-600 dark:text-orange-400">
    {{ candidate.rejection_reason || candidate.intent_filter_reason }}
  </div>
  <div class="mt-2 flex items-center justify-between gap-3 text-[10px] text-[var(--text-tertiary)]">
    <span>样本 {{ candidate.source_call_ids?.length || 0 }}</span>
    <span v-if="candidate.retry_after">下次重试 {{ new Date(candidate.retry_after).toLocaleTimeString() }}</span>
    <span v-else-if="candidate.error" class="truncate text-red-500">{{ candidate.error }}</span>
    <div class="flex gap-2">
      <button
        v-if="candidate.status === 'failed' || candidate.status === 'rate_limited'"
        class="rounded-lg border border-slate-200 px-2 py-1 font-bold text-[var(--text-secondary)] transition hover:bg-slate-100 dark:border-white/10 dark:hover:bg-white/10"
        @click="handleRetryCandidate(candidate)"
      >
        重试
      </button>
      <button
        v-if="candidate.status === 'confidence_rejected' || candidate.status === 'intent_filtered'"
        class="rounded-lg border border-blue-200 bg-blue-50 px-2 py-1 font-bold text-blue-600 transition hover:bg-blue-100 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300"
        @click="handleForceGenerate(candidate)"
      >
        强制生成
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 8: 添加 `handleForceGenerate` 处理函数**

在 `handleRetryCandidate` 函数（约第661行）之后添加：

```typescript
const handleForceGenerate = async (candidate: ApiToolGenerationCandidate) => {
  try {
    const updated = await forceGenerateCandidate(sessionId.value, candidate.id)
    Object.assign(candidate, updated)
  } catch (err) {
    console.error('Force generate failed:', err)
  }
}
```

并在文件顶部确保 `forceGenerateCandidate` 已从 api 中导入：

```typescript
import { ..., forceGenerateCandidate } from '@/api/apiMonitor'
```

- [ ] **Step 9: 在分析区域添加意图输入框**

在分析模式选择按钮区域附近（搜索 `analysisInstruction` 相关的 textarea），在自由分析模式下添加意图输入。找到指令输入区域，在 `instruction` 输入框之后添加意图输入框。

找到指令输入的 textarea（搜索 `v-model="analysisInstruction"`），在其后面、分析按钮之前，添加：

```vue
<!-- Intent input for free analysis and recording -->
<div v-if="analysisMode === 'free'" class="mt-2">
  <textarea
    v-model="analysisIntent"
    placeholder="描述你希望获取的 API 类型（可选）..."
    rows="2"
    class="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-blue-400 focus:outline-none dark:border-white/10 dark:bg-white/5"
  />
</div>
```

- [ ] **Step 10: 修改 SSE 事件处理，处理新的事件类型**

在 SSE 事件处理函数（搜索 `handleAnalysisEvent` 或事件名称匹配逻辑）中，确保处理新的事件类型：

```typescript
if (data.event === 'api_candidate_confidence_rejected' || data.event === 'api_candidate_intent_filtered') {
  const candidateData = data.data
  const idx = generationCandidates.value.findIndex(c => c.id === candidateData.candidate_id)
  if (idx >= 0) {
    Object.assign(generationCandidates.value[idx], {
      status: candidateData.status,
      rejection_reason: candidateData.rejection_reason,
      intent_filter_reason: candidateData.intent_filter_reason,
    })
  } else {
    generationCandidates.value.push(candidateData as ApiToolGenerationCandidate)
  }
}
```

注意：根据实际的事件处理结构，可能需要适配。请查看现有 `api_candidate_created` 和 `api_candidate_updated` 事件的处理方式，参照相同的模式。

- [ ] **Step 11: Commit**

```bash
git add RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
git commit -m "feat: 前端意图输入、候选状态展示、强制生成 UI"
```

---

### Task 8: i18n 翻译

**Files:**
- Modify: `RpaClaw/frontend/src/locales/zh.ts`
- Modify: `RpaClaw/frontend/src/locales/en.ts`

- [ ] **Step 1: 在中文翻译文件中添加新键**

在 `zh.ts` 中与 API Monitor 相关的翻译键附近添加：

```typescript
  'Intent description': '目的描述',
  'Intent placeholder': '描述你希望获取的 API 类型（可选）...',
  'Confidence rejected': '置信度不足',
  'Intent filtered': 'AI 过滤',
  'Force generate': '强制生成',
```

- [ ] **Step 2: 在英文翻译文件中添加新键**

在 `en.ts` 中与 API Monitor 相关的翻译键附近添加：

```typescript
  'Intent description': 'Intent Description',
  'Intent placeholder': 'Describe the type of APIs you want to capture (optional)...',
  'Confidence rejected': 'Low Confidence',
  'Intent filtered': 'AI Filtered',
  'Force generate': 'Force Generate',
```

- [ ] **Step 3: Commit**

```bash
git add RpaClaw/frontend/src/locales/zh.ts RpaClaw/frontend/src/locales/en.ts
git commit -m "feat: 新增意图过滤相关 i18n 翻译"
```

---

## Self-Review Checklist

**1. Spec Coverage:**
- [x] 移除 business_path → Task 2
- [x] 调整评分权重 → Task 2
- [x] 淘汰理由生成 → Task 2 (summarize_rejection_reasons) + Task 3 (AI reason)
- [x] AI 意图过滤模块 → Task 3
- [x] 数据模型变更 → Task 1
- [x] 评分流程前置 → Task 4
- [x] API 变更 → Task 5
- [x] SSE 事件 → Task 4 + Task 7
- [x] 前端意图输入 → Task 7
- [x] 前端候选状态展示 → Task 7
- [x] 前端 API 函数 → Task 6
- [x] i18n → Task 8
