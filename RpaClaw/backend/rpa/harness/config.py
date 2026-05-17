from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config import settings


TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_harness_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def harness_capture_enabled(settings_obj: Any = settings) -> bool:
    return bool(getattr(settings_obj, "rpa_harness_capture_enabled", False))


def harness_assets_dir(settings_obj: Any = settings) -> Path:
    explicit = str(getattr(settings_obj, "rpa_harness_assets_dir", "") or "").strip()
    if explicit:
        return Path(explicit)
    local_data_dir = str(getattr(settings_obj, "local_data_dir", "./data") or "./data")
    return Path(local_data_dir) / "rpa_harness_assets"

