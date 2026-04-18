import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.rpa.skill_exporter import SkillExporter


class SkillExporterContractFilesTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_export_writes_extra_contract_files(self):
        output_dir = Path.cwd() / "RpaClaw" / "backend" / "tests" / "_tmp_skill_exporter"
        if output_dir.exists():
            shutil.rmtree(output_dir)

        try:
            with patch("backend.rpa.skill_exporter.settings.storage_backend", "local"), patch(
                "backend.rpa.skill_exporter.settings.external_skills_dir",
                str(output_dir),
            ):
                await SkillExporter().export_skill(
                    user_id="u1",
                    skill_name="contract_skill",
                    description="desc",
                    script="print('ok')",
                    params={},
                    extra_files={"skill.contract.json": "{}"},
                )

            self.assertTrue((output_dir / "contract_skill" / "skill.contract.json").exists())
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
