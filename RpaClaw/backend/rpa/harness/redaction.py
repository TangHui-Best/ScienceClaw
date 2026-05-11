from __future__ import annotations

from typing import Any

from backend.rpa.harness.packets import RPAHarnessRedactionPolicy


def redact_payload(
    payload: Any,
    policy: RPAHarnessRedactionPolicy | None = None,
) -> Any:
    policy = policy or RPAHarnessRedactionPolicy()
    if not policy.enabled:
        return payload

    sensitive_keys = {key.lower() for key in policy.sensitive_keys}

    def redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: policy.replacement
                if str(key).lower() in sensitive_keys
                else redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        return value

    return redact_value(payload)
