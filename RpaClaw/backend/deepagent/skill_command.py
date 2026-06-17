from __future__ import annotations

import ntpath
import posixpath
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedSkillCommand:
    cwd: str | None
    python_bin: str
    script: str
    kwargs: dict[str, str]


def parse_skill_command(command: str) -> ParsedSkillCommand | None:
    candidates: list[tuple[bool, ParsedSkillCommand]] = []
    for posix in (True, False):
        try:
            tokens = shlex.split(command, posix=posix)
        except ValueError:
            continue

        parsed = _parse_skill_tokens(tokens)
        if parsed is not None:
            candidates.append((posix, parsed))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]

    if "\\" in command:
        for _, parsed in candidates:
            if "\\" in (parsed.cwd or "") or "\\" in parsed.script:
                return parsed

    for posix, parsed in candidates:
        if posix:
            return parsed
    return candidates[0][1]


def infer_skill_name(parsed: ParsedSkillCommand) -> str:
    resolved = combine_shell_path(parsed.cwd, parsed.script)
    normalized = _normalize_path(resolved)
    if _basename_any(normalized).lower() == "skill.py":
        parent = posixpath.dirname(normalized)
        if parent:
            name = posixpath.basename(parent.rstrip("/"))
            if name and name not in {".", ".."}:
                return name

    if parsed.cwd:
        cwd_name = posixpath.basename(_normalize_path(parsed.cwd).rstrip("/"))
        if cwd_name and cwd_name not in {".", ".."}:
            return cwd_name

    return ""


def resolve_local_skill_script(
    parsed: ParsedSkillCommand, default_cwd: str | Path
) -> Path:
    base_dir = Path(parsed.cwd).expanduser() if parsed.cwd else Path(default_cwd)
    script_path = Path(parsed.script).expanduser()
    if not is_absolute_shell_path(parsed.script):
        script_path = base_dir / parsed.script
    return script_path.resolve()


def combine_shell_path(cwd: str | None, path: str) -> str:
    if not cwd or is_absolute_shell_path(path):
        return path

    separator = "\\" if "\\" in cwd and "/" not in cwd else "/"
    return cwd.rstrip("\\/") + separator + path.lstrip("\\/")


def is_absolute_shell_path(path: str) -> bool:
    stripped = _strip_matching_quotes(path)
    return bool(
        ntpath.isabs(stripped)
        or posixpath.isabs(stripped)
        or re.match(r"^[A-Za-z]:[\\/]", stripped)
    )


def _parse_skill_tokens(tokens: list[str]) -> ParsedSkillCommand | None:
    normalized = [_strip_matching_quotes(token) for token in tokens]

    cwd: str | None = None
    run_tokens = normalized
    if "&&" in normalized:
        and_idx = normalized.index("&&")
        prefix = normalized[:and_idx]
        run_tokens = normalized[and_idx + 1 :]
        if prefix and prefix[0].lower() == "cd" and len(prefix) >= 2:
            cwd = " ".join(prefix[1:])

    if len(run_tokens) < 2:
        return None

    python_bin = run_tokens[0]
    if _basename_any(python_bin).lower() not in {"python", "python3", "python.exe", "python3.exe"}:
        return None

    script = run_tokens[1]
    if _basename_any(script).lower() != "skill.py":
        return None

    kwargs: dict[str, str] = {}
    for arg in run_tokens[2:]:
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            kwargs[key] = value

    return ParsedSkillCommand(cwd=cwd, python_bin=python_bin, script=script, kwargs=kwargs)


def _basename_any(path: str) -> str:
    normalized = _normalize_path(path).rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _normalize_path(path: str) -> str:
    return _strip_matching_quotes(path).replace("\\", "/")


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
