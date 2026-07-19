from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any
from urllib import error, request
from urllib.parse import parse_qsl, urlencode, urlsplit


class EvalAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvalAppUserSession:
    username: str
    token: str
    user: dict[str, Any] | None = None


@dataclass(frozen=True)
class AcceptanceReset:
    profile: str


@dataclass(frozen=True)
class AcceptanceTaskHandle:
    task_id: str
    profile: str
    order_no: str
    relative_url: str = dataclass_field(repr=False)
    task_token: str = dataclass_field(repr=False)


@dataclass(frozen=True)
class AcceptanceOracleSummary:
    passed: bool
    task_id: str
    profile: str
    record_count: int
    mismatches: tuple[str, ...]
    target_order_no: str | None = None
    selected_order_no: str | None = None
    actual: dict[str, Any] | None = None


class EvalAppClient:
    def __init__(self, base_url: str, *, timeout_s: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def reset(self, reset_token: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/eval/reset",
            headers={"X-RPA-Eval-Reset-Token": reset_token},
        )

    def login(self, username: str, password: str) -> EvalAppUserSession:
        payload = {"username": username, "password": password}
        token_response = self._request("POST", "/api/auth/login", json_body=payload)
        token = token_response["access_token"]
        user = self._request("GET", "/api/auth/me", token=token)
        return EvalAppUserSession(username=username, token=token, user=user)

    def issue_eval_token(self, username: str, reset_token: str) -> EvalAppUserSession:
        response = self._request(
            "POST",
            "/api/eval/auth-token",
            json_body={"username": username},
            headers={"X-RPA-Eval-Reset-Token": reset_token},
        )
        return EvalAppUserSession(username=username, token=response["access_token"], user=response.get("user"))

    def reset_acceptance_profile(self, profile: str, reset_token: str) -> AcceptanceReset:
        normalized = profile.upper()
        response = self._request(
            "POST",
            f"/api/e2e/reset/{normalized}",
            headers={"X-RPA-Eval-Reset-Token": reset_token},
        )
        return AcceptanceReset(profile=str(response["profile"]))

    def list_acceptance_orders(self, **filters: str | None) -> tuple[dict[str, Any], ...]:
        query = urlencode({name: value for name, value in filters.items() if value is not None})
        suffix = f"?{query}" if query else ""
        response = self._request("GET", f"/api/e2e/system-a/orders{suffix}")
        return tuple(dict(item) for item in response)

    def start_acceptance_task(self, order_no: str) -> AcceptanceTaskHandle:
        response = self._request(
            "POST",
            "/api/e2e/acceptance-tasks",
            json_body={"order_no": order_no},
        )
        return AcceptanceTaskHandle(
            task_id=str(response["task_id"]),
            profile=str(response["profile"]),
            order_no=str(response["order_no"]),
            relative_url=str(response["url"]),
            task_token=str(response["token"]),
        )

    def get_acceptance_task(self, task_id: str, task_token: str) -> dict[str, Any]:
        query = urlencode({"token": task_token})
        return self._request("GET", f"/api/e2e/acceptance-tasks/{task_id}?{query}")

    def submit_acceptance_record(
        self,
        task_id: str,
        task_token: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        query = urlencode({"token": task_token})
        return self._request(
            "POST",
            f"/api/e2e/acceptance-tasks/{task_id}/records?{query}",
            json_body=record,
        )

    def acceptance_oracle(self, task_id: str, oracle_token: str) -> AcceptanceOracleSummary:
        response = self._request(
            "GET",
            f"/api/e2e/oracle/{task_id}",
            headers={"X-RPA-Eval-Oracle-Token": oracle_token},
        )
        return AcceptanceOracleSummary(
            passed=bool(response["passed"]),
            task_id=str(response["task_id"]),
            profile=str(response["profile"]),
            record_count=int(response["record_count"]),
            mismatches=tuple(str(item) for item in response.get("mismatches", ())),
            target_order_no=response.get("target_order_no"),
            selected_order_no=response.get("selected_order_no"),
            actual=response.get("actual"),
        )

    def get_json(self, path: str, token: str) -> Any:
        return self._request("GET", path, token=token)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        token: str | None = None,
    ) -> Any:
        body = None
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"

        sensitive_values = [
            value
            for key, value in parse_qsl(urlsplit(path).query, keep_blank_values=True)
            if "token" in key.casefold()
        ]
        sensitive_values.extend(
            value
            for key, value in request_headers.items()
            if "token" in key.casefold() or key.casefold() == "authorization"
        )
        if token:
            sensitive_values.append(token)
        safe_path = re.sub(
            r"(?i)([?&](?:token|[^=&]*_token)=)[^&]*",
            r"\1<redacted>",
            path,
        )
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )
        failure_message: str | None = None
        raw = ""
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            safe_detail = _redact_failure_text(detail, sensitive_values)
            failure_message = (
                f"{method} {safe_path} failed with HTTP {exc.code}: {safe_detail}"
            )
        except error.URLError as exc:
            safe_reason = _redact_failure_text(str(exc.reason), sensitive_values)
            failure_message = f"{method} {safe_path} failed: {safe_reason}"
        except TimeoutError:
            failure_message = f"{method} {safe_path} timed out after {self.timeout_s}s"

        if failure_message is not None:
            raise EvalAppError(failure_message)

        if not raw:
            return {}
        json_failure = False
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            json_failure = True
        if json_failure:
            raise EvalAppError(f"{method} {safe_path} returned non-JSON response")


def _redact_failure_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    redacted = re.sub(r"https?://[^\s'\"}]+", "<url-redacted>", redacted)
    redacted = re.sub(
        r'(?i)(["\'](?:token|[^"\']*_token)["\']\s*:\s*["\'])[^"\']*',
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([?&](?:token|[^=&]*_token)=)[^&\s'\"]*",
        r"\1<redacted>",
        redacted,
    )
    return redacted[:240]
