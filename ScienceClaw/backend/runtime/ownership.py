from __future__ import annotations


def _load_chat_session_lookup():
    from backend.deepagent.sessions import ScienceSessionNotFoundError, async_get_science_session

    return async_get_science_session, ScienceSessionNotFoundError


def _load_rpa_manager():
    from backend.rpa.manager import rpa_manager

    return rpa_manager


async def user_owns_runtime_session(session_id: str, user_id: str) -> bool:
    async_get_science_session, session_not_found_error = _load_chat_session_lookup()

    try:
        session = await async_get_science_session(session_id)
        return str(session.user_id) == str(user_id)
    except session_not_found_error:
        return _load_rpa_manager().owns_sandbox_session(str(user_id), session_id)
