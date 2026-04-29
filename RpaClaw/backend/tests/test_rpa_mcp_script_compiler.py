from backend.rpa.mcp_script_compiler import generate_mcp_script, has_trace_backed_steps


def test_generate_mcp_script_accepts_raw_trace_payloads():
    steps = [
        {
            "trace_id": "trace-open",
            "trace_type": "navigation",
            "source": "manual",
            "action": "navigate",
            "description": "Open dashboard",
            "after_page": {"url": "https://example.test/dashboard", "title": ""},
            "locator_candidates": [],
            "validation": {},
        }
    ]

    assert has_trace_backed_steps(steps) is True

    script = generate_mcp_script(steps, is_local=True)

    assert "Auto-generated skill from RPA trace recording" in script
    assert "https://example.test/dashboard" in script
