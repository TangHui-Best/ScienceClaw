import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    async def count(self):
        if self.selector == 'a[href*="SimoneAvogadro/android-reverse-engineering-skill"]':
            return 3
        if self.selector == 'a[href="/SimoneAvogadro/android-reverse-engineering-skill"]':
            return 1
        return 0

    async def click(self):
        if self.selector == 'a[href*="SimoneAvogadro/android-reverse-engineering-skill"]':
            raise RuntimeError("strict mode violation: resolved to 3 elements")
        self.page.clicked_selector = self.selector


class _FakePage:
    def __init__(self):
        self.clicked_selector = ""

    def locator(self, selector):
        return _FakeLocator(self, selector)

    async def wait_for_load_state(self, state, timeout=None):
        return None

    async def wait_for_timeout(self, timeout):
        return None


def _load_assistant_runtime_module():
    backend_dir = Path(__file__).resolve().parents[1]
    rpa_dir = backend_dir / "rpa"

    backend_pkg = sys.modules.setdefault("backend", types.ModuleType("backend"))
    backend_pkg.__path__ = [str(backend_dir)]
    rpa_pkg = sys.modules.setdefault("backend.rpa", types.ModuleType("backend.rpa"))
    rpa_pkg.__path__ = [str(rpa_dir)]

    module_name = "backend.rpa.assistant_runtime"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, rpa_dir / "assistant_runtime.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class AssistantRuntimeLocatorTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_structured_intent_uses_exact_href_when_falling_back_to_link_href(self):
        assistant_runtime = _load_assistant_runtime_module()
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "elements": [
                        {
                            "tag": "a",
                            "role": "link",
                            "href": "/SimoneAvogadro/android-reverse-engineering-skill",
                        }
                    ],
                    "collections": [],
                }
            ],
            "actionable_nodes": [],
            "content_nodes": [],
        }

        resolved = assistant_runtime.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "target_hint": {"role": "link"},
                "description": "Open selected repository",
            },
        )

        self.assertEqual(
            resolved["resolved"]["locator"],
            {"method": "css", "value": 'a[href="/SimoneAvogadro/android-reverse-engineering-skill"]'},
        )

    async def test_execute_structured_intent_normalizes_broad_href_click_to_exact_href(self):
        assistant_runtime = _load_assistant_runtime_module()
        page = _FakePage()

        result = await assistant_runtime.execute_structured_intent(
            page,
            {
                "action": "click",
                "description": "Open selected repository",
                "resolved": {
                    "frame_path": [],
                    "locator": {
                        "method": "css",
                        "value": 'a[href*="SimoneAvogadro/android-reverse-engineering-skill"]',
                    },
                    "locator_candidates": [],
                    "collection_hint": {},
                    "item_hint": {},
                    "ordinal": None,
                    "selected_locator_kind": "css",
                },
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            page.clicked_selector,
            'a[href="/SimoneAvogadro/android-reverse-engineering-skill"]',
        )


if __name__ == "__main__":
    unittest.main()
