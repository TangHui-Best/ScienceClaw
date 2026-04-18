from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.rpa.generator import PlaywrightGenerator
from backend.rpa.mcp_models import RpaMcpSanitizeReport, RpaMcpSource, RpaMcpToolDefinition


_LOGIN_BUTTON_RE = re.compile(r"\b(login|log in|sign in|登录)\b", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"password|密码", re.IGNORECASE)
_EMAIL_RE = re.compile(r"email|e-mail|username|user name|account|账号", re.IGNORECASE)


class RpaMcpConverter:
    def __init__(self) -> None:
        self._generator = PlaywrightGenerator()

    def preview(self, *, user_id: str, session_id: str, skill_name: str, name: str, description: str, steps: list[dict], params: dict) -> RpaMcpToolDefinition:
        normalized = self._generator._normalize_step_signals(
            self._generator._infer_missing_tab_transitions(
                self._generator._deduplicate_steps(steps)
            )
        )
        login_range = self._detect_login_range(normalized)
        sanitized_steps, report = self._strip_login_steps(normalized, login_range)
        sanitized_params = self._strip_login_params(params, report)
        allowed_domains = self._collect_domains(normalized)
        post_auth_start_url = self._pick_post_auth_start_url(normalized, sanitized_steps)
        input_schema = self._build_input_schema(sanitized_params)
        return RpaMcpToolDefinition(
            id="preview",
            user_id=user_id,
            name=name,
            tool_name=self._tool_name(name),
            description=description,
            source=RpaMcpSource(session_id=session_id, skill_name=skill_name),
            allowed_domains=allowed_domains,
            post_auth_start_url=post_auth_start_url,
            steps=sanitized_steps,
            params=sanitized_params,
            input_schema=input_schema,
            sanitize_report=report,
        )

    def _detect_login_range(self, steps: list[dict]) -> tuple[int, int] | None:
        start = None
        end = None
        for index, step in enumerate(steps):
            text = " ".join(
                str(step.get(key) or "") for key in ("description", "value", "target", "url")
            )
            is_password = bool(step.get("sensitive")) or "{{credential}}" in text or _PASSWORD_RE.search(text)
            is_login_button = step.get("action") == "click" and _LOGIN_BUTTON_RE.search(text)
            is_login_page = "login" in str(step.get("url") or "").lower() or "signin" in str(step.get("url") or "").lower()
            is_email_field = step.get("action") == "fill" and _EMAIL_RE.search(text)
            if start is None and (is_password or is_login_page or is_email_field):
                start = index
            if start is not None and is_login_button:
                end = index
                break
        if start is None or end is None:
            return None
        return start, end

    def _strip_login_steps(self, steps: list[dict], login_range: tuple[int, int] | None) -> tuple[list[dict], RpaMcpSanitizeReport]:
        report = RpaMcpSanitizeReport()
        if login_range is None:
            report.warnings.append("Could not determine login step range automatically.")
            return list(steps), report
        start, end = login_range
        report.removed_steps = list(range(start, end + 1))
        return [dict(step) for idx, step in enumerate(steps) if idx < start or idx > end], report

    def _strip_login_params(self, params: dict, report: RpaMcpSanitizeReport) -> dict:
        sanitized = {}
        for key, value in params.items():
            info = dict(value or {})
            original = str(info.get("original_value") or "")
            if info.get("sensitive") or info.get("credential_id") or "{{credential}}" in original:
                report.removed_params.append(key)
                continue
            if _EMAIL_RE.search(key) or _EMAIL_RE.search(original):
                report.removed_params.append(key)
                continue
            sanitized[key] = info
        return sanitized

    def _collect_domains(self, steps: list[dict]) -> list[str]:
        domains = []
        for step in steps:
            host = (urlparse(str(step.get("url") or "")).hostname or "").lower().lstrip(".")
            if host and host not in domains:
                domains.append(host)
        return domains

    def _pick_post_auth_start_url(self, steps: list[dict], sanitized_steps: list[dict]) -> str:
        for step in sanitized_steps:
            url = str(step.get("url") or "").strip()
            if url:
                return url
        for step in steps:
            url = str(step.get("url") or "").strip()
            if url:
                return url
        return ""

    def _build_input_schema(self, params: dict) -> dict:
        properties = {
            "cookies": {
                "type": "array",
                "description": "Playwright-compatible cookies for allowed domains",
            }
        }
        required = ["cookies"]
        for key, info in params.items():
            prop = {
                "type": info.get("type", "string"),
                "description": info.get("description", ""),
            }
            original = info.get("original_value")
            if original and original != "{{credential}}":
                prop["default"] = original
            elif info.get("required"):
                required.append(key)
            properties[key] = prop
        return {"type": "object", "properties": properties, "required": required}

    def _tool_name(self, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", (name or "tool").strip().lower()).strip("_")
        return f"rpa_{slug or 'tool'}"
