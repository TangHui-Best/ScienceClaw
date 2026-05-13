import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


TEST_RESET_TOKEN = "eval-" + "test-" + "reset-" + "token"


class EvalAuthTokenTests(unittest.TestCase):
    def test_eval_auth_token_requires_reset_token(self):
        with patch.dict("os.environ", {"RPA_EVAL_RESET_TOKEN": TEST_RESET_TOKEN}):
            with TestClient(app) as client:
                response = client.post("/api/eval/auth-token", json={"username": "buyer"})

        self.assertEqual(403, response.status_code)

    def test_eval_auth_token_requires_configured_reset_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with TestClient(app) as client:
                response = client.post("/api/eval/auth-token", json={"username": "buyer"})

        self.assertEqual(503, response.status_code)

    def test_eval_auth_token_issues_token_for_fixture_user(self):
        with patch.dict("os.environ", {"RPA_EVAL_RESET_TOKEN": TEST_RESET_TOKEN}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/eval/auth-token",
                    headers={"X-RPA-Eval-Reset-Token": TEST_RESET_TOKEN},
                    json={"username": "buyer"},
                )
                payload = response.json()
                me_response = client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {payload['access_token']}"},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual("bearer", payload["token_type"])
        self.assertEqual("buyer", payload["user"]["username"])
        self.assertEqual(200, me_response.status_code)
        self.assertEqual("buyer", me_response.json()["username"])

    def test_reset_endpoint_accepts_configured_reset_token(self):
        with patch.dict("os.environ", {"RPA_EVAL_RESET_TOKEN": TEST_RESET_TOKEN}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/eval/reset",
                    headers={"X-RPA-Eval-Reset-Token": TEST_RESET_TOKEN},
                )

        self.assertEqual(200, response.status_code)
        self.assertEqual("reset", response.json()["status"])


if __name__ == "__main__":
    unittest.main()
