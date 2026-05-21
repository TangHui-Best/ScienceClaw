from __future__ import annotations

from io import BytesIO

from backend.rpa.harness.cli import emit_json_report


class _FakeStdout:
    encoding = "cp936"

    def __init__(self) -> None:
        self.buffer = BytesIO()
        self.text_writes: list[str] = []

    def write(self, value: str) -> None:
        self.text_writes.append(value)

    def flush(self) -> None:
        pass


def test_emit_json_report_writes_utf8_bytes_for_unicode_stdout() -> None:
    stdout = _FakeStdout()

    emit_json_report({"step_intent": "\u83b7\u53d6start\u6570"}, stdout=stdout)

    assert stdout.text_writes == []
    assert b'\xe8\x8e\xb7\xe5\x8f\x96start\xe6\x95\xb0' in stdout.buffer.getvalue()
