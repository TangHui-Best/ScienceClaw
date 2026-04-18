import pytest

from backend.rpa.mcp_executor import RpaMcpExecutor, InvalidCookieError
from backend.rpa.mcp_models import RpaMcpToolDefinition


class _FakePage:
    def __init__(self):
        self.calls = []

    async def goto(self, url):
        self.calls.append(("goto", url))


class _FakeContext:
    def __init__(self, page):
        self.calls = []
        self.page = page

    async def add_cookies(self, cookies):
        self.calls.append(("add_cookies", cookies))

    async def new_page(self):
        self.calls.append(("new_page", None))
        return self.page

    async def close(self):
        self.calls.append(("close", None))


class _FakeBrowser:
    def __init__(self, context):
        self.context = context

    async def new_context(self, **kwargs):
        return self.context


async def _fake_runner(page, script, kwargs):
    return {"success": True, "data": {"page_calls": page.calls, "kwargs": kwargs, "script": script}}


def _sample_tool():
    return RpaMcpToolDefinition(
        id="tool-1",
        user_id="user-1",
        name="download_invoice",
        tool_name="rpa_download_invoice",
        description="Download invoice",
        allowed_domains=["example.com"],
        post_auth_start_url="https://example.com/dashboard",
        steps=[{"action": "click", "target": '{"method":"role","role":"button","name":"Export"}', "description": "Export invoice"}],
        params={"month": {"original_value": "2026-03", "description": "Invoice month"}},
        input_schema={"type": "object", "properties": {"cookies": {"type": "array"}}, "required": ["cookies"]},
        sanitize_report={"removed_steps": [0], "removed_params": ["email", "password"], "warnings": []},
        source={"type": "rpa_skill", "session_id": "session-1", "skill_name": "invoice_skill"},
    )


def test_validate_cookies_rejects_disallowed_domain():
    executor = RpaMcpExecutor()

    with pytest.raises(InvalidCookieError):
        executor.validate_cookies(
            cookies=[{"name": "sessionid", "value": "secret", "domain": ".other.com", "path": "/"}],
            allowed_domains=["example.com"],
            post_auth_start_url="https://example.com/dashboard",
        )


@pytest.mark.anyio
async def test_execute_adds_cookies_before_goto():
    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    executor = RpaMcpExecutor(browser_factory=lambda *_args, **_kwargs: browser, script_runner=_fake_runner)

    tool = _sample_tool()
    await executor.execute(tool, {"cookies": [{"name": "sessionid", "value": "secret", "domain": ".example.com", "path": "/"}], "month": "2026-03"})

    assert context.calls[:2] == [
        ("add_cookies", [{"name": "sessionid", "value": "secret", "domain": ".example.com", "path": "/"}]),
        ("new_page", None),
    ]
    assert page.calls[0] == ("goto", "https://example.com/dashboard")

