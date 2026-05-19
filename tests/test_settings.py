import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock


REPO_ROOT = "/home/runner/work/Device-Type-Library-Import/Device-Type-Library-Import"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class SettingsTests(unittest.TestCase):
    def load_settings(self, env):
        previous_argv = list(sys.argv)
        try:
            sys.argv = ["settings.py"]
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                sys.modules.pop("settings", None)
                import settings
                return importlib.reload(settings)
        finally:
            sys.argv = previous_argv

    def test_validate_environment_only_requires_netbox_values(self):
        settings = self.load_settings(
            {
                "NETBOX_URL": "https://netbox.example",
                "NETBOX_TOKEN": "token",
            }
        )

        exception_handler = MagicMock()
        settings.validate_environment(exception_handler)

        exception_handler.exception.assert_not_called()

    def test_validate_environment_reports_missing_required_value(self):
        settings = self.load_settings(
            {
                "NETBOX_URL": "https://netbox.example",
            }
        )

        exception_handler = MagicMock()
        settings.validate_environment(exception_handler)

        exception_handler.exception.assert_called_once()
        self.assertEqual(exception_handler.exception.call_args[0][1], "NETBOX_TOKEN")


if __name__ == "__main__":
    unittest.main()
