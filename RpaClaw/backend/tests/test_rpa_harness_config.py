from pathlib import Path
from types import SimpleNamespace

from backend.rpa.harness.config import (
    harness_capture_enabled,
    harness_assets_dir,
    parse_harness_bool,
)


def test_parse_harness_bool_defaults_to_disabled():
    assert parse_harness_bool(None) is False
    assert parse_harness_bool("") is False
    assert parse_harness_bool("false") is False
    assert parse_harness_bool("0") is False
    assert parse_harness_bool("no") is False


def test_parse_harness_bool_accepts_true_like_values():
    assert parse_harness_bool("true") is True
    assert parse_harness_bool("1") is True
    assert parse_harness_bool("yes") is True
    assert parse_harness_bool("on") is True


def test_harness_capture_enabled_reads_settings_flag():
    assert harness_capture_enabled(SimpleNamespace(rpa_harness_capture_enabled=True)) is True
    assert harness_capture_enabled(SimpleNamespace(rpa_harness_capture_enabled=False)) is False


def test_harness_assets_dir_uses_explicit_setting():
    settings = SimpleNamespace(
        rpa_harness_assets_dir="E:/tmp/custom-assets",
        local_data_dir="E:/tmp/data",
    )

    assert harness_assets_dir(settings) == Path("E:/tmp/custom-assets")


def test_harness_assets_dir_derives_from_local_data_dir_when_missing():
    settings = SimpleNamespace(rpa_harness_assets_dir="", local_data_dir="E:/tmp/data")

    assert harness_assets_dir(settings) == Path("E:/tmp/data") / "rpa_harness_assets"

