from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_anthropic_model_verification_uses_native_messages_client(monkeypatch):
    from backend.route import models

    calls = []

    class NativeAnthropic:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        async def ainvoke(self, messages):
            calls.append(("invoke", messages))
            return object()

    class ForbiddenOpenAI:
        def __init__(self, **_kwargs):
            raise AssertionError("Anthropic must not use the OpenAI-compatible client")

    monkeypatch.setattr(models, "ChatAnthropic", NativeAnthropic)
    monkeypatch.setattr(models, "ChatOpenAI", ForbiddenOpenAI)

    assert await models.verify_model_connection(
        "anthropic",
        "https://anthropic.example",
        "secret-test-only",
        "claude-test",
    ) is True
    assert calls[0] == (
        "init",
        {
            "model": "claude-test",
            "api_key": "secret-test-only",
            "base_url": "https://anthropic.example",
            "max_tokens": 5,
            "timeout": 10,
        },
    )
    assert calls[1][0] == "invoke"
