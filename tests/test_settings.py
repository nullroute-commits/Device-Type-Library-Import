import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class SettingsTests(unittest.TestCase):
    def load_settings(self, env):
        previous_argv = list(sys.argv)
        try:
            sys.argv = ["settings.py"]
            with patch.dict(os.environ, env, clear=True):
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

    def test_exclusion_filters_accept_env_values(self):
        settings = self.load_settings(
            {
                "NETBOX_URL": "https://netbox.example",
                "NETBOX_TOKEN": "token",
                "EXCLUDE_OBJECT_TYPES": "interfaces,module-types images",
                "EXCLUDE_OBJECTS": "device-types:EX4300 mgmt0,module-types:line-card",
            }
        )

        self.assertEqual(
            settings.args.exclude_object_types,
            ["interfaces", "module-types", "images"],
        )
        self.assertEqual(
            settings.args.exclude_objects,
            ["device-types:EX4300", "mgmt0", "module-types:line-card"],
        )

    def test_exclusion_filters_strip_whitespace_after_commas(self):
        previous_argv = list(sys.argv)
        try:
            sys.argv = [
                "settings.py",
                "--exclude-object-types",
                "interfaces, module-types",
                "--exclude-objects",
                "device-types:EX4300, mgmt0",
            ]
            with patch.dict(
                os.environ,
                {"NETBOX_URL": "https://netbox.example", "NETBOX_TOKEN": "token"},
                clear=True,
            ):
                sys.modules.pop("settings", None)
                import settings
                settings = importlib.reload(settings)
        finally:
            sys.argv = previous_argv

        self.assertEqual(settings.args.exclude_object_types, ["interfaces", "module-types"])
        self.assertEqual(settings.args.exclude_objects, ["device-types:EX4300", "mgmt0"])

    def test_exclusion_filters_accept_space_separated_env_values(self):
        settings = self.load_settings(
            {
                "NETBOX_URL": "https://netbox.example",
                "NETBOX_TOKEN": "token",
                "EXCLUDE_OBJECT_TYPES": "interfaces module-types images",
                "EXCLUDE_OBJECTS": "device-types:EX4300 mgmt0",
            }
        )

        self.assertEqual(
            settings.args.exclude_object_types,
            ["interfaces", "module-types", "images"],
        )
        self.assertEqual(settings.args.exclude_objects, ["device-types:EX4300", "mgmt0"])


if __name__ == "__main__":
    unittest.main()
