import pytest

from backend.rpa.api_monitor.intent_pruner import (
    IntentPruneCandidate,
    _parse_prune_response,
    _fallback_result,
)


def _candidate(key: str) -> IntentPruneCandidate:
    return IntentPruneCandidate(
        candidate_key=key,
        method=key.split(" ", 1)[0],
        url_pattern=key.split(" ", 1)[1],
        confidence_score=100,
        confidence_reasons=["由用户动作触发"],
        request_summary="(无请求体)",
        response_summary='{"items":[]}',
        step_summary="点击 查询",
        page_url="https://example.com/orders",
        title="Orders",
    )


def test_parse_prune_response_normalizes_items():
    candidates = [_candidate("POST /api/orders/search"), _candidate("GET /api/menu/tree")]
    raw = """
    ```json
    {
      "items": [
        {
          "candidate_key": "POST /api/orders/search",
          "group": "primary",
          "score": 110,
          "rank": 1,
          "reason": "订单查询主接口。"
        },
        {
          "candidate_key": "GET /api/menu/tree",
          "group": "bootstrap",
          "score": -5,
          "rank": null,
          "reason": "菜单初始化接口。"
        }
      ]
    }
    ```
    """

    result = _parse_prune_response(raw, candidates, batch_id="batch_1")

    assert result.batch_id == "batch_1"
    assert [(item.candidate_key, item.intent_group, item.intent_score) for item in result.items] == [
        ("POST /api/orders/search", "primary", 100),
        ("GET /api/menu/tree", "bootstrap", 0),
    ]
    assert result.items[0].intent_rank == 1
    assert result.items[1].intent_rank is None


def test_parse_prune_response_fills_missing_and_invalid_as_uncertain():
    candidates = [_candidate("POST /api/orders/search"), _candidate("GET /api/user/profile")]
    raw = '{"items":[{"candidate_key":"POST /api/orders/search","group":"other","score":80,"reason":"bad group"}]}'

    result = _parse_prune_response(raw, candidates, batch_id="batch_2")

    assert [(item.candidate_key, item.intent_group) for item in result.items] == [
        ("POST /api/orders/search", "uncertain"),
        ("GET /api/user/profile", "uncertain"),
    ]
    assert all(item.intent_reason for item in result.items)


def test_fallback_result_marks_all_uncertain():
    candidates = [_candidate("GET /api/user/profile"), _candidate("GET /api/menu/tree")]

    result = _fallback_result(candidates, batch_id="batch_3", reason="意图裁剪失败，需人工确认")

    assert [item.intent_group for item in result.items] == ["uncertain", "uncertain"]
    assert [item.intent_reason for item in result.items] == ["意图裁剪失败，需人工确认", "意图裁剪失败，需人工确认"]
