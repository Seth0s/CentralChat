"""K.3 — cofre local JSON."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from app.shared.local_vault import migrate_legacy_vault_to_admin, read_vault_file, resolve_secret


class TestLocalVault(unittest.TestCase):
    def test_read_vault_allowlist_only(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "gemini_api_key": "  sk-test  ",
                        "ignored_key": "x",
                        "other": 1,
                    },
                    f,
                )
            d = read_vault_file(path)
            self.assertEqual(d, {"gemini_api_key": "sk-test"})
        finally:
            os.unlink(path)

    def test_resolve_secret_env_wins(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"gemini_api_key": "from-file"}, f)
            self.assertEqual(
                resolve_secret(env_value="from-env", vault_path=path, vault_key="gemini_api_key"),
                "from-env",
            )
            self.assertEqual(
                resolve_secret(env_value="", vault_path=path, vault_key="gemini_api_key"),
                "from-file",
            )
        finally:
            os.unlink(path)

    def test_missing_file(self) -> None:
        self.assertEqual(read_vault_file("/nonexistent/vault.json"), {})
        self.assertEqual(
            resolve_secret(env_value="", vault_path="/nonexistent/vault.json", vault_key="gemini_api_key"),
            "",
        )

    def test_resolve_secret_prefers_admin_provider(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "secrets").mkdir()
            secrets_path = root / "secrets" / "inference_providers.json"
            secrets_path.write_text(json.dumps({"google": "sk-from-admin"}), encoding="utf-8")
            fd, vault_path = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            try:
                with open(vault_path, "w", encoding="utf-8") as f:
                    json.dump({"gemini_api_key": "from-legacy"}, f)
                with patch("app.shared.inference_governance.CENTRAL_ROOT", str(root)):
                    with patch("app.config.CENTRAL_ROOT", str(root)):
                        with patch("app.shared.inference_governance.OPENROUTER_API_KEY", ""):
                            with patch("app.shared.inference_governance.CENTRAL_CLOUD_MODEL_ALLOWLIST", ()):
                                with patch.dict(os.environ, {}, clear=False):
                                    os.environ.pop("GOOGLE_API_KEY", None)
                                    import app.shared.inference_governance as ig
                                    from app.shared.secret_backends import reset_secret_backend_cache

                                    reset_secret_backend_cache()
                                    ig._migrated_legacy_vault = True
                                    self.assertEqual(
                                        resolve_secret(
                                            env_value="",
                                            vault_path=vault_path,
                                            vault_key="gemini_api_key",
                                        ),
                                        "sk-from-admin",
                                    )
            finally:
                os.unlink(vault_path)


if __name__ == "__main__":
    unittest.main()
