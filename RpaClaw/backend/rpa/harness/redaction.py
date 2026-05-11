from __future__ import annotations

import re
from typing import Any

from backend.rpa.harness.packets import RPAHarnessRedactionPolicy


_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]+)")


def redact_payload(
    payload: Any,
    policy: RPAHarnessRedactionPolicy | None = None,
) -> Any:
    policy = policy or RPAHarnessRedactionPolicy()
    if not policy.enabled:
        return payload

    sensitive_keys = {key.lower() for key in policy.sensitive_keys}
    sensitive_key_pattern = "|".join(re.escape(key) for key in sorted(sensitive_keys))
    query_value_re = re.compile(
        rf"(?i)([?&](?:{sensitive_key_pattern})=)([^&#\s]+)"
    )
    assignment_value_re = re.compile(
        rf"(?i)\b({sensitive_key_pattern})\b(\s*[:=]\s*)(['\"]?)([^'\"\s,;}}]+)(['\"]?)"
    )
    quoted_key_value_re = re.compile(
        rf"(?i)(['\"](?:{sensitive_key_pattern})['\"]\s*:\s*)(['\"])(.*?)(\2)"
    )
    fill_call_re = re.compile(
        rf"(?i)(\b(?:fill|type|select_option)\s*\(\s*['\"][^'\"]*(?:{sensitive_key_pattern})[^'\"]*['\"]\s*,\s*)(['\"])(.*?)(\2)"
    )

    def is_sensitive_label(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return any(key in normalized for key in sensitive_keys)

    def redact_text(value: str) -> str:
        text = _EMAIL_RE.sub(policy.replacement, value)
        text = _BEARER_RE.sub(f"Bearer {policy.replacement}", text)
        text = query_value_re.sub(rf"\1{policy.replacement}", text)
        text = quoted_key_value_re.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{policy.replacement}{match.group(4)}",
            text,
        )
        text = fill_call_re.sub(
            lambda match: f"{match.group(1)}{match.group(2)}{policy.replacement}{match.group(4)}",
            text,
        )
        text = assignment_value_re.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}"
                f"{match.group(3)}{policy.replacement}{match.group(5)}"
            ),
            text,
        )
        return text

    def redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            sensitive_labeled_value = any(
                is_sensitive_label(value.get(label_key))
                for label_key in ("label", "name", "text", "field", "title")
            )
            redacted = {}
            for key, item in value.items():
                normalized_key = str(key).lower()
                if normalized_key in sensitive_keys:
                    redacted[key] = policy.replacement
                elif sensitive_labeled_value and normalized_key in {
                    "value",
                    "content",
                    "inner_text",
                    "text_content",
                }:
                    redacted[key] = policy.replacement
                else:
                    redacted[key] = redact_value(item)
            return redacted
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    return redact_value(payload)
