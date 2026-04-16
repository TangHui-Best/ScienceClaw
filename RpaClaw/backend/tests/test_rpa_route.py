import importlib
import json
import unittest
from datetime import datetime


ROUTE_MODULE = importlib.import_module("backend.route.rpa")
MANAGER_MODULE = importlib.import_module("backend.rpa.manager")


class RPARouteSerializationTests(unittest.TestCase):
    def test_json_ready_step_payloads_converts_datetime_fields(self):
        step = MANAGER_MODULE.RPAStep(
            id="step-1",
            action="navigate",
            description="Open trending",
            value="https://github.com/trending",
            timestamp=datetime(2026, 4, 15, 10, 30, 0),
        )

        payload = {"steps": ROUTE_MODULE._json_ready_step_payloads([step])}
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertIn("2026-04-15T10:30:00", encoded)


if __name__ == "__main__":
    unittest.main()
