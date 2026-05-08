"""Tests for user action capture JS and handler."""
import asyncio
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.rpa.api_monitor.manager import ApiMonitorSessionManager, _USER_ACTION_CAPTURE_JS
from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest


class TestUserActionCaptureJS:
    def test_js_contains_binding_name(self):
        assert "__apiMonitorAction" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_click(self):
        assert "click" in _USER_ACTION_CAPTURE_JS
        assert "describeElement" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_submit(self):
        assert "submit" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_navigate(self):
        assert "pushState" in _USER_ACTION_CAPTURE_JS
        assert "popstate" in _USER_ACTION_CAPTURE_JS

    def test_js_guards_against_double_install(self):
        assert "__apiMonitorActionInstalled" in _USER_ACTION_CAPTURE_JS
