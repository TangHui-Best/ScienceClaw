import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.config import settings
from backend.rpa.skill_exporter import SkillExporter


class TestSkillExporter(unittest.IsolatedAsyncioTestCase):
    async def test_export_skill_writes_recorded_metadata_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = SkillExporter()
            steps = [
                {
                    "id": "step_1",
                    "action": "goto",
                    "description": "Open dashboard",
                    "url": "https://example.com/dashboard",
                    "frame_path": [],
                    "locator_candidates": [],
                    "validation": {"status": "ok", "details": ""},
                }
            ]
            params = {
                "query": {
                    "type": "string",
                    "description": "Search query",
                    "required": True,
                    "original_value": "",
                    "sensitive": False,
                    "credential_id": "",
                }
            }

            original_backend = settings.storage_backend
            original_dir = settings.external_skills_dir
            settings.storage_backend = "local"
            settings.external_skills_dir = temp_dir
            try:
                await exporter.export_skill(
                    user_id="user-1",
                    skill_name="recorded_search",
                    description="Recorded search flow",
                    script="print('ok')\n",
                    params=params,
                    steps=steps,
                )
            finally:
                settings.storage_backend = original_backend
                settings.external_skills_dir = original_dir

            skill_dir = Path(temp_dir) / "recorded_search"
            meta = json.loads((skill_dir / "skill.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "rpa-recording")
            self.assertEqual(meta["entry_script"], "skill.py")
            self.assertEqual(meta["steps"][0]["action"], "goto")
            self.assertIn("params.json", meta["artifacts"])

    async def test_export_skill_serializes_datetime_values_in_recorded_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = SkillExporter()
            steps = [
                {
                    "id": "step_1",
                    "action": "goto",
                    "description": "Open dashboard",
                    "timestamp": datetime(2026, 4, 24, 12, 0, 0),
                }
            ]

            original_backend = settings.storage_backend
            original_dir = settings.external_skills_dir
            settings.storage_backend = "local"
            settings.external_skills_dir = temp_dir
            try:
                await exporter.export_skill(
                    user_id="user-1",
                    skill_name="recorded_search",
                    description="Recorded search flow",
                    script="print('ok')\n",
                    params={},
                    steps=steps,
                )
            finally:
                settings.storage_backend = original_backend
                settings.external_skills_dir = original_dir

            skill_dir = Path(temp_dir) / "recorded_search"
            meta = json.loads((skill_dir / "skill.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["steps"][0]["timestamp"], "2026-04-24T12:00:00")

    async def test_export_skill_writes_trace_projection_without_legacy_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = SkillExporter()
            projected_steps = [
                {
                    "id": "trace-ai-select",
                    "action": "ai_script",
                    "description": "Select first project",
                    "rpa_trace": {
                        "trace_id": "trace-ai-select",
                        "trace_type": "ai_operation",
                    },
                }
            ]
            recording_meta = {
                "recording_source": "trace",
                "traces": [projected_steps[0]["rpa_trace"]],
                "runtime_results": {},
                "trace_diagnostics": [],
            }

            original_backend = settings.storage_backend
            original_dir = settings.external_skills_dir
            settings.storage_backend = "local"
            settings.external_skills_dir = temp_dir
            try:
                await exporter.export_skill(
                    user_id="user-1",
                    skill_name="trace_projector",
                    description="Trace projector",
                    script="print('ok')\n",
                    params={},
                    recording_meta=recording_meta,
                    steps=projected_steps,
                )
            finally:
                settings.storage_backend = original_backend
                settings.external_skills_dir = original_dir

            skill_dir = Path(temp_dir) / "trace_projector"
            meta = json.loads((skill_dir / "skill.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["steps"], projected_steps)
            self.assertEqual(meta["mcp_steps"], projected_steps)
            self.assertNotIn("legacy_steps", meta["recording"])


if __name__ == "__main__":
    unittest.main()
