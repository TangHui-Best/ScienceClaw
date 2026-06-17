from __future__ import annotations

import importlib.util
import json
import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

START_MARKER = ">>>TOOL_RESULT_JSON>>>"
END_MARKER = "<<<TOOL_RESULT_JSON<<<"
DEFAULT_TOOL_RUNNER_PATH = "/app/_tool_runner.py"
DEFAULT_EXECUTE_TIMEOUT = 120
PACKAGE_ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class MarkerWrappedOutput:
    pre_output: str
    result: Any
    post_output: str


def parse_marker_wrapped_output(raw_output: str) -> MarkerWrappedOutput:
    start = raw_output.find(START_MARKER)
    end = raw_output.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError("Tool output missing result markers")

    pre_output = raw_output[:start].strip()
    payload = raw_output[start + len(START_MARKER):end].strip()
    post_output = raw_output[end + len(END_MARKER):].strip()

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in tool result: {exc}") from exc

    return MarkerWrappedOutput(pre_output=pre_output, result=parsed, post_output=post_output)


def _emit(payload: dict[str, Any]) -> None:
    print(START_MARKER)
    print(json.dumps(payload, ensure_ascii=False, default=str))
    print(END_MARKER)


def _load_tool_function(tool_file: str, function_name: str):
    spec = importlib.util.spec_from_file_location("_tool_mod", tool_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec from {tool_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool_obj = getattr(module, function_name, None)
    if tool_obj is None:
        raise AttributeError(f"Function '{function_name}' not found in {tool_file}")
    return tool_obj


def _run_tool(tool_file: str, function_name: str, arguments: dict[str, Any]) -> Any:
    tool_dir = str(Path(tool_file).resolve().parent)
    added_to_path = False
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
        added_to_path = True
    try:
        tool_obj = _load_tool_function(tool_file, function_name)
        return tool_obj.invoke(arguments)
    finally:
        if added_to_path:
            sys.path.remove(tool_dir)


def _format_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _combine_output(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def _prepend_pythonpath(path_entry: str, existing_pythonpath: str | None) -> str:
    parts = [segment for segment in (existing_pythonpath or "").split(os.pathsep) if segment]
    if path_entry not in parts:
        parts.insert(0, path_entry)
    return os.pathsep.join(parts)


class LocalToolExecutor:
    def __init__(
        self,
        *,
        python_executable: str | None = None,
        runner_module: str = "backend.deepagent.tool_execution",
        execute_timeout: int = DEFAULT_EXECUTE_TIMEOUT,
        env: dict[str, str] | None = None,
    ) -> None:
        self._python_executable = python_executable or sys.executable
        self._runner_module = runner_module
        self._execute_timeout = execute_timeout
        self._env = env

    def execute(self, *, tool_path: str, function_name: str, arguments: dict[str, Any]) -> Any:
        args_json = json.dumps(arguments, ensure_ascii=False, default=str)
        command = [
            self._python_executable,
            "-m",
            self._runner_module,
            tool_path,
            function_name,
            args_json,
        ]
        rendered_command = _format_command(command)

        env = os.environ.copy()
        if self._env:
            env.update(self._env)
        env["PYTHONPATH"] = _prepend_pythonpath(str(PACKAGE_ROOT), env.get("PYTHONPATH"))

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._execute_timeout,
                env=env,
                cwd=str(PACKAGE_ROOT),
            )
        except Exception as exc:
            logger.error("[Tools] Local tool execution failed for %s: %s", function_name, exc)
            return {
                "_sandbox_exec": {"command": rendered_command, "output": str(exc)},
                "result": {"error": f"Local execution failed: {exc}"},
            }

        try:
            parsed = parse_marker_wrapped_output(completed.stdout)
        except ValueError:
            output = _combine_output(completed.stdout.strip()[-2000:], completed.stderr.strip()[-2000:])
            logger.error("[Tools] Result markers missing for local tool %s", function_name)
            return {
                "_sandbox_exec": {"command": rendered_command, "output": output},
                "result": {"error": "Tool output parsing failed"},
            }

        output = _combine_output(parsed.pre_output, completed.stderr.strip())
        return {
            "_sandbox_exec": {"command": rendered_command, "output": output},
            "result": parsed.result,
        }


class SandboxToolExecutor:
    def __init__(
        self,
        *,
        sandbox_base_url: str | None = None,
        sandbox_tools_dir: str | None = None,
        tool_runner_path: str = DEFAULT_TOOL_RUNNER_PATH,
        execute_timeout: int = DEFAULT_EXECUTE_TIMEOUT,
        command_runner: Callable[[str, int], str] | None = None,
    ) -> None:
        self._sandbox_base_url = (sandbox_base_url or settings.sandbox_base_url).rstrip("/")
        self._sandbox_tools_dir = (sandbox_tools_dir or settings.sandbox_tools_dir).rstrip("/")
        self._tool_runner_path = tool_runner_path
        self._execute_timeout = execute_timeout
        self._command_runner = command_runner
        self._sandbox_session_id: str | None = None

    def _ensure_sandbox_session(self) -> str:
        if self._sandbox_session_id:
            return self._sandbox_session_id

        response = httpx.post(
            f"{self._sandbox_base_url}/v1/shell/sessions/create",
            json={"exec_dir": "/"},
            timeout=10,
        )
        response.raise_for_status()
        self._sandbox_session_id = response.json()["data"]["session_id"]
        logger.info("[Tools] Sandbox tool-exec session: %s", self._sandbox_session_id)
        return self._sandbox_session_id

    def _execute_in_sandbox(self, command: str, timeout: int) -> str:
        def _do_exec(session_id: str) -> str:
            response = httpx.post(
                f"{self._sandbox_base_url}/v1/shell/exec",
                json={"id": session_id, "command": command, "async_mode": False},
                timeout=timeout + 5,
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("output", "")

        try:
            return _do_exec(self._ensure_sandbox_session())
        except Exception as exc:
            logger.warning("[Tools] Sandbox exec failed (%s), retrying with new session", exc)
            self._sandbox_session_id = None
            return _do_exec(self._ensure_sandbox_session())

    def execute(self, *, tool_path: str, function_name: str, arguments: dict[str, Any]) -> Any:
        tool_basename = Path(tool_path).name
        sandbox_tool_path = f"{self._sandbox_tools_dir}/{tool_basename}"
        args_json = json.dumps(arguments, ensure_ascii=False, default=str)
        command = (
            f"python3 {shlex.quote(self._tool_runner_path)} "
            f"{shlex.quote(sandbox_tool_path)} "
            f"{shlex.quote(function_name)} "
            f"{shlex.quote(args_json)}"
        )
        logger.info("[Tools] Proxy -> sandbox: %s", function_name)

        try:
            if self._command_runner is not None:
                raw_output = self._command_runner(command, self._execute_timeout)
            else:
                raw_output = self._execute_in_sandbox(command, self._execute_timeout)
        except Exception as exc:
            logger.error("[Tools] Sandbox call failed for %s: %s", function_name, exc)
            return {
                "_sandbox_exec": {"command": command, "output": str(exc)},
                "result": {"error": f"Sandbox execution failed: {exc}"},
            }

        try:
            parsed = parse_marker_wrapped_output(raw_output)
        except ValueError:
            logger.error("[Tools] Result markers missing for %s", function_name)
            return {
                "_sandbox_exec": {"command": command, "output": raw_output[-2000:]},
                "result": {"error": "Tool output parsing failed"},
            }

        return {
            "_sandbox_exec": {"command": command, "output": parsed.pre_output},
            "result": parsed.result,
        }


def main() -> None:
    if len(sys.argv) < 3:
        _emit({"error": f"Usage: {sys.argv[0]} <tool_file> <func_name> [json_args]"})
        sys.exit(1)

    tool_file = sys.argv[1]
    function_name = sys.argv[2]
    args_json = sys.argv[3] if len(sys.argv) > 3 else "{}"

    try:
        arguments = json.loads(args_json)
    except json.JSONDecodeError as exc:
        _emit({"error": f"Invalid JSON args: {exc}"})
        sys.exit(1)

    try:
        result = _run_tool(tool_file, function_name, arguments)
    except Exception as exc:
        _emit({"error": f"Tool execution failed: {type(exc).__name__}: {exc}"})
        sys.exit(1)

    _emit(result)


if __name__ == "__main__":
    main()
