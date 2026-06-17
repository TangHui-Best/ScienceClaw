import os
import tempfile
import unittest
from pathlib import Path

from backend.config import settings
from backend.credential import vault as vault_module


class CredentialVaultKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        self.home_dir = Path(self._tmpdir.name) / "home"
        self.home_dir.mkdir()
        self.cwd_dir = Path(self._tmpdir.name) / "cwd"
        self.cwd_dir.mkdir()

        self._original_cwd = Path.cwd()
        os.chdir(self.cwd_dir)
        self.addCleanup(self._restore_cwd)

        self._original_home = settings.rpa_claw_home
        self._original_key = settings.credential_key
        settings.rpa_claw_home = str(self.home_dir)
        settings.credential_key = ""
        self.addCleanup(self._restore_settings)

        self._original_env_key = os.environ.get("CREDENTIAL_KEY")
        os.environ.pop("CREDENTIAL_KEY", None)
        self.addCleanup(self._restore_env)

        vault_module._vault = None
        self.addCleanup(self._reset_cached_vault)

    def _restore_cwd(self) -> None:
        os.chdir(self._original_cwd)

    def _restore_settings(self) -> None:
        settings.rpa_claw_home = self._original_home
        settings.credential_key = self._original_key

    def _restore_env(self) -> None:
        if self._original_env_key is None:
            os.environ.pop("CREDENTIAL_KEY", None)
        else:
            os.environ["CREDENTIAL_KEY"] = self._original_env_key

    @staticmethod
    def _reset_cached_vault() -> None:
        vault_module._vault = None

    def test_loads_existing_key_from_home_env_before_generating(self) -> None:
        existing_key = "ab" * 32
        env_path = self.home_dir / ".env"
        env_path.write_text(f"CREDENTIAL_KEY={existing_key}\n", encoding="utf-8")

        vault_module.CredentialVault()

        self.assertEqual(settings.credential_key, existing_key)
        self.assertEqual(os.environ.get("CREDENTIAL_KEY"), existing_key)
        self.assertFalse((self.cwd_dir / ".env").exists())

    def test_generates_new_key_in_home_env_file(self) -> None:
        vault_module.CredentialVault()

        env_path = self.home_dir / ".env"
        self.assertTrue(env_path.exists())
        env_content = env_path.read_text(encoding="utf-8")
        self.assertIn(f"CREDENTIAL_KEY={settings.credential_key}", env_content)
        self.assertFalse((self.cwd_dir / ".env").exists())
