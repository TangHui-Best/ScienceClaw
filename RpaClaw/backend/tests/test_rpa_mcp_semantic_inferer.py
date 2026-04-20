import pytest

from backend.rpa.mcp_semantic_inferer import RpaMcpSemanticInferer


class FakeModelClient:
    def __init__(self, content: str):
        self.content = content
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        content = self.content

        class Response:
            pass

        response = Response()
        response.content = content
        return response


@pytest.mark.anyio
async def test_semantic_inferer_accepts_valid_recommendation():
    client = FakeModelClient('{"tool":{"tool_name":"search_reports","display_name":"Search reports","description":"Search reports by keyword."},"input_schema":{"type":"object","properties":{"report_keyword":{"type":"string","description":"Keyword used to search reports."}},"required":["report_keyword"]},"params":{"report_keyword":{"source_step_index":1,"original_value":"cancer","description":"Keyword used to search reports.","required":true,"confidence":0.86}},"warnings":[]}')
    recommendation = await RpaMcpSemanticInferer(model_client=client).infer(
        requested_name="rpa_tool",
        requested_description="",
        steps=[{"action": "fill", "description": "填写搜索关键词", "target": '{"method":"placeholder","value":"搜索关键词"}', "value": "cancer", "url": "https://example.com/search"}],
        removed_step_details=[],
        fallback_params={},
    )
    assert recommendation.source == "ai_inferred"
    assert recommendation.tool_name == "search_reports"
    assert recommendation.params["report_keyword"]["original_value"] == "cancer"


@pytest.mark.anyio
async def test_semantic_inferer_drops_sensitive_recommendations():
    client = FakeModelClient('{"tool":{"tool_name":"login_then_search","display_name":"Login then search","description":"Search."},"input_schema":{"type":"object","properties":{"password":{"type":"string","description":"Password"}},"required":["password"]},"params":{"password":{"source_step_index":0,"original_value":"secret","description":"Password","required":true,"confidence":0.9}},"warnings":[]}')
    recommendation = await RpaMcpSemanticInferer(model_client=client).infer(
        requested_name="login_then_search",
        requested_description="",
        steps=[],
        removed_step_details=[{"index": 0, "description": "填写密码"}],
        fallback_params={},
    )
    assert recommendation.source == "ai_inferred"
    assert "password" not in recommendation.params
    assert "password" not in recommendation.input_schema["properties"]
    assert any("sensitive" in warning.lower() for warning in recommendation.warnings)


@pytest.mark.anyio
async def test_semantic_inferer_falls_back_on_invalid_json():
    client = FakeModelClient("not json")
    recommendation = await RpaMcpSemanticInferer(model_client=client).infer(
        requested_name="Search Reports",
        requested_description="Search reports by keyword",
        steps=[],
        removed_step_details=[],
        fallback_params={"keyword": {"original_value": "cancer", "type": "string", "description": "Search keyword"}},
    )
    assert recommendation.source == "rule_inferred"
    assert recommendation.tool_name == "search_reports"
    assert recommendation.input_schema["properties"]["keyword"]["default"] == "cancer"
    assert recommendation.warnings
