from __future__ import annotations

import json
import logging
import os
import shlex
import threading
from pathlib import Path
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.deepagent.external_tools_loader import ExternalToolsLoader

logger = logging.getLogger(__name__)

_SANDBOX_BASE_URL = (
    (os.environ.get("SANDBOX_BASE_URL") or "").strip()
    or "http://sandbox:8080"
)
_TOOL_RUNNER_PATH = "/app/_tool_runner.py"
_TOOLS_DIR_IN_SANDBOX = settings.sandbox_tools_dir
_EXECUTE_TIMEOUT = 120

_START_MARKER = ">>>TOOL_RESULT_JSON>>>"
_END_MARKER = "<<<TOOL_RESULT_JSON<<<"

_session_lock = threading.Lock()
_sandbox_session_id: Optional[str] = None


def _ensure_sandbox_session() -> str:
    global _sandbox_session_id
    if _sandbox_session_id:
        return _sandbox_session_id
    with _session_lock:
        if _sandbox_session_id:
            return _sandbox_session_id
        response = httpx.post(
            f"{_SANDBOX_BASE_URL}/v1/shell/sessions/create",
            json={"exec_dir": "/"},
            timeout=10,
        )
        response.raise_for_status()
        _sandbox_session_id = response.json()["data"]["session_id"]
        logger.info(f"[Tools] Sandbox tool-exec session: {_sandbox_session_id}")
        return _sandbox_session_id


def _execute_in_sandbox(command: str, timeout: int = _EXECUTE_TIMEOUT) -> str:
    global _sandbox_session_id

    def _do_exec(session_id: str) -> str:
        response = httpx.post(
            f"{_SANDBOX_BASE_URL}/v1/shell/exec",
            json={"id": session_id, "command": command, "async_mode": False},
            timeout=timeout + 5,
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("output", "")

    try:
        return _do_exec(_ensure_sandbox_session())
    except Exception as exc:
        logger.warning(f"[Tools] Sandbox exec failed ({exc}), retrying with new session")
        _sandbox_session_id = None
        return _do_exec(_ensure_sandbox_session())


class _SandboxExecutor:
    def execute(self, *, tool_path: str, function_name: str, arguments: dict[str, Any]) -> Any:
        tool_basename = Path(tool_path).name
        sandbox_tool_path = f"{_TOOLS_DIR_IN_SANDBOX}/{tool_basename}"
        args_json = json.dumps(arguments, ensure_ascii=False, default=str)
        command = (
            f"python3 {shlex.quote(_TOOL_RUNNER_PATH)} "
            f"{shlex.quote(sandbox_tool_path)} "
            f"{shlex.quote(function_name)} "
            f"{shlex.quote(args_json)}"
        )
        logger.info(f"[Tools] Proxy -> sandbox: {function_name}")
        try:
            raw_output = _execute_in_sandbox(command)
        except Exception as exc:
            logger.error(f"[Tools] Sandbox call failed for {function_name}: {exc}")
            return {
                "_sandbox_exec": {"command": command, "output": str(exc)},
                "result": {"error": f"Sandbox execution failed: {exc}"},
            }

        start = raw_output.find(_START_MARKER)
        end = raw_output.find(_END_MARKER)
        if start == -1 or end == -1:
            logger.error(f"[Tools] Result markers missing for {function_name}")
            return {
                "_sandbox_exec": {"command": command, "output": raw_output[-2000:]},
                "result": {"error": "Tool output parsing failed"},
            }

        pre_output = raw_output[:start].strip()
        json_str = raw_output[start + len(_START_MARKER):end].strip()
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            parsed = {"error": "Invalid JSON in tool result", "raw": json_str[:500]}

        return {
            "_sandbox_exec": {"command": command, "output": pre_output},
            "result": parsed,
        }


_loader = ExternalToolsLoader(
    tools_dir=Path(settings.tools_dir),
    executor=_SandboxExecutor(),
)


def reload_external_tools(force: bool = False):
    return _loader.reload(force=force)


external_tools = reload_external_tools(force=True)
