import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from database import engine
from main import app


TEST_RESET_TOKEN = "first-browser-e2e-reset-token"
RESET_HEADERS = {"X-RPA-Eval-Reset-Token": TEST_RESET_TOKEN}


class FirstBrowserE2EBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict("os.environ", {"RPA_EVAL_RESET_TOKEN": TEST_RESET_TOKEN})
        self.env.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        auth_response = self.client.post(
            "/api/eval/auth-token",
            headers=RESET_HEADERS,
            json={"username": "buyer"},
        )
        self.assertEqual(200, auth_response.status_code)
        self.auth_headers = {
            "Authorization": f"Bearer {auth_response.json()['access_token']}"
        }

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        engine.dispose()
        self.env.stop()

    def reset(self, profile: str | None = None):
        suffix = f"?profile={profile}" if profile else ""
        return self.client.post(f"/api/eval/reset{suffix}", headers=RESET_HEADERS)

    def list_orders(self, **params: str):
        return self.client.get(
            "/api/acceptance/orders",
            headers=self.auth_headers,
            params=params,
        )

    def create_task(self, order_no: str):
        return self.client.post(
            f"/api/acceptance/orders/{order_no}/tasks",
            headers=self.auth_headers,
        )

    def test_profile_a_target_is_first_among_matching_supplier_orders(self):
        response = self.reset("case_a")
        self.assertEqual(200, response.status_code)
        self.assertEqual("case_a", response.json()["profile"])

        orders_response = self.list_orders(
            business_type="设备采购",
            date_from="2026-05-01",
            date_to="2026-05-31",
            supplier_name="华东精密设备有限公司",
        )
        self.assertEqual(200, orders_response.status_code)
        orders = orders_response.json()
        self.assertGreaterEqual(len(orders), 3)
        self.assertEqual("PO-2026-05017", orders[0]["order_no"])
        self.assertEqual(Decimal("128600.50"), Decimal(str(orders[0]["amount"])))
        self.assertEqual("CNY", orders[0]["currency"])

    def test_profile_b_target_is_third_among_matching_supplier_orders(self):
        response = self.reset("case_b")
        self.assertEqual(200, response.status_code)

        orders_response = self.list_orders(
            business_type="服务采购",
            date_from="2026-06-01",
            date_to="2026-06-30",
            supplier_name="北辰数字技术有限公司",
        )
        self.assertEqual(200, orders_response.status_code)
        orders = orders_response.json()
        self.assertGreaterEqual(len(orders), 3)
        self.assertEqual("PO-2026-06042", orders[2]["order_no"])
        self.assertEqual(Decimal("10150.75"), Decimal(str(orders[2]["amount"])))
        self.assertEqual("USD", orders[2]["currency"])

    def test_order_search_applies_every_filter_on_the_backend(self):
        self.reset("case_b")

        exact = self.list_orders(
            business_type="服务采购",
            date_from="2026-06-08",
            date_to="2026-06-08",
            supplier_name="北辰数字技术有限公司",
            order_no="PO-2026-06042",
        )
        self.assertEqual(200, exact.status_code)
        self.assertEqual(["PO-2026-06042"], [row["order_no"] for row in exact.json()])

        self.assertEqual([], self.list_orders(business_type="设备采购").json())
        self.assertEqual([], self.list_orders(date_from="2026-06-09").json())
        self.assertEqual([], self.list_orders(supplier_name="不存在的供应商").json())
        self.assertEqual([], self.list_orders(order_no="PO-UNKNOWN").json())

    def test_task_ids_and_tokens_are_random_and_must_match(self):
        self.reset("case_a")
        first = self.create_task("PO-2026-05017")
        second = self.create_task("PO-2026-05017")
        self.assertEqual(201, first.status_code)
        self.assertEqual(201, second.status_code)
        first_payload = first.json()
        second_payload = second.json()
        self.assertNotEqual(first_payload["task_id"], second_payload["task_id"])
        self.assertNotEqual(first_payload["token"], second_payload["token"])
        self.assertIn(first_payload["task_id"], first_payload["url"])
        self.assertIn(first_payload["token"], first_payload["url"])

        valid = self.client.get(
            f"/api/acceptance/tasks/{first_payload['task_id']}",
            headers=self.auth_headers,
            params={"token": first_payload["token"]},
        )
        invalid = self.client.get(
            f"/api/acceptance/tasks/{first_payload['task_id']}",
            headers=self.auth_headers,
            params={"token": second_payload["token"]},
        )
        self.assertEqual(200, valid.status_code)
        self.assertEqual("PO-2026-05017", valid.json()["order"]["order_no"])
        self.assertEqual(403, invalid.status_code)

    def test_profiles_place_business_iframe_at_different_ordinals(self):
        self.reset("case_a")
        task_a = self.create_task("PO-2026-05017").json()
        response_a = self.client.get(
            f"/api/acceptance/tasks/{task_a['task_id']}",
            headers=self.auth_headers,
            params={"token": task_a["token"]},
        )

        self.reset("case_b")
        task_b = self.create_task("PO-2026-06042").json()
        response_b = self.client.get(
            f"/api/acceptance/tasks/{task_b['task_id']}",
            headers=self.auth_headers,
            params={"token": task_b["token"]},
        )

        self.assertEqual(200, response_a.status_code)
        self.assertEqual(200, response_b.status_code)
        self.assertEqual(1, response_a.json()["non_business_frame_count"])
        self.assertEqual(2, response_b.json()["non_business_frame_count"])

    def test_save_creates_real_record_oracle_reads_it_and_duplicate_is_rejected(self):
        self.reset("case_b")
        task = self.create_task("PO-2026-06042").json()
        record = {
            "order_no": "PO-2026-06042",
            "supplier_name": "北辰数字技术有限公司",
            "contract_no": "CT-2026-0116",
            "amount": "10150.75",
            "currency": "USD",
            "order_date": "2026-06-08",
            "note": "自动创建",
            "confirmed": True,
        }

        created = self.client.post(
            f"/api/acceptance/tasks/{task['task_id']}/records",
            headers=self.auth_headers,
            params={"token": task["token"]},
            json=record,
        )
        duplicate = self.client.post(
            f"/api/acceptance/tasks/{task['task_id']}/records",
            headers=self.auth_headers,
            params={"token": task["token"]},
            json=record,
        )
        oracle = self.client.get(
            "/api/eval/oracle/acceptance",
            headers=RESET_HEADERS,
            params={"task_id": task["task_id"]},
        )

        self.assertEqual(201, created.status_code)
        self.assertEqual(409, duplicate.status_code)
        self.assertEqual(200, oracle.status_code)
        payload = oracle.json()
        self.assertEqual(task["task_id"], payload["task_id"])
        for key, value in record.items():
            if key == "amount":
                self.assertEqual(Decimal(value), Decimal(str(payload[key])))
            else:
                self.assertEqual(value, payload[key])

    def test_oracle_requires_reset_token(self):
        self.reset("case_a")
        task = self.create_task("PO-2026-05017").json()
        response = self.client.get(
            "/api/eval/oracle/acceptance",
            params={"task_id": task["task_id"]},
        )
        self.assertEqual(403, response.status_code)

    def test_reset_removes_previous_profile_orders_tasks_and_records(self):
        self.reset("case_a")
        task = self.create_task("PO-2026-05017").json()
        self.client.post(
            f"/api/acceptance/tasks/{task['task_id']}/records",
            headers=self.auth_headers,
            params={"token": task["token"]},
            json={
                "order_no": "PO-2026-05017",
                "supplier_name": "华东精密设备有限公司",
                "contract_no": "CT-2026-0088",
                "amount": "128600.50",
                "currency": "CNY",
                "order_date": "2026-05-16",
                "note": "自动创建",
                "confirmed": True,
            },
        )

        self.reset("case_b")
        self.assertEqual([], self.list_orders(order_no="PO-2026-05017").json())
        self.assertEqual(1, len(self.list_orders(order_no="PO-2026-06042").json()))
        old_task = self.client.get(
            f"/api/acceptance/tasks/{task['task_id']}",
            headers=self.auth_headers,
            params={"token": task["token"]},
        )
        old_oracle = self.client.get(
            "/api/eval/oracle/acceptance",
            headers=RESET_HEADERS,
            params={"task_id": task["task_id"]},
        )
        self.assertEqual(404, old_task.status_code)
        self.assertEqual(404, old_oracle.status_code)

    def test_unknown_profile_is_rejected_without_changing_default_reset(self):
        bad = self.reset("unknown")
        self.assertEqual(400, bad.status_code)

        default = self.reset()
        self.assertEqual(200, default.status_code)
        self.assertEqual("default", default.json()["profile"])
        legacy_orders = self.client.get(
            "/api/purchase-orders",
            headers=self.auth_headers,
        )
        self.assertEqual(200, legacy_orders.status_code)
        self.assertIn("PO-2026-RPA-001", [row["number"] for row in legacy_orders.json()])


if __name__ == "__main__":
    unittest.main()
