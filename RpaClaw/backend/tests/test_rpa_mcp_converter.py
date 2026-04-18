import pytest

from backend.rpa.mcp_models import RpaMcpToolDefinition
from backend.rpa.mcp_converter import RpaMcpConverter


def test_rpa_mcp_tool_definition_defaults():
    tool = RpaMcpToolDefinition(
        id="rpa_mcp_tool_1",
        user_id="user-1",
        name="download_invoice",
        tool_name="rpa_download_invoice",
        description="Download invoice",
        allowed_domains=["example.com"],
        post_auth_start_url="https://example.com/dashboard",
        steps=[],
        params={},
        input_schema={"type": "object", "properties": {}, "required": []},
        sanitize_report={"removed_steps": [], "removed_params": [], "warnings": []},
        source={"type": "rpa_skill", "session_id": "session-1", "skill_name": "invoice_skill"},
    )

    assert tool.enabled is True
    assert tool.allowed_domains == ["example.com"]
    assert tool.sanitize_report.warnings == []


def test_preview_strips_login_steps_and_sensitive_params():
    converter = RpaMcpConverter()
    steps = [
        {"action": "navigate", "url": "https://example.com/login", "description": "Open login"},
        {"action": "fill", "target": '{"method":"label","value":"Email"}', "value": "alice@example.com", "description": "Fill email"},
        {"action": "fill", "target": '{"method":"label","value":"Password"}', "value": "{{credential}}", "description": "Fill password", "sensitive": True},
        {"action": "click", "target": '{"method":"role","role":"button","name":"Sign in"}', "description": "Sign in"},
        {"action": "navigate", "url": "https://example.com/dashboard", "description": "Open dashboard"},
        {"action": "click", "target": '{"method":"role","role":"button","name":"Export"}', "description": "Export invoice"},
    ]
    params = {
        "email": {"original_value": "alice@example.com"},
        "password": {"original_value": "{{credential}}", "sensitive": True, "credential_id": "cred-1"},
        "month": {"original_value": "2026-03", "description": "Invoice month"},
    }

    preview = converter.preview(
        user_id="user-1",
        session_id="session-1",
        skill_name="invoice_skill",
        name="download_invoice",
        description="Download invoice",
        steps=steps,
        params=params,
    )

    assert preview.post_auth_start_url == "https://example.com/dashboard"
    assert preview.allowed_domains == ["example.com"]
    assert preview.sanitize_report.removed_params == ["email", "password"]
    assert [step["description"] for step in preview.steps] == ["Open dashboard", "Export invoice"]
    assert "cookies" in preview.input_schema["required"]
    assert "password" not in preview.input_schema["properties"]


def test_preview_adds_warning_when_login_range_is_ambiguous():
    converter = RpaMcpConverter()
    steps = [
        {"action": "click", "target": '{"method":"role","role":"button","name":"Continue"}', "description": "Continue"},
        {"action": "navigate", "url": "https://example.com/workspace", "description": "Open workspace"},
    ]

    preview = converter.preview(
        user_id="user-1",
        session_id="session-1",
        skill_name="skill",
        name="workspace_tool",
        description="Workspace tool",
        steps=steps,
        params={},
    )

    assert preview.sanitize_report.warnings
