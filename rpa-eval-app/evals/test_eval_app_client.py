import json
import unittest
from unittest.mock import patch

from eval_app_client import EvalAppClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({"status": "reset"}).encode("utf-8")


class EvalAppClientTests(unittest.TestCase):
    def test_reset_omits_profile_query_by_default(self):
        requests = []

        def fake_urlopen(req, timeout):
            requests.append(req)
            return FakeResponse()

        with patch("eval_app_client.request.urlopen", side_effect=fake_urlopen):
            EvalAppClient("http://localhost:8085").reset("reset-token")

        self.assertEqual("http://localhost:8085/api/eval/reset", requests[0].full_url)

    def test_reset_url_encodes_optional_profile(self):
        requests = []

        def fake_urlopen(req, timeout):
            requests.append(req)
            return FakeResponse()

        with patch("eval_app_client.request.urlopen", side_effect=fake_urlopen):
            EvalAppClient("http://localhost:8085").reset("reset-token", profile="case_a")

        self.assertEqual(
            "http://localhost:8085/api/eval/reset?profile=case_a",
            requests[0].full_url,
        )


if __name__ == "__main__":
    unittest.main()
