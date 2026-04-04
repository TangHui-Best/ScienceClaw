from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import httpx

from backend.runtime.models import SessionRuntimeRecord

logger = logging.getLogger(__name__)


class DockerRuntimeProvider:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    def _get_client(self):
        if self.client is None:
            import docker

            self.client = docker.from_env()
        return self.client

    def _resolve_volumes_from(self, client) -> list[str]:
        configured = (getattr(self.settings, "docker_runtime_volumes_from", "") or "").strip()
        if configured:
            return [configured]

        containers = client.containers.list(
            filters={"label": "com.docker.compose.service=sandbox"}
        )
        if not containers:
            return []

        source_name = getattr(containers[0], "name", "")
        if not source_name:
            return []

        logger.info(f"Using sandbox container '{source_name}' as volumes_from source")
        return [source_name]

    @staticmethod
    def _parse_key_value_map(raw: str) -> dict[str, str]:
        items: dict[str, str] = {}
        for part in raw.split(","):
            item = part.strip()
            if not item or ":" not in item:
                continue
            key, value = item.split(":", 1)
            items[key.strip()] = value.strip()
        return items

    @staticmethod
    def _parse_list(raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    async def _wait_until_ready(self, rest_base_url: str) -> None:
        timeout_seconds = int(getattr(self.settings, "runtime_wait_timeout_seconds", 0) or 0)
        if timeout_seconds <= 0:
            return

        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=5) as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(f"{rest_base_url}/v1/docs")
                    resp.raise_for_status()
                    return
                except Exception as exc:
                    last_error = exc
                    await asyncio.sleep(1)

        raise RuntimeError(
            f"Timed out waiting for runtime to become ready at {rest_base_url}: {last_error}"
        )

    @staticmethod
    def _container_name(session_id: str) -> str:
        sanitized = "".join(ch if ch.isalnum() else "-" for ch in session_id.lower())
        sanitized = sanitized.strip("-") or "session"
        prefix = sanitized[:16].rstrip("-") or "session"
        digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:8]
        return f"scienceclaw-sess-{prefix}-{digest}".rstrip("-")

    async def create_runtime(self, session_id: str, user_id: str):
        client = self._get_client()
        container_name = self._container_name(session_id)
        run_kwargs = {
            "detach": True,
            "name": container_name,
            "network": self.settings.docker_runtime_network,
            "shm_size": getattr(self.settings, "docker_runtime_shm_size", "2gb"),
            "mem_limit": getattr(self.settings, "docker_runtime_mem_limit", ""),
            "labels": {
                "scienceclaw.runtime": "session",
                "scienceclaw.session_id": session_id,
                "scienceclaw.user_id": user_id,
            },
        }
        security_opt = self._parse_list(
            getattr(self.settings, "docker_runtime_security_opt", "")
        )
        if security_opt:
            run_kwargs["security_opt"] = security_opt
        extra_hosts = self._parse_key_value_map(
            getattr(self.settings, "docker_runtime_extra_hosts", "")
        )
        if extra_hosts:
            run_kwargs["extra_hosts"] = extra_hosts
        volumes_from = await asyncio.to_thread(self._resolve_volumes_from, client)
        if volumes_from:
            run_kwargs["volumes_from"] = volumes_from

        await asyncio.to_thread(
            client.containers.run,
            self.settings.runtime_image,
            **run_kwargs,
        )

        now = int(time.time())
        record = SessionRuntimeRecord(
            session_id=session_id,
            user_id=user_id,
            namespace=getattr(self.settings, "k8s_namespace", "local"),
            pod_name=container_name,
            service_name=container_name,
            rest_base_url=f"http://{container_name}:{self.settings.runtime_service_port}",
            status="ready",
            created_at=now,
            last_used_at=now,
        )
        await self._wait_until_ready(record.rest_base_url)
        return record

    async def delete_runtime(self, runtime_record) -> None:
        client = self._get_client()
        try:
            container = await asyncio.to_thread(
                client.containers.get, runtime_record.service_name
            )
        except Exception as exc:
            if "No such container" in str(exc):
                logger.info(
                    "Runtime container already removed for session %s: %s",
                    runtime_record.session_id,
                    runtime_record.service_name,
                )
                return
            raise
        await asyncio.to_thread(container.remove, force=True)

    async def refresh_runtime(self, runtime_record):
        client = self._get_client()
        try:
            container = await asyncio.to_thread(
                client.containers.get, runtime_record.service_name
            )
        except Exception as exc:
            if "No such container" in str(exc):
                runtime_record.status = "missing"
                return runtime_record
            raise

        state = getattr(container, "attrs", {}).get("State", {}) or {}
        health = state.get("Health", {}) or {}
        health_status = str(health.get("Status") or "").lower()
        container_status = str(state.get("Status") or "").lower()

        if health_status == "healthy":
            runtime_record.status = "ready"
        elif health_status == "unhealthy":
            runtime_record.status = "unhealthy"
        elif container_status in {"running", "created", "restarting"}:
            runtime_record.status = container_status
        elif container_status:
            runtime_record.status = container_status
        else:
            runtime_record.status = "unknown"
        return runtime_record
