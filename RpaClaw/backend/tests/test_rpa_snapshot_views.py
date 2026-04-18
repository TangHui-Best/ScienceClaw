import unittest

from backend.rpa.snapshot_views import BaseSnapshot, build_base_snapshot_from_legacy


class SnapshotViewTests(unittest.TestCase):
    def test_builds_action_and_extraction_views_from_legacy_snapshot(self):
        legacy = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "actionable_nodes": [
                {
                    "id": "n1",
                    "role": "link",
                    "name": "Repo A",
                    "href": "/a/repo",
                    "is_visible": True,
                }
            ],
            "content_nodes": [{"id": "c1", "text": "Repo description"}],
            "containers": [
                {
                    "id": "box1",
                    "container_kind": "repo_card",
                    "child_actionable_ids": ["n1"],
                }
            ],
            "frames": [
                {
                    "frame_path": [],
                    "collections": [
                        {"kind": "repo_cards", "items": [{"name": "Repo A"}]}
                    ],
                }
            ],
        }

        snapshot = build_base_snapshot_from_legacy(legacy)

        self.assertIsInstance(snapshot, BaseSnapshot)
        self.assertEqual(snapshot.url, "https://github.com/trending")
        self.assertEqual(snapshot.action_view()["nodes"][0]["name"], "Repo A")
        self.assertEqual(
            snapshot.extraction_view()["collections"][0]["kind"],
            "repo_cards",
        )

    def test_views_include_truncation_metadata_when_budget_is_exceeded(self):
        legacy = {
            "url": "x",
            "title": "x",
            "actionable_nodes": [
                {"id": str(i), "role": "link", "name": f"Link {i}"}
                for i in range(130)
            ],
        }

        snapshot = build_base_snapshot_from_legacy(legacy)
        view = snapshot.action_view(max_nodes=10)

        self.assertEqual(len(view["nodes"]), 10)
        self.assertTrue(view["truncated"])

    def test_semantic_view_preserves_context_without_dumping_every_node(self):
        legacy = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "content_nodes": [
                {"id": str(i), "text": f"Repository description {i}"}
                for i in range(40)
            ],
            "containers": [
                {"id": "repo-1", "container_kind": "repo_card", "text": "Repo A"}
            ],
        }

        snapshot = build_base_snapshot_from_legacy(legacy)
        view = snapshot.semantic_view(max_content_nodes=5)

        self.assertEqual(view["url"], "https://github.com/trending")
        self.assertEqual(len(view["content_nodes"]), 5)
        self.assertTrue(view["truncated"])


if __name__ == "__main__":
    unittest.main()
