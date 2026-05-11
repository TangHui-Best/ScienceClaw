from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from backend.rpa.harness.packets import (
    FailurePacket,
    ObservationPacket,
    RPAHarnessArtifactRef,
    RPAHarnessRedactionPolicy,
)
from backend.rpa.harness.redaction import redact_payload


class RPAHarnessArtifactStore:
    def __init__(
        self,
        root: str | Path,
        max_packets_per_kind: int = 100,
        redaction_policy: RPAHarnessRedactionPolicy | None = None,
    ) -> None:
        self.root = Path(root)
        self.max_packets_per_kind = max(1, max_packets_per_kind)
        self.redaction_policy = redaction_policy

    def write_packet(self, packet: ObservationPacket | FailurePacket) -> Path:
        packet_dir = self._packet_dir(packet.packet_kind, packet.packet_id)
        packet_dir.mkdir(parents=True, exist_ok=True)

        packet_path = packet_dir / "packet.json"
        payload = redact_payload(
            packet.model_dump(mode="json"),
            self.redaction_policy,
        )
        packet_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.prune(packet.packet_kind)
        return packet_path

    def write_packet_artifact(
        self,
        packet_kind: str,
        packet_id: str,
        artifact_name: str,
        payload: Any,
        *,
        media_type: str = "application/json",
    ) -> RPAHarnessArtifactRef:
        self._validate_path_segment(artifact_name, "artifact_name")
        packet_dir = self._packet_dir(packet_kind, packet_id)
        artifact_dir = (packet_dir / "artifacts").resolve()
        self._validate_under_root(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = (artifact_dir / artifact_name).resolve()
        self._validate_under_root(artifact_path)
        redacted_payload = redact_payload(payload, self.redaction_policy)
        if media_type == "application/json":
            artifact_path.write_text(
                json.dumps(redacted_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            artifact_path.write_text(str(redacted_payload), encoding="utf-8")

        relative_path = artifact_path.relative_to(self.root.resolve()).as_posix()
        return RPAHarnessArtifactRef(
            path=relative_path,
            media_type=media_type,
            redacted=True,
        )

    def read_observation_packet(self, path: str | Path) -> ObservationPacket:
        return ObservationPacket.model_validate(self._read_packet_json(path))

    def read_failure_packet(self, path: str | Path) -> FailurePacket:
        return FailurePacket.model_validate(self._read_packet_json(path))

    def prune(self, packet_kind: str) -> None:
        kind_dir = self._kind_dir(packet_kind)
        if not kind_dir.exists():
            return

        packet_dirs = [path for path in kind_dir.iterdir() if path.is_dir()]
        if len(packet_dirs) <= self.max_packets_per_kind:
            return

        ordered = sorted(packet_dirs, key=self._packet_sort_key)
        for packet_dir in ordered[: -self.max_packets_per_kind]:
            shutil.rmtree(packet_dir)

    def _packet_sort_key(self, packet_dir: Path) -> tuple[str, str]:
        packet_path = packet_dir / "packet.json"
        try:
            payload = self._read_json(packet_path)
        except (OSError, json.JSONDecodeError):
            return ("", packet_dir.name)
        created_at = payload.get("created_at") if isinstance(payload, dict) else None
        return (str(created_at or ""), packet_dir.name)

    def _packet_dir(self, packet_kind: str, packet_id: str) -> Path:
        kind_dir = self._kind_dir(packet_kind)
        self._validate_path_segment(packet_id, "packet_id")

        packet_dir = (kind_dir / packet_id).resolve()
        self._validate_under_root(packet_dir)
        return packet_dir

    def _kind_dir(self, packet_kind: str) -> Path:
        self._validate_path_segment(packet_kind, "packet_kind")

        kind_dir = (self.root.resolve() / packet_kind).resolve()
        self._validate_under_root(kind_dir)
        return kind_dir

    def _validate_under_root(self, packet_dir: Path) -> None:
        root = self.root.resolve()
        if packet_dir != root and root not in packet_dir.parents:
            raise ValueError("artifact path must stay under artifact root")

    def _validate_path_segment(self, value: str, field_name: str) -> None:
        path = Path(value)
        if (
            not value
            or value in {".", ".."}
            or path.name != value
            or "/" in value
            or "\\" in value
        ):
            raise ValueError(f"unsafe {field_name}: {value!r}")

    def _read_packet_json(self, path: str | Path) -> Any:
        packet_path = Path(path).resolve()
        self._validate_under_root(packet_path)
        return self._read_json(packet_path)

    def _read_json(self, path: str | Path) -> Any:
        with Path(path).open("r", encoding="utf-8") as packet_file:
            return json.load(packet_file)
