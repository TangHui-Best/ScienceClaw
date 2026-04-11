import importlib
import unittest


SCREencAST_MODULE = importlib.import_module("backend.rpa.screencast")


class _FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class _FakeCDPSession:
    def __init__(self, responses=None):
        self.handlers = {}
        self.sent = []
        self.detached = False
        self.responses = responses or {}

    def on(self, event_name, handler):
        self.handlers[event_name] = handler

    async def send(self, method, params):
        self.sent.append((method, params))
        return self.responses.get(method)

    async def detach(self):
        self.detached = True


class _FakeContext:
    def __init__(self, failures_before_success=0):
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def new_cdp_session(self, _page):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError("attach failed")
        return _FakeCDPSession()


class _FakePage:
    def __init__(self, context):
        self.context = context


class SessionScreencastControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_switch_page_retries_once_before_succeeding(self):
        context = _FakeContext(failures_before_success=1)
        page = _FakePage(context)
        ws = _FakeWebSocket()
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: page,
            tabs_provider=lambda: [],
        )
        controller._ws = ws
        controller._running = True

        await controller._switch_page_if_needed(force=True)

        self.assertEqual(context.calls, 2)
        self.assertIsNotNone(controller._cdp)
        self.assertEqual([message["type"] for message in ws.messages], [])

    async def test_switch_page_emits_preview_error_after_retries_fail(self):
        context = _FakeContext(failures_before_success=3)
        page = _FakePage(context)
        ws = _FakeWebSocket()
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: page,
            tabs_provider=lambda: [],
        )
        controller._ws = ws
        controller._running = True

        with self.assertRaises(RuntimeError):
            await controller._switch_page_if_needed(force=True)

        self.assertEqual(context.calls, 2)
        self.assertEqual(ws.messages[-1]["type"], "preview_error")

    async def test_dispatch_key_backspace_uses_raw_key_payload_without_text(self):
        cdp = _FakeCDPSession()
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: None,
            tabs_provider=lambda: [],
        )
        controller._cdp = cdp

        await controller._dispatch_key(
            {
                "action": "keyDown",
                "key": "Backspace",
                "code": "Backspace",
                "text": "",
                "modifiers": 0,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchKeyEvent")
        self.assertEqual(payload["type"], "rawKeyDown")
        self.assertEqual(payload["key"], "Backspace")
        self.assertEqual(payload["code"], "Backspace")
        self.assertEqual(payload["windowsVirtualKeyCode"], 8)
        self.assertEqual(payload["nativeVirtualKeyCode"], 8)
        self.assertNotIn("text", payload)

    async def test_refresh_input_metrics_uses_css_visual_viewport_dimensions(self):
        cdp = _FakeCDPSession(
            responses={
                "Page.getLayoutMetrics": {
                    "cssVisualViewport": {
                        "clientWidth": 800,
                        "clientHeight": 600,
                    }
                }
            }
        )
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: None,
            tabs_provider=lambda: [],
        )
        controller._cdp = cdp
        controller._input_width = 1280
        controller._input_height = 720

        await controller._refresh_input_metrics()

        self.assertEqual(controller._input_width, 800)
        self.assertEqual(controller._input_height, 600)

    async def test_dispatch_mouse_uses_css_pixel_coordinates_without_scaling(self):
        cdp = _FakeCDPSession()
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: None,
            tabs_provider=lambda: [],
        )
        controller._cdp = cdp
        controller._input_width = 800
        controller._input_height = 600
        controller._frame_width = 1920
        controller._frame_height = 1080

        await controller._dispatch_mouse(
            {
                "action": "mousePressed",
                "x": 400,
                "y": 300,
                "button": "left",
                "clickCount": 1,
                "modifiers": 0,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchMouseEvent")
        self.assertEqual(payload["x"], 400)
        self.assertEqual(payload["y"], 300)

    async def test_on_frame_emits_separate_frame_and_input_dimensions(self):
        ws = _FakeWebSocket()
        controller = SCREencAST_MODULE.SessionScreencastController(
            page_provider=lambda: None,
            tabs_provider=lambda: [],
        )
        controller._cdp = _FakeCDPSession()
        controller._ws = ws
        controller._running = True
        controller._frame_width = 1600
        controller._frame_height = 900
        controller._input_width = 800
        controller._input_height = 600

        await controller._on_frame(
            {
                "sessionId": 1,
                "data": "ZmFrZQ==",
                "metadata": {
                    "timestamp": 123.0,
                    "deviceWidth": 1600,
                    "deviceHeight": 900,
                },
            }
        )

        self.assertEqual(ws.messages[-1]["type"], "frame")
        self.assertEqual(ws.messages[-1]["metadata"]["frameWidth"], 1600)
        self.assertEqual(ws.messages[-1]["metadata"]["frameHeight"], 900)
        self.assertEqual(ws.messages[-1]["metadata"]["inputWidth"], 800)
        self.assertEqual(ws.messages[-1]["metadata"]["inputHeight"], 600)


class ScreencastServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_key_backspace_uses_raw_key_payload_without_text(self):
        cdp = _FakeCDPSession()
        service = SCREencAST_MODULE.ScreencastService(cdp)

        await service._dispatch_key(
            {
                "action": "keyDown",
                "key": "Backspace",
                "code": "Backspace",
                "text": "",
                "modifiers": 0,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchKeyEvent")
        self.assertEqual(payload["type"], "rawKeyDown")
        self.assertEqual(payload["key"], "Backspace")
        self.assertEqual(payload["windowsVirtualKeyCode"], 8)
        self.assertEqual(payload["nativeVirtualKeyCode"], 8)
        self.assertNotIn("text", payload)

    async def test_dispatch_key_shifted_digit_uses_physical_key_code(self):
        cdp = _FakeCDPSession()
        service = SCREencAST_MODULE.ScreencastService(cdp)

        await service._dispatch_key(
            {
                "action": "keyDown",
                "key": "!",
                "code": "Digit1",
                "text": "!",
                "modifiers": 8,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchKeyEvent")
        self.assertEqual(payload["type"], "keyDown")
        self.assertEqual(payload["key"], "!")
        self.assertEqual(payload["code"], "Digit1")
        self.assertEqual(payload["windowsVirtualKeyCode"], 49)
        self.assertEqual(payload["nativeVirtualKeyCode"], 49)
        self.assertEqual(payload["text"], "!")
        self.assertEqual(payload["unmodifiedText"], "1")

    async def test_dispatch_key_enter_uses_keydown_with_carriage_return_text(self):
        cdp = _FakeCDPSession()
        service = SCREencAST_MODULE.ScreencastService(cdp)

        await service._dispatch_key(
            {
                "action": "keyDown",
                "key": "Enter",
                "code": "Enter",
                "text": "",
                "modifiers": 0,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchKeyEvent")
        self.assertEqual(payload["type"], "keyDown")
        self.assertEqual(payload["key"], "Enter")
        self.assertEqual(payload["code"], "Enter")
        self.assertEqual(payload["windowsVirtualKeyCode"], 13)
        self.assertEqual(payload["nativeVirtualKeyCode"], 13)
        self.assertEqual(payload["text"], "\r")
        self.assertEqual(payload["unmodifiedText"], "\r")

    async def test_dispatch_mouse_uses_css_pixel_coordinates_without_scaling(self):
        cdp = _FakeCDPSession()
        service = SCREencAST_MODULE.ScreencastService(cdp)
        service._input_width = 800
        service._input_height = 600
        service._frame_width = 1920
        service._frame_height = 1080

        await service._dispatch_mouse(
            {
                "action": "mouseMoved",
                "x": 401,
                "y": 299,
                "modifiers": 0,
            }
        )

        self.assertEqual(len(cdp.sent), 1)
        method, payload = cdp.sent[0]
        self.assertEqual(method, "Input.dispatchMouseEvent")
        self.assertEqual(payload["x"], 401)
        self.assertEqual(payload["y"], 299)


if __name__ == "__main__":
    unittest.main()
