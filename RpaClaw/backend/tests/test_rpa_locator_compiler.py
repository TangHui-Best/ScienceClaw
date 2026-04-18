import unittest

from backend.rpa.locator_compiler import (
    LocatorCompiler,
    LocatorCompileError,
    is_stable_locator_payload,
)


class LocatorCompilerTests(unittest.TestCase):
    def test_role_name_locator_wins_over_random_css_id(self):
        compiler = LocatorCompiler()
        payload = compiler.compile_node(
            {
                "role": "button",
                "name": "Save changes",
                "locator": {"method": "css", "value": "#button-172993"},
            }
        )

        self.assertEqual(
            payload,
            {"method": "role", "role": "button", "name": "Save changes", "exact": False},
        )

    def test_exact_href_is_used_for_navigation_link_not_broad_contains(self):
        compiler = LocatorCompiler()
        payload = compiler.compile_node(
            {
                "role": "link",
                "name": "SimoneAvogadro / android-reverse-engineering-skill",
                "href": "/SimoneAvogadro/android-reverse-engineering-skill",
            }
        )

        self.assertEqual(
            payload,
            {
                "method": "css",
                "value": 'a[href="/SimoneAvogadro/android-reverse-engineering-skill"]',
            },
        )
        self.assertNotIn("*=", payload["value"])

    def test_scoped_collection_item_locator_is_nested(self):
        compiler = LocatorCompiler()

        payload = compiler.compile_scoped(
            parent={"method": "css", "value": "article.Box-row"},
            child={"role": "link", "name": "Pull requests", "exact": False},
        )

        self.assertEqual(payload["method"], "nested")
        self.assertEqual(payload["parent"]["value"], "article.Box-row")
        self.assertEqual(payload["child"]["role"], "link")

    def test_rejects_broad_href_contains_and_random_ids(self):
        self.assertFalse(
            is_stable_locator_payload(
                {"method": "css", "value": 'a[href*="owner/repo"]'}
            )
        )
        self.assertFalse(
            is_stable_locator_payload({"method": "css", "value": "#input-172993"})
        )

    def test_raises_when_no_stable_locator_can_be_compiled(self):
        compiler = LocatorCompiler()

        with self.assertRaises(LocatorCompileError):
            compiler.compile_node({"locator": {"method": "css", "value": "#input-172993"}})


if __name__ == "__main__":
    unittest.main()
