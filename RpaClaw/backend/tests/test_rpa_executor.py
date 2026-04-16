import importlib
import importlib.util
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


EXECUTOR_MODULE = importlib.import_module("backend.rpa.executor")
GENERATOR_PATH = Path(__file__).resolve().parents[1] / "rpa" / "generator.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location("rpa_generator_module_for_executor", GENERATOR_PATH)
GENERATOR_MODULE = importlib.util.module_from_spec(GENERATOR_SPEC)
assert GENERATOR_SPEC is not None and GENERATOR_SPEC.loader is not None
GENERATOR_SPEC.loader.exec_module(GENERATOR_MODULE)
PlaywrightGenerator = GENERATOR_MODULE.PlaywrightGenerator

SEMANTIC_RULE_STEP = {
    "action": "ai_instruction",
    "source": "ai",
    "description": "Sync table A into table B by matching rows on name",
    "prompt": "Fill table B from table A by matching rows on name, then submit",
    "instruction_kind": "semantic_rule",
    "input_scope": {"mode": "current_page"},
    "output_expectation": {"mode": "act"},
    "execution_hint": {
        "requires_dom_snapshot": True,
        "allow_navigation": True,
        "max_reasoning_steps": 10,
    },
}


class _FakePage:
    def __init__(self, context, title="Page", url="about:blank"):
        self.context = context
        self._title = title
        self.url = url
        self.handlers = {}
        self.default_timeout = None
        self.default_navigation_timeout = None

    async def title(self):
        return self._title

    async def expose_function(self, _name, _fn):
        return None

    async def evaluate(self, _script):
        return None

    async def bring_to_front(self):
        return None

    async def wait_for_timeout(self, _timeout):
        return None

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout):
        self.default_navigation_timeout = timeout

    def on(self, event_name, handler):
        self.handlers[event_name] = handler


class _FakeContext:
    def __init__(self):
        self.handlers = {}
        self.closed = False
        self.pages = []

    async def new_page(self):
        page = _FakePage(self, title=f"Page {len(self.pages) + 1}")
        self.pages.append(page)
        return page

    def on(self, event_name, handler):
        self.handlers[event_name] = handler

    async def create_popup(self):
        popup = _FakePage(self, title="Popup", url="https://example.com/popup")
        self.pages.append(popup)
        handler = self.handlers.get("page")
        if handler:
            handler(popup)
        return popup

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.contexts = []

    async def new_context(self, **_kwargs):
        context = _FakeContext()
        self.contexts.append(context)
        return context


class _FakeSessionManager:
    def __init__(self):
        self.attached = []
        self.registered = []
        self.context_pages = []
        self.detached = []

    def attach_context(self, session_id, context):
        self.attached.append((session_id, context))

    async def register_page(self, session_id, page, make_active=False):
        self.registered.append((session_id, page, make_active))
        return "root-tab"

    async def register_context_page(self, session_id, page, make_active=True):
        self.context_pages.append((session_id, page, make_active))
        return "popup-tab"

    def detach_context(self, session_id, context=None):
        self.detached.append((session_id, context))


class ScriptExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_registers_popup_pages_with_session_manager(self):
        browser = _FakeBrowser()
        session_manager = _FakeSessionManager()
        page_registry = {}
        script = """
import asyncio

async def execute_skill(page, **kwargs):
    await page.context.create_popup()
    await asyncio.sleep(0)
    return {"ok": True}
"""

        result = await EXECUTOR_MODULE.ScriptExecutor().execute(
            browser,
            script,
            session_id="session-1",
            page_registry=page_registry,
            session_manager=session_manager,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(browser.contexts), 1)
        self.assertEqual(len(session_manager.attached), 1)
        self.assertEqual(len(session_manager.registered), 1)
        self.assertEqual(len(session_manager.context_pages), 1)
        self.assertEqual(session_manager.registered[0][0], "session-1")
        self.assertEqual(session_manager.context_pages[0][0], "session-1")
        self.assertEqual(session_manager.detached, [("session-1", browser.contexts[0])])
        self.assertEqual(page_registry, {})
        self.assertTrue(browser.contexts[0].closed)

    async def test_execute_injects_execute_ai_instruction_symbol(self):
        browser = _FakeBrowser()
        script = '''
async def execute_skill(page, **kwargs):
    assert execute_ai_instruction is not None
    return {"ok": True}
'''

        result = await EXECUTOR_MODULE.ScriptExecutor().execute(browser, script)

        self.assertTrue(result["success"])

    async def test_execute_runs_generated_ai_instruction_script(self):
        browser = _FakeBrowser()
        script = PlaywrightGenerator().generate_script([SEMANTIC_RULE_STEP], is_local=True)

        with patch.object(
            EXECUTOR_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "ok"}),
        ) as execute_mock:
            result = await EXECUTOR_MODULE.ScriptExecutor().execute(browser, script)

        self.assertTrue(result["success"])
        execute_mock.assert_awaited_once()
        self.assertEqual(execute_mock.await_args.kwargs["step"]["action"], "ai_instruction")
        self.assertEqual(
            execute_mock.await_args.kwargs["step"]["prompt"],
            "Fill table B from table A by matching rows on name, then submit",
        )

    async def test_execute_generated_ai_instruction_script_surfaces_helper_errors(self):
        browser = _FakeBrowser()
        script = PlaywrightGenerator().generate_script([SEMANTIC_RULE_STEP], is_local=True, test_mode=True)

        with patch.object(
            EXECUTOR_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": False, "error": "AI instruction planning timed out after 25s"}),
        ):
            result = await EXECUTOR_MODULE.ScriptExecutor().execute(browser, script)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step_index"], 0)
        self.assertIn("planning timed out", result["error"])

    async def test_execute_sanitizes_non_jsonable_result_data(self):
        browser = _FakeBrowser()
        script = """
import threading

async def execute_skill(page, **kwargs):
    return {"ok": True, "lock": threading.Lock()}
"""

        result = await EXECUTOR_MODULE.ScriptExecutor().execute(browser, script)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["ok"], True)
        self.assertIsInstance(result["data"]["lock"], str)


class StepExecutionErrorTests(unittest.IsolatedAsyncioTestCase):
    """Tests for STEP_FAILED: parsing in the except Exception block."""

    async def test_execute_returns_failed_step_index_on_step_error(self):
        executor = EXECUTOR_MODULE.ScriptExecutor()
        script = '''
class StepExecutionError(Exception):
    def __init__(self, step_index, original_error):
        self.step_index = step_index
        self.original_error = original_error
        super().__init__(f"STEP_FAILED:{step_index}:{original_error}")

async def execute_skill(page, **kwargs):
    raise StepExecutionError(step_index=2, original_error="Timeout 30000ms exceeded")
'''
        browser = _FakeBrowser()
        result = await executor.execute(browser, script)

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step_index"], 2)
        self.assertEqual(result["error"], "Timeout 30000ms exceeded")

    async def test_execute_returns_none_failed_step_index_on_generic_error(self):
        executor = EXECUTOR_MODULE.ScriptExecutor()
        script = '''
async def execute_skill(page, **kwargs):
    raise RuntimeError("something broke")
'''
        browser = _FakeBrowser()
        result = await executor.execute(browser, script)

        self.assertFalse(result["success"])
        self.assertIsNone(result["failed_step_index"])

    async def test_execute_returns_none_failed_step_index_on_success(self):
        executor = EXECUTOR_MODULE.ScriptExecutor()
        script = '''
async def execute_skill(page, **kwargs):
    return {"ok": True}
'''
        browser = _FakeBrowser()
        result = await executor.execute(browser, script)

        self.assertTrue(result["success"])
        self.assertIsNone(result.get("failed_step_index"))


if __name__ == "__main__":
    unittest.main()
