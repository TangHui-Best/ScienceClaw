from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from backend.runtime.models import SessionRuntimeRecord

logger = logging.getLogger(__name__)


class K8sRuntimeProvider:
    def __init__(self, settings, core_v1_api=None, api_exception_cls=None, config_loader=None):
        self.settings = settings
        self.core_v1_api = core_v1_api
        self.api_exception_cls = api_exception_cls
        self.config_loader = config_loader

    def _load_clients(self):
        if self.core_v1_api is not None:
            return self.core_v1_api

        if self.config_loader is None or self.api_exception_cls is None:
            from kubernetes import client, config
            from kubernetes.client.exceptions import ApiException

            self.api_exception_cls = ApiException

            def _default_loader():
                try:
                    config.load_incluster_config()
                except Exception:
                    config.load_kube_config()

            self.config_loader = _default_loader
            self.core_v1_api = client.CoreV1Api()

        self.config_loader()
        return self.core_v1_api

    @staticmethod
    def _resource_name(session_id: str) -> str:
        sanitized = "".join(ch if ch.isalnum() else "-" for ch in session_id.lower())
        sanitized = sanitized.strip("-") or "session"
        prefix = sanitized[:24].rstrip("-") or "session"
        digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:8]
        return f"scienceclaw-sess-{prefix}-{digest}".rstrip("-")

    def _namespace(self) -> str:
        return getattr(self.settings, "k8s_namespace", "default")

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
    def _parse_name_list(raw: str) -> list[dict[str, str]]:
        return [{"name": item.strip()} for item in raw.split(",") if item.strip()]

    @staticmethod
    def _parse_json_list(raw: str) -> list[dict]:
        raw = (raw or "").strip()
        if not raw:
            return []
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("Expected a JSON list")
        return payload

    def _is_not_found(self, exc: Exception) -> bool:
        if self.api_exception_cls is not None and isinstance(exc, self.api_exception_cls):
            return getattr(exc, "status", None) == 404
        return "404" in str(exc) or "Not Found" in str(exc)

    def _build_workspace_volume(self) -> tuple[dict, dict]:
        volume_name = (
            getattr(self.settings, "k8s_runtime_workspace_volume_name", "workspace") or "workspace"
        ).strip()
        mount_path = (
            getattr(self.settings, "k8s_runtime_workspace_mount_path", "/home/scienceclaw")
            or "/home/scienceclaw"
        ).strip()
        pvc_claim = (
            getattr(self.settings, "k8s_runtime_workspace_pvc_claim", "") or ""
        ).strip()

        if pvc_claim:
            volume = {
                "name": volume_name,
                "persistentVolumeClaim": {"claimName": pvc_claim},
            }
        else:
            volume = {
                "name": volume_name,
                "emptyDir": {},
            }

        mount = {
            "name": volume_name,
            "mountPath": mount_path,
        }
        return volume, mount

    def _build_pod_manifest(self, name: str, session_id: str, user_id: str) -> dict:
        labels = {
            "app.kubernetes.io/name": "scienceclaw-session-runtime",
            "scienceclaw/runtime": "session",
            "scienceclaw/runtime-name": name,
            "scienceclaw/session-id": session_id,
            "scienceclaw/user-id": user_id,
        }
        labels.update(
            self._parse_key_value_map(getattr(self.settings, "k8s_runtime_labels", ""))
        )
        annotations = self._parse_key_value_map(
            getattr(self.settings, "k8s_runtime_annotations", "")
        )
        workspace_volume, workspace_mount = self._build_workspace_volume()
        container = {
            "name": "sandbox",
            "image": self.settings.runtime_image,
            "imagePullPolicy": getattr(self.settings, "k8s_runtime_image_pull_policy", "IfNotPresent"),
            "ports": [{"containerPort": self.settings.runtime_service_port, "name": "http"}],
            "volumeMounts": [
                workspace_mount,
                *self._parse_json_list(
                    getattr(self.settings, "k8s_runtime_extra_volume_mounts_json", "")
                ),
            ],
        }
        env_vars = self._parse_key_value_map(getattr(self.settings, "k8s_runtime_env", ""))
        if env_vars:
            container["env"] = [{"name": key, "value": value} for key, value in env_vars.items()]

        resources: dict[str, dict[str, str]] = {}
        requests: dict[str, str] = {}
        limits: dict[str, str] = {}
        if getattr(self.settings, "k8s_runtime_cpu_request", "").strip():
            requests["cpu"] = self.settings.k8s_runtime_cpu_request.strip()
        if getattr(self.settings, "k8s_runtime_memory_request", "").strip():
            requests["memory"] = self.settings.k8s_runtime_memory_request.strip()
        if getattr(self.settings, "k8s_runtime_cpu_limit", "").strip():
            limits["cpu"] = self.settings.k8s_runtime_cpu_limit.strip()
        if getattr(self.settings, "k8s_runtime_memory_limit", "").strip():
            limits["memory"] = self.settings.k8s_runtime_memory_limit.strip()
        if requests:
            resources["requests"] = requests
        if limits:
            resources["limits"] = limits
        if resources:
            container["resources"] = resources

        pod_spec: dict = {
            "containers": [container],
            "restartPolicy": "Never",
            "volumes": [
                workspace_volume,
                *self._parse_json_list(
                    getattr(self.settings, "k8s_runtime_extra_volumes_json", "")
                ),
            ],
        }
        service_account = (getattr(self.settings, "k8s_runtime_service_account", "") or "").strip()
        if service_account:
            pod_spec["serviceAccountName"] = service_account
        image_pull_secrets = self._parse_name_list(
            getattr(self.settings, "k8s_runtime_image_pull_secrets", "")
        )
        if image_pull_secrets:
            pod_spec["imagePullSecrets"] = image_pull_secrets
        node_selector = self._parse_key_value_map(
            getattr(self.settings, "k8s_runtime_node_selector", "")
        )
        if node_selector:
            pod_spec["nodeSelector"] = node_selector
        tolerations = self._parse_json_list(
            getattr(self.settings, "k8s_runtime_tolerations_json", "")
        )
        if tolerations:
            pod_spec["tolerations"] = tolerations
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "labels": labels,
                **({"annotations": annotations} if annotations else {}),
            },
            "spec": pod_spec,
        }

    def _build_service_manifest(self, name: str) -> dict:
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name},
            "spec": {
                "selector": {"scienceclaw/runtime-name": name},
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": self.settings.runtime_service_port,
                        "targetPort": self.settings.runtime_service_port,
                    }
                ],
            },
        }

    async def _wait_until_ready(self, api, name: str) -> None:
        timeout_seconds = int(getattr(self.settings, "runtime_wait_timeout_seconds", 0) or 0)
        if timeout_seconds <= 0:
            return

        deadline = time.monotonic() + timeout_seconds
        namespace = self._namespace()
        last_phase = "unknown"
        while time.monotonic() < deadline:
            pod = await asyncio.to_thread(api.read_namespaced_pod, name=name, namespace=namespace)
            status = getattr(pod, "status", None)
            phase = getattr(status, "phase", "unknown")
            last_phase = phase
            container_statuses = getattr(status, "container_statuses", None) or []
            if phase == "Running" and container_statuses and all(
                getattr(item, "ready", False) for item in container_statuses
            ):
                return
            await asyncio.sleep(1)

        raise RuntimeError(
            f"Timed out waiting for runtime pod {name} in namespace {namespace}; last phase={last_phase}"
        )

    async def create_runtime(self, session_id: str, user_id: str):
        api = self._load_clients()
        namespace = self._namespace()
        name = self._resource_name(session_id)

        pod_manifest = self._build_pod_manifest(name, session_id, user_id)
        service_manifest = self._build_service_manifest(name)

        await asyncio.to_thread(
            api.create_namespaced_pod, namespace=namespace, body=pod_manifest
        )
        try:
            await asyncio.to_thread(
                api.create_namespaced_service, namespace=namespace, body=service_manifest
            )
        except Exception:
            try:
                await asyncio.to_thread(
                    api.delete_namespaced_pod,
                    name=name,
                    namespace=namespace,
                    grace_period_seconds=0,
                )
            except Exception:
                pass
            raise

        await self._wait_until_ready(api, name)

        now = int(time.time())
        fqdn = f"{name}.{namespace}.svc.cluster.local"
        return SessionRuntimeRecord(
            session_id=session_id,
            user_id=user_id,
            namespace=namespace,
            pod_name=name,
            service_name=name,
            rest_base_url=f"http://{fqdn}:{self.settings.runtime_service_port}",
            status="ready",
            created_at=now,
            last_used_at=now,
        )

    async def delete_runtime(self, runtime_record) -> None:
        api = self._load_clients()
        namespace = runtime_record.namespace or self._namespace()

        for delete_call, name in (
            (api.delete_namespaced_service, runtime_record.service_name),
            (api.delete_namespaced_pod, runtime_record.pod_name),
        ):
            try:
                await asyncio.to_thread(
                    delete_call,
                    name=name,
                    namespace=namespace,
                    grace_period_seconds=0,
                )
            except TypeError:
                try:
                    await asyncio.to_thread(delete_call, name=name, namespace=namespace)
                except Exception as exc:
                    if self._is_not_found(exc):
                        logger.info(
                            "K8s runtime resource already removed for session %s: %s",
                            runtime_record.session_id,
                            name,
                        )
                        continue
                    raise
            except Exception as exc:
                if self._is_not_found(exc):
                    logger.info(
                        "K8s runtime resource already removed for session %s: %s",
                        runtime_record.session_id,
                        name,
                    )
                    continue
                raise

    async def refresh_runtime(self, runtime_record):
        api = self._load_clients()
        pod = await asyncio.to_thread(
            api.read_namespaced_pod,
            name=runtime_record.pod_name,
            namespace=runtime_record.namespace or self._namespace(),
        )
        phase = getattr(getattr(pod, "status", None), "phase", runtime_record.status)
        runtime_record.status = "ready" if phase == "Running" else str(phase).lower()
        return runtime_record
