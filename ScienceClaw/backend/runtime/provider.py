from __future__ import annotations

from typing import Protocol


class RuntimeProvider(Protocol):
    async def create_runtime(self, session_id: str, user_id: str):
        ...

    async def delete_runtime(self, runtime_record) -> None:
        ...

    async def refresh_runtime(self, runtime_record):
        ...


def build_runtime_provider(settings) -> RuntimeProvider:
    runtime_mode = getattr(settings, "runtime_mode", "shared")
    if runtime_mode == "docker":
        from backend.runtime.docker_runtime_provider import DockerRuntimeProvider

        return DockerRuntimeProvider(settings)
    if runtime_mode == "session_pod":
        from backend.runtime.k8s_runtime_provider import K8sRuntimeProvider

        return K8sRuntimeProvider(settings)

    from backend.runtime.shared_runtime_provider import SharedRuntimeProvider

    return SharedRuntimeProvider(settings)
