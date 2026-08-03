from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from rpa_agent.quality.architecture_guard import find_next_architecture_violations


BACKEND = Path(__file__).parents[2]


def test_s0_packages_do_not_cross_runtime_or_quality_ownership_boundaries() -> None:
    assert find_next_architecture_violations(
        BACKEND / "rpa_agent" / "platform",
        BACKEND / "rpa_agent" / "quality",
        BACKEND / "runtime" / "rpa_agent_next_aio_provider.py",
    ) == []


def test_guard_rejects_legacy_runtime_and_quality_imports() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        platform = root / "platform"
        quality = root / "quality"
        runtime = root / "runtime"
        platform.mkdir()
        quality.mkdir()
        runtime.mkdir()
        (platform / "bad.py").write_text(
            "from backend.runtime.aio_runtime_provider import AioNativeRuntimeProvider\n",
            encoding="utf-8",
        )
        (quality / "bad.py").write_text(
            "from rpa_agent.creation import RecordingSession\nfrom backend.rpa import manager\n",
            encoding="utf-8",
        )
        (runtime / "rpa_agent_next_aio_provider.py").write_text(
            "from rpa_agent.compiler import compile_trace\n",
            encoding="utf-8",
        )

        assert find_next_architecture_violations(root) == [
            "platform/bad.py:1: forbidden import 'backend.runtime.aio_runtime_provider'",
            "quality/bad.py:1: forbidden import 'rpa_agent.creation'",
            "quality/bad.py:2: forbidden import 'backend.rpa'",
            "runtime/rpa_agent_next_aio_provider.py:1: forbidden import 'rpa_agent.compiler'",
        ]
