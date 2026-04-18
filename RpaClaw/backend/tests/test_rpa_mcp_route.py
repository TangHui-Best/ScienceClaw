from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.route import rpa_mcp as rpa_mcp_route


class _User:
    id = "user-1"


class _MemoryRepo:
    def __init__(self, docs=None):
        self.docs = {str(doc["_id"]): dict(doc) for doc in (docs or [])}

    async def find_one(self, filter_doc, projection=None):
        for doc in self.docs.values():
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                return dict(doc)
        return None

    async def find_many(self, filter_doc, projection=None, sort=None, skip=0, limit=0):
        return [dict(doc) for doc in self.docs.values() if all(doc.get(key) == value for key, value in filter_doc.items())]

    async def update_one(self, filter_doc, update_doc, upsert=False):
        existing = await self.find_one(filter_doc)
        payload = dict(existing or filter_doc)
        payload.update(update_doc.get("$set", {}))
        payload.setdefault("_id", filter_doc.get("_id"))
        self.docs[str(payload["_id"])] = payload
        return 1

    async def delete_one(self, filter_doc):
        for doc_id, doc in list(self.docs.items()):
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                del self.docs[doc_id]
                return 1
        return 0


def _build_rpa_mcp_app():
    app = FastAPI()
    app.include_router(rpa_mcp_route.router, prefix="/api/v1")
    app.dependency_overrides[rpa_mcp_route.require_user] = lambda: _User()
    return app


def _fake_steps(session_id: str, user_id: str):
    assert session_id == "session-1"
    assert user_id == "user-1"
    return {
        "steps": [{"action": "click", "description": "Export invoice", "url": "https://example.com/dashboard"}],
        "params": {},
        "skill_name": "invoice_skill",
    }


class _FakeConverter:
    def preview(self, **kwargs):
        return SimpleNamespace(model_dump=lambda mode='python': {
            "id": "preview",
            "name": kwargs["name"],
            "tool_name": "rpa_download_invoice",
            "description": kwargs["description"],
            "allowed_domains": ["example.com"],
            "post_auth_start_url": "https://example.com/dashboard",
            "steps": kwargs["steps"],
            "params": kwargs["params"],
            "input_schema": {"type": "object", "properties": {"cookies": {"type": "array"}}, "required": ["cookies"]},
            "sanitize_report": {"removed_steps": [0, 1, 2], "removed_params": ["email", "password"], "warnings": []},
            "source": {"type": "rpa_skill", "session_id": kwargs["session_id"], "skill_name": kwargs["skill_name"]},
            "enabled": True,
        })


def _fake_gateway_tools(user_id: str):
    assert user_id == "user-1"
    return [
        {
            "name": "rpa_download_invoice",
            "description": "Download invoice",
            "input_schema": {"type": "object", "properties": {"cookies": {"type": "array"}}, "required": ["cookies"]},
        }
    ]


def test_preview_route_returns_sanitize_report(monkeypatch):
    app = _build_rpa_mcp_app()
    client = TestClient(app)

    monkeypatch.setattr(rpa_mcp_route, "get_rpa_session_steps", _fake_steps)
    monkeypatch.setattr(rpa_mcp_route, "RpaMcpConverter", lambda: _FakeConverter())

    response = client.post(
        "/api/v1/rpa-mcp/session/session-1/preview",
        json={"name": "download_invoice", "description": "Download invoice"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["sanitize_report"]["removed_steps"] == [0, 1, 2]


def test_gateway_discover_tools_returns_enabled_user_tools(monkeypatch):
    app = _build_rpa_mcp_app()
    client = TestClient(app)
    monkeypatch.setattr(rpa_mcp_route, "_build_gateway_tools", _fake_gateway_tools)

    response = client.post("/api/v1/rpa-mcp/mcp", json={"method": "tools/list", "params": {}})

    assert response.status_code == 200
    assert response.json()["result"]["tools"][0]["name"] == "rpa_download_invoice"
