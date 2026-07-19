import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


RESET_TOKEN = "task9-reset-token"
ORACLE_TOKEN = "task9-oracle-token"
ENV = {
    "RPA_EVAL_RESET_TOKEN": RESET_TOKEN,
    "RPA_EVAL_ORACLE_TOKEN": ORACLE_TOKEN,
}


def contains_key(value: object, forbidden_key: str) -> bool:
    if isinstance(value, dict):
        return forbidden_key in value or any(
            contains_key(child, forbidden_key) for child in value.values()
        )
    if isinstance(value, list):
        return any(contains_key(child, forbidden_key) for child in value)
    return False


class AcceptanceE2EContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(os.environ, ENV, clear=False)
        self.env_patch.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env_patch.stop()

    def reset(self, profile: str) -> dict:
        response = self.client.post(
            f"/api/e2e/reset/{profile}",
            headers={"X-RPA-Eval-Reset-Token": RESET_TOKEN},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def orders(self) -> list[dict]:
        response = self.client.get("/api/e2e/system-a/orders")
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def start_task(self, order_no: str) -> dict:
        response = self.client.post(
            "/api/e2e/acceptance-tasks",
            json={"order_no": order_no},
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def submit_record(self, task: dict, **overrides: object):
        task_response = self.client.get(
            f"/api/e2e/acceptance-tasks/{task['task_id']}",
            params={"token": task["token"]},
        )
        self.assertEqual(200, task_response.status_code, task_response.text)
        source = task_response.json()["source_order"]
        payload = {
            "order_no": source["order_no"],
            "supplier_name": source["supplier_name"],
            "contract_no": source["contract_no"],
            "amount": source["amount"],
            "currency": source["currency"],
            "order_date": source["order_date"],
            "description": "自动创建",
            "confirmed": True,
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/e2e/acceptance-tasks/{task['task_id']}/records",
            params={"token": task["token"]},
            json=payload,
        )

    def oracle(self, task_id: str, token: str | None = ORACLE_TOKEN):
        headers = {} if token is None else {"X-RPA-Eval-Oracle-Token": token}
        return self.client.get(f"/api/e2e/oracle/{task_id}", headers=headers)

    def test_profile_a_has_target_first_with_three_same_action_rows(self):
        reset = self.reset("A")
        orders = self.orders()

        self.assertEqual("A", reset["profile"])
        self.assertGreaterEqual(len(orders), 3)
        self.assertEqual("PO-2026-05017", orders[0]["order_no"])
        self.assertEqual("设备采购", orders[0]["business_type"])
        self.assertEqual("华东精密设备有限公司", orders[0]["supplier_name"])
        self.assertEqual("CT-2026-0088", orders[0]["contract_no"])
        self.assertEqual(Decimal("128600.50"), Decimal(orders[0]["amount"]))
        self.assertEqual("CNY", orders[0]["currency"])
        self.assertEqual("2026-05-16", orders[0]["order_date"])
        self.assertTrue(all(row["action_label"] == "发起验收" for row in orders))

    def test_profile_b_has_different_target_third_and_distractor_rows(self):
        self.reset("B")
        orders = self.orders()

        self.assertGreaterEqual(len(orders), 3)
        self.assertNotEqual("PO-2026-06042", orders[0]["order_no"])
        self.assertEqual("PO-2026-06042", orders[2]["order_no"])
        self.assertEqual("服务采购", orders[2]["business_type"])
        self.assertEqual("北辰数字技术有限公司", orders[2]["supplier_name"])
        self.assertEqual("CT-2026-0116", orders[2]["contract_no"])
        self.assertEqual(Decimal("10150.75"), Decimal(orders[2]["amount"]))
        self.assertEqual("USD", orders[2]["currency"])
        self.assertEqual("2026-06-08", orders[2]["order_date"])
        self.assertEqual(len(orders), len({row["order_no"] for row in orders}))

    def test_query_conditions_match_target_but_preserve_distractor_rows(self):
        self.reset("B")
        response = self.client.get(
            "/api/e2e/system-a/orders",
            params={
                "business_type": "服务采购",
                "date_from": "2026-06-01",
                "date_to": "2026-06-30",
                "supplier_name": "北辰数字技术有限公司",
                "order_no": "PO-2026-06042",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(3, len(response.json()))
        self.assertEqual("PO-2026-06042", response.json()[2]["order_no"])

        no_match = self.client.get(
            "/api/e2e/system-a/orders",
            params={"date_from": "2030-01-01"},
        )
        self.assertEqual([], no_match.json())

    def test_reset_profiles_are_parameterized_and_do_not_share_records(self):
        self.reset("A")
        task_a = self.start_task("PO-2026-05017")
        self.assertEqual(201, self.submit_record(task_a).status_code)
        self.assertTrue(self.oracle(task_a["task_id"]).json()["passed"])

        self.reset("B")
        task_b = self.start_task("PO-2026-06042")
        self.assertEqual(201, self.submit_record(task_b).status_code)
        oracle_b = self.oracle(task_b["task_id"])
        self.assertEqual(200, oracle_b.status_code, oracle_b.text)
        self.assertTrue(oracle_b.json()["passed"])
        self.assertEqual("B", oracle_b.json()["profile"])
        self.assertEqual("PO-2026-06042", oracle_b.json()["actual"]["order_no"])
        self.assertNotIn("PO-2026-05017", oracle_b.text)
        self.assertEqual(404, self.oracle(task_a["task_id"]).status_code)

    def test_profile_a_wrong_row_task_can_never_pass_oracle(self):
        self.reset("A")
        wrong_task = self.start_task("PO-2026-05031")
        self.assertEqual(201, self.submit_record(wrong_task).status_code)

        payload = self.oracle(wrong_task["task_id"]).json()
        self.assertFalse(payload["passed"])
        self.assertIn("target_order", payload["mismatches"])
        self.assertEqual("PO-2026-05017", payload["target_order_no"])
        self.assertEqual("PO-2026-05031", payload["selected_order_no"])

    def test_profile_b_first_row_task_can_never_pass_oracle(self):
        self.reset("B")
        wrong_task = self.start_task("PO-2026-06011")
        self.assertEqual(
            201,
            self.submit_record(
                wrong_task,
                order_no="PO-2026-06042",
                supplier_name="北辰数字技术有限公司",
                contract_no="CT-2026-0116",
                amount="10150.75",
                currency="USD",
                order_date="2026-06-08",
            ).status_code,
        )

        payload = self.oracle(wrong_task["task_id"]).json()
        self.assertFalse(payload["passed"])
        self.assertEqual(["target_order"], payload["mismatches"])
        self.assertEqual("PO-2026-06042", payload["target_order_no"])
        self.assertEqual("PO-2026-06011", payload["selected_order_no"])

    def test_each_start_creates_random_task_token_and_url_bound_to_source(self):
        self.reset("A")
        first = self.start_task("PO-2026-05017")
        second = self.start_task("PO-2026-05017")

        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertNotEqual(first["token"], second["token"])
        self.assertNotEqual(first["url"], second["url"])
        self.assertIn(first["task_id"], first["url"])
        self.assertIn(first["token"], first["url"])
        self.assertEqual("A", first["profile"])
        self.assertEqual("PO-2026-05017", first["order_no"])
        self.assertFalse(contains_key(first, "oracle_token"))
        self.assertNotIn(ORACLE_TOKEN, str(first))

        invalid = self.client.get(
            f"/api/e2e/acceptance-tasks/{first['task_id']}",
            params={"token": second["token"]},
        )
        self.assertEqual(403, invalid.status_code)

    def test_start_rejects_unknown_order_and_task_api_never_exposes_oracle_secret(self):
        self.reset("A")
        missing = self.client.post(
            "/api/e2e/acceptance-tasks",
            json={"order_no": "PO-NOT-FOUND"},
        )
        self.assertEqual(404, missing.status_code)

        task = self.start_task("PO-2026-05017")
        response = self.client.get(
            f"/api/e2e/acceptance-tasks/{task['task_id']}",
            params={"token": task["token"]},
        )
        self.assertEqual(200, response.status_code)
        self.assertFalse(contains_key(response.json(), "oracle_token"))
        self.assertNotIn(ORACLE_TOKEN, response.text)

    def test_oracle_requires_independent_configured_header(self):
        self.reset("A")
        task = self.start_task("PO-2026-05017")

        self.assertEqual(403, self.oracle(task["task_id"], None).status_code)
        self.assertEqual(403, self.oracle(task["task_id"], "wrong-token").status_code)
        with patch.dict(os.environ, {"RPA_EVAL_ORACLE_TOKEN": ""}, clear=False):
            self.assertEqual(503, self.oracle(task["task_id"]).status_code)

    def test_oracle_reads_database_and_compares_every_field_exactly(self):
        self.reset("A")
        task = self.start_task("PO-2026-05017")
        save = self.submit_record(task)

        self.assertEqual(201, save.status_code, save.text)
        oracle = self.oracle(task["task_id"])
        self.assertEqual(200, oracle.status_code, oracle.text)
        payload = oracle.json()
        self.assertTrue(payload["passed"], payload)
        self.assertEqual([], payload["mismatches"])
        self.assertEqual(1, payload["record_count"])
        self.assertEqual(
            {
                "order_no",
                "supplier_name",
                "contract_no",
                "amount",
                "currency",
                "order_date",
                "description",
                "confirmed",
            },
            set(payload["actual"]),
        )
        self.assertEqual(Decimal("128600.50"), Decimal(payload["actual"]["amount"]))

        duplicate = self.submit_record(task)
        self.assertEqual(409, duplicate.status_code)

    def test_oracle_rejects_page_success_when_persisted_business_value_is_wrong(self):
        self.reset("B")
        task = self.start_task("PO-2026-06042")
        save = self.submit_record(task, amount="10150.76")
        self.assertEqual(201, save.status_code, save.text)

        payload = self.oracle(task["task_id"]).json()
        self.assertFalse(payload["passed"])
        self.assertEqual(1, payload["record_count"])
        self.assertIn("amount", payload["mismatches"])
        self.assertEqual("10150.76", payload["actual"]["amount"])

    def test_oracle_reports_each_individual_business_field_mismatch(self):
        cases = {
            "order_no": "PO-WRONG",
            "supplier_name": "错误供应商",
            "contract_no": "CT-WRONG",
            "amount": "128600.51",
            "currency": "USD",
            "order_date": "2026-05-17",
            "description": "人工创建",
            "confirmed": False,
        }
        for field, wrong_value in cases.items():
            with self.subTest(field=field):
                self.reset("A")
                task = self.start_task("PO-2026-05017")
                self.assertEqual(201, self.submit_record(task, **{field: wrong_value}).status_code)
                payload = self.oracle(task["task_id"]).json()
                self.assertFalse(payload["passed"])
                self.assertIn(field, payload["mismatches"])


if __name__ == "__main__":
    unittest.main()
