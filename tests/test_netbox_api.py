import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from netbox_api import DeviceTypes, NetBox


class FakeHandle:
    def __init__(self):
        self.logs = []
        self.verbose_logs = []

    def log(self, message):
        self.logs.append(str(message))

    def verbose_log(self, message):
        self.verbose_logs.append(str(message))


class FakeEndpoint:
    def __init__(self, records=None, create_result=None):
        self.records = records or []
        self.create_calls = []
        self.create_result = create_result

    def all(self):
        return list(self.records)

    def create(self, payload):
        self.create_calls.append(payload)
        return self.create_result


class NetBoxBehaviorTests(unittest.TestCase):
    def test_verify_compatibility_enables_new_filters_for_major_versions_above_four(self):
        handle = FakeHandle()
        netbox = NetBox.__new__(NetBox)
        netbox.netbox = SimpleNamespace(version="5.0.0")
        netbox.handle = handle
        netbox.modules = False
        netbox.new_filters = False

        netbox.verify_compatibility()

        self.assertTrue(netbox.modules)
        self.assertTrue(netbox.new_filters)
        self.assertTrue(any("Using new filters" in message for message in handle.logs))

    def test_create_device_types_keys_existing_records_by_manufacturer_and_model(self):
        handle = FakeHandle()
        created_record = SimpleNamespace(
            manufacturer=SimpleNamespace(name="Vendor B", slug="vendor-b"),
            model="SharedModel",
            id=42,
        )
        endpoint = FakeEndpoint(create_result=created_record)
        netbox = NetBox.__new__(NetBox)
        netbox.handle = handle
        netbox.counter = Counter()
        netbox.modules = False
        netbox.url = "https://netbox.example"
        netbox.token = "token"
        netbox.device_types = SimpleNamespace(
            existing_device_types={
                DeviceTypes.get_device_type_key("vendor-a", "SharedModel"): SimpleNamespace(
                    manufacturer=SimpleNamespace(name="Vendor A", slug="vendor-a"),
                    model="SharedModel",
                    id=1,
                )
            },
            get_device_type_key=DeviceTypes.get_device_type_key,
        )
        netbox.netbox = SimpleNamespace(dcim=SimpleNamespace(device_types=endpoint))

        payload = {
            "manufacturer": {"name": "Vendor B", "slug": "vendor-b"},
            "model": "SharedModel",
            "slug": "shared-model",
            "src": "/tmp/device.yml",
        }

        netbox.create_device_types([payload])

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual(endpoint.create_calls[0]["manufacturer"]["slug"], "vendor-b")
        self.assertEqual(netbox.counter["added"], 1)

    def test_upload_images_counts_only_successful_requests(self):
        handle = FakeHandle()
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False

        with tempfile.TemporaryDirectory() as tmpdir:
            front = Path(tmpdir) / "front.png"
            front.write_bytes(b"front")

            with patch("netbox_api.requests.patch", return_value=SimpleNamespace(ok=True, status_code=200, text="", __str__=lambda self: "200")) as patched_request:
                device_types.upload_images(
                    "https://netbox.example",
                    "token",
                    {"front_image": str(front)},
                    99,
                )

        self.assertEqual(device_types.counter["images"], 1)
        self.assertEqual(patched_request.call_count, 1)

    def test_upload_images_does_not_increment_counter_on_failure(self):
        handle = FakeHandle()
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False

        with tempfile.TemporaryDirectory() as tmpdir:
            rear = Path(tmpdir) / "rear.png"
            rear.write_bytes(b"rear")

            with patch("netbox_api.requests.patch", return_value=SimpleNamespace(ok=False, status_code=500, text="boom")):
                device_types.upload_images(
                    "https://netbox.example",
                    "token",
                    {"rear_image": str(rear)},
                    100,
                )

        self.assertEqual(device_types.counter["images"], 0)
        self.assertTrue(any("Failed to update images" in message for message in handle.logs))


if __name__ == "__main__":
    unittest.main()
