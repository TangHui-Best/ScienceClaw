import asyncio

from backend.deepagent.full_sandbox_backend import FullSandboxBackend
from backend.deepagent.skill_command import infer_skill_name, parse_skill_command


def test_parse_skill_command_preserves_unquoted_windows_cd_path():
    parsed = parse_skill_command(r"cd C:\Users\xxxx && python skill.py --foo=bar")

    assert parsed is not None
    assert parsed.cwd == r"C:\Users\xxxx"
    assert parsed.script == "skill.py"
    assert parsed.kwargs == {"foo": "bar"}
    assert infer_skill_name(parsed) == "xxxx"


def test_parse_skill_command_preserves_quoted_windows_cd_path():
    parsed = parse_skill_command(r'cd "C:\Users\xxxx" && python skill.py --foo=bar')

    assert parsed is not None
    assert parsed.cwd == r"C:\Users\xxxx"
    assert parsed.script == "skill.py"
    assert parsed.kwargs == {"foo": "bar"}
    assert infer_skill_name(parsed) == "xxxx"


def test_infer_skill_name_from_relative_posix_skill_command():
    parsed = parse_skill_command('cd "/workspace/session-1/.skills/demo-skill" && python skill.py')

    assert parsed is not None
    assert parsed.cwd == "/workspace/session-1/.skills/demo-skill"
    assert parsed.script == "skill.py"
    assert infer_skill_name(parsed) == "demo-skill"


def test_full_sandbox_injects_credentials_for_relative_skill_command(monkeypatch):
    backend = FullSandboxBackend(
        session_id="session-1",
        user_id="user-1",
        sandbox_url="http://example.com",
        base_dir="/tmp",
        sandbox_base_dir="/workspace",
    )
    repo_queries = []

    class FakeRepo:
        async def find_one(self, query):
            repo_queries.append(query)
            return {"params": [{"name": "password"}]}

    async def fake_inject_credentials(user_id, params, kwargs):
        assert user_id == "user-1"
        assert params == [{"name": "password"}]
        assert kwargs == {}
        return {"password": "s3cret"}

    monkeypatch.setattr("backend.storage.get_repository", lambda _: FakeRepo())
    monkeypatch.setattr("backend.credential.vault.inject_credentials", fake_inject_credentials)

    command = asyncio.run(
        backend._maybe_inject_credentials(
            'cd "/workspace/session-1/.skills/demo-skill" && python skill.py'
        )
    )

    assert repo_queries == [{"name": "demo-skill", "user_id": "user-1"}]
    assert command.startswith('cd "/workspace/session-1/.skills/demo-skill" && python skill.py ')
    assert "--_downloads_dir=/workspace/session-1/downloads" in command
    assert "--password=s3cret" in command
