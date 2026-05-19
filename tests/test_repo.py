import tempfile
import unittest
from pathlib import Path

from repo import DTLRepo


class FakeHandle:
    def __init__(self):
        self.messages = []

    def verbose_log(self, message):
        self.messages.append(str(message))


class RepoParseFilesTests(unittest.TestCase):
    def setUp(self):
        self.repo = DTLRepo.__new__(DTLRepo)
        self.repo.handle = FakeHandle()

    def test_parse_files_skips_invalid_documents_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            valid = base / "valid.yaml"
            valid.write_text(
                "manufacturer: Juniper\nmodel: EX4300\nslug: ex4300\n",
                encoding="utf-8",
            )
            invalid = base / "invalid.yaml"
            invalid.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
            missing = base / "missing.yaml"
            missing.write_text("manufacturer: Cisco\nmodel: ISR\n", encoding="utf-8")

            parsed = self.repo.parse_files([str(valid), str(invalid), str(missing)])

            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["manufacturer"], {"name": "Juniper", "slug": "juniper"})
            self.assertEqual(parsed[0]["src"], str(valid))
            self.assertTrue(any("Skipping invalid YAML document" in message for message in self.repo.handle.messages))
            self.assertTrue(any("missing required fields" in message for message in self.repo.handle.messages))

    def test_parse_files_applies_slug_filters_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            matching = base / "matching.yaml"
            matching.write_text(
                "manufacturer: APC\nmodel: Smart-UPS\nslug: smart-ups-x\n",
                encoding="utf-8",
            )
            skipped = base / "skipped.yaml"
            skipped.write_text(
                "manufacturer: APC\nmodel: PDU\nslug: rack-pdu\n",
                encoding="utf-8",
            )

            parsed = self.repo.parse_files([str(matching), str(skipped)], slugs=["SMART-UPS"])

            self.assertEqual([item["model"] for item in parsed], ["Smart-UPS"])


if __name__ == "__main__":
    unittest.main()
