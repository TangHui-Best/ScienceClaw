import pytest


@pytest.mark.asyncio
async def test_user_owns_runtime_session_via_chat_session(monkeypatch):
    import backend.runtime.ownership as ownership

    class _Session:
        user_id = "user-1"

    async def _get_session(session_id: str):
        assert session_id == "sess-1"
        return _Session()

    class _NotFound(Exception):
        pass

    class _RpaManager:
        def owns_sandbox_session(self, user_id: str, sandbox_session_id: str) -> bool:
            return False

    monkeypatch.setattr(ownership, "_load_chat_session_lookup", lambda: (_get_session, _NotFound))
    monkeypatch.setattr(ownership, "_load_rpa_manager", lambda: _RpaManager())

    owned = await ownership.user_owns_runtime_session("sess-1", "user-1")

    assert owned is True


@pytest.mark.asyncio
async def test_user_owns_runtime_session_falls_back_to_rpa_sessions(monkeypatch):
    import backend.runtime.ownership as ownership

    async def _get_session(session_id: str):
        raise _NotFound()

    class _NotFound(Exception):
        pass

    class _RpaManager:
        def owns_sandbox_session(self, user_id: str, sandbox_session_id: str) -> bool:
            return user_id == "user-1" and sandbox_session_id == "rpa-1"

    monkeypatch.setattr(ownership, "_load_chat_session_lookup", lambda: (_get_session, _NotFound))
    monkeypatch.setattr(ownership, "_load_rpa_manager", lambda: _RpaManager())

    owned = await ownership.user_owns_runtime_session("rpa-1", "user-1")

    assert owned is True


@pytest.mark.asyncio
async def test_user_owns_runtime_session_rejects_wrong_user(monkeypatch):
    import backend.runtime.ownership as ownership

    class _Session:
        user_id = "user-2"

    async def _get_session(session_id: str):
        return _Session()

    class _NotFound(Exception):
        pass

    class _RpaManager:
        def owns_sandbox_session(self, user_id: str, sandbox_session_id: str) -> bool:
            return False

    monkeypatch.setattr(ownership, "_load_chat_session_lookup", lambda: (_get_session, _NotFound))
    monkeypatch.setattr(ownership, "_load_rpa_manager", lambda: _RpaManager())

    owned = await ownership.user_owns_runtime_session("sess-2", "user-1")

    assert owned is False
