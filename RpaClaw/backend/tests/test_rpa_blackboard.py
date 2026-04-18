import unittest

from backend.rpa.blackboard import Blackboard, resolve_template


class BlackboardTests(unittest.TestCase):
    def test_resolves_nested_ref(self):
        board = Blackboard()
        board.write("selected_project", {"url": "https://github.com/a/b", "repo": "b"})

        self.assertEqual(board.resolve_ref("selected_project.url"), "https://github.com/a/b")

    def test_resolves_url_template_without_hardcoding_recorded_value(self):
        board = Blackboard(values={"selected_project": {"url": "https://github.com/a/b"}})

        self.assertEqual(
            resolve_template("{selected_project.url}/pulls", board),
            "https://github.com/a/b/pulls",
        )

    def test_missing_ref_raises_key_error_with_path(self):
        board = Blackboard(values={"selected_project": {}})

        with self.assertRaisesRegex(KeyError, "selected_project.url"):
            board.resolve_ref("selected_project.url")

    def test_runtime_params_can_initialize_blackboard_refs(self):
        board = Blackboard(runtime_params={"keyword": "SKILL"})

        self.assertEqual(board.resolve_ref("params.keyword"), "SKILL")


if __name__ == "__main__":
    unittest.main()
