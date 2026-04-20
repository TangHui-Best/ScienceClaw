from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.config import settings


_SENSITIVE_PARAM_RE = re.compile(
    r"password|passcode|token|secret|cookie|cookies|credential|验证码|动态码|短信码|密码|口令|账号|帐号|账户|用户名|邮箱|手机号|手机",
    re.IGNORECASE,
)


@dataclass
class RpaMcpSemanticRecommendation:
    source: str
    tool_name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    params: dict[str, Any]
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    model: str = ""


class RpaMcpSemanticInferer:
    def __init__(self, model_client: Any | None = None) -> None:
        self._model_client = model_client

    async def infer(
        self,
        *,
        requested_name: str,
        requested_description: str,
        steps: list[dict[str, Any]],
        removed_step_details: list[dict[str, Any]],
        fallback_params: dict[str, Any],
    ) -> RpaMcpSemanticRecommendation:
        if not self._can_use_model():
            return self._fallback(
                requested_name,
                requested_description,
                fallback_params,
                ["Semantic inference model is not configured."],
            )

        context = self._build_context(steps, removed_step_details)
        try:
            response = await asyncio.wait_for(
                self._client().ainvoke(self._messages(requested_name, requested_description, context)),
                timeout=max(1, int(settings.rpa_mcp_semantic_timeout_seconds)),
            )
            payload = self._parse_json(str(getattr(response, "content", "") or ""))
            return self._validate_payload(payload, requested_name, requested_description, fallback_params)
        except Exception as exc:
            return self._fallback(
                requested_name,
                requested_description,
                fallback_params,
                [f"Semantic inference failed: {exc.__class__.__name__}"],
            )

    def _can_use_model(self) -> bool:
        if self._model_client is not None:
            return True
        return bool(settings.rpa_mcp_semantic_inference and settings.model_ds_api_key)

    def _client(self) -> Any:
        if self._model_client is not None:
            return self._model_client
        return ChatOpenAI(
            model=settings.model_ds_name,
            base_url=settings.model_ds_base_url,
            api_key=settings.model_ds_api_key,
            temperature=0,
            max_tokens=2000,
        )

    def _messages(self, requested_name: str, requested_description: str, context: dict[str, Any]) -> list[Any]:
        return [
            SystemMessage(
                content=(
                    "You infer MCP tool metadata from sanitized RPA browser steps. "
                    "Return strict JSON only. Never add login, account, password, cookie, token, or credential parameters."
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "requested_name": requested_name,
                        "requested_description": requested_description,
                        "sanitized_context": context,
                        "required_json_shape": {
                            "tool": {
                                "tool_name": "snake_case",
                                "display_name": "Human title",
                                "description": "What the tool does",
                            },
                            "input_schema": {"type": "object", "properties": {}, "required": []},
                            "params": {},
                            "warnings": [],
                        },
                    },
                    ensure_ascii=False,
                )
            ),
        ]

    def _build_context(self, steps: list[dict[str, Any]], removed_step_details: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "steps": [self._step_context(index, step) for index, step in enumerate(steps)],
            "removed_login_steps": [
                {
                    "index": detail.get("index"),
                    "action": detail.get("action"),
                    "description": detail.get("description"),
                    "url": detail.get("url"),
                }
                for detail in removed_step_details
            ],
        }

    def _step_context(self, index: int, step: dict[str, Any]) -> dict[str, Any]:
        description = str(step.get("description") or "")
        value = "" if _SENSITIVE_PARAM_RE.search(description) else step.get("value", "")
        return {
            "index": index,
            "action": step.get("action"),
            "description": description,
            "url": step.get("url"),
            "target": self._safe_target(step.get("target")),
            "example_value": value,
        }

    def _safe_target(self, target: Any) -> Any:
        if not isinstance(target, str):
            return target
        try:
            parsed = json.loads(target)
        except json.JSONDecodeError:
            return target[:300]
        allowed = {}
        for key in ("method", "role", "name", "value", "placeholder", "label", "text", "title", "alt"):
            if key in parsed:
                allowed[key] = parsed[key]
        return allowed

    def _parse_json(self, content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            stripped = re.sub(r"^json\s*", "", stripped.strip(), flags=re.IGNORECASE)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("No JSON object found")
        return json.loads(stripped[start:end + 1])

    def _validate_payload(
        self,
        payload: dict[str, Any],
        requested_name: str,
        requested_description: str,
        fallback_params: dict[str, Any],
    ) -> RpaMcpSemanticRecommendation:
        tool = payload.get("tool") or {}
        tool_name = self._snake_case(str(tool.get("tool_name") or requested_name or "rpa_tool"))
        display_name = str(tool.get("display_name") or requested_name or tool_name)
        description = str(tool.get("description") or requested_description or "")
        schema = payload.get("input_schema") if isinstance(payload.get("input_schema"), dict) else {}
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        warnings = [str(item) for item in payload.get("warnings", []) if str(item).strip()]

        clean_params = {}
        clean_properties = {}
        clean_required = []
        for raw_name, info in params.items():
            name = self._snake_case(str(raw_name))
            if not name or _SENSITIVE_PARAM_RE.search(name):
                warnings.append(f"Dropped sensitive parameter recommendation: {raw_name}")
                continue
            info_dict = dict(info or {})
            prop = dict((schema.get("properties") or {}).get(raw_name) or (schema.get("properties") or {}).get(name) or {})
            if _SENSITIVE_PARAM_RE.search(str(prop.get("description") or "")) or _SENSITIVE_PARAM_RE.search(str(info_dict.get("description") or "")):
                warnings.append(f"Dropped sensitive parameter recommendation: {raw_name}")
                continue
            prop.setdefault("type", "string")
            prop.setdefault("description", str(info_dict.get("description") or name))
            if info_dict.get("original_value") not in (None, ""):
                prop["default"] = info_dict.get("original_value")
            clean_properties[name] = prop
            clean_params[name] = info_dict
            clean_params[name]["description"] = prop["description"]
            clean_params[name]["type"] = prop["type"]
            if raw_name in schema.get("required", []) or name in schema.get("required", []) or clean_params[name].get("required"):
                clean_required.append(name)

        if not clean_params and fallback_params:
            fallback = self._fallback(
                requested_name,
                requested_description,
                fallback_params,
                ["Semantic inference returned no usable parameters."],
            )
            fallback.tool_name = tool_name
            fallback.display_name = display_name
            fallback.description = description
            return fallback

        return RpaMcpSemanticRecommendation(
            source="ai_inferred",
            tool_name=tool_name,
            display_name=display_name,
            description=description,
            input_schema={"type": "object", "properties": clean_properties, "required": clean_required},
            params=clean_params,
            confidence=self._average_confidence(clean_params),
            warnings=warnings,
            model=settings.model_ds_name,
        )

    def _fallback(
        self,
        requested_name: str,
        requested_description: str,
        fallback_params: dict[str, Any],
        warnings: list[str],
    ) -> RpaMcpSemanticRecommendation:
        properties = {}
        required = []
        for key, info in fallback_params.items():
            info_dict = dict(info or {})
            properties[key] = {
                "type": info_dict.get("type", "string"),
                "description": info_dict.get("description", ""),
            }
            if info_dict.get("original_value") not in (None, ""):
                properties[key]["default"] = info_dict.get("original_value")
            if info_dict.get("required"):
                required.append(key)
        return RpaMcpSemanticRecommendation(
            source="rule_inferred",
            tool_name=self._snake_case(requested_name or "rpa_tool"),
            display_name=requested_name or "RPA tool",
            description=requested_description or "",
            input_schema={"type": "object", "properties": properties, "required": required},
            params={key: dict(value or {}) for key, value in fallback_params.items()},
            warnings=warnings,
            model="",
        )

    def _average_confidence(self, params: dict[str, Any]) -> float | None:
        values = [
            float(info.get("confidence"))
            for info in params.values()
            if isinstance(info, dict) and info.get("confidence") is not None
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    def _snake_case(self, value: str) -> str:
        normalized = re.sub(r"[^0-9a-zA-Z]+", "_", value.strip().lower()).strip("_")
        return normalized or "rpa_tool"
