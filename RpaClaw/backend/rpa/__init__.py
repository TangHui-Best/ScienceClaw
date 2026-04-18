"""RPA package exports.

Keep package import lightweight so contract/compiler modules can be imported in
unit tests and non-browser contexts without importing Playwright immediately.
"""

from __future__ import annotations

from typing import Any

__all__ = ["rpa_manager", "RPASession", "RPAStep", "cdp_connector"]


def __getattr__(name: str) -> Any:
    if name in {"rpa_manager", "RPASession", "RPAStep"}:
        from .manager import RPASession, RPAStep, rpa_manager

        exports = {
            "rpa_manager": rpa_manager,
            "RPASession": RPASession,
            "RPAStep": RPAStep,
        }
        return exports[name]
    if name == "cdp_connector":
        from .cdp_connector import cdp_connector

        return cdp_connector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
