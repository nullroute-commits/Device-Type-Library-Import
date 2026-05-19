import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from netbox_api import DeviceTypes, ImportFilters, NetBox


class FakeHandle:
    def __init__(self):
        self.logs = []
        self.verbose_logs = []

    def log(self, message):
        self.logs.append(str(message))

    def verbose_log(self, message):
        self.verbose_logs.append(str(message))

    def log_device_ports_created(self, created_ports=None, port_type="port"):
        return len(created_ports or [])

    def log_module_ports_created(self, created_ports=None, port_type="port"):
        return len(created_ports or [])


class FakeEndpoint:
    def __init__(self, records=None, create_result=None, filter_records=None):
        self.records = records or []
        self.create_calls = []
        self.create_result = create_result
        self.filter_calls = []
        self.filter_records = filter_records or []

    def all(self):
        return list(self.records)

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        return list(self.filter_records)

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
        netbox.import_filters = ImportFilters(handle)
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

    def test_create_device_types_skips_excluded_device_type_objects(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint()
        netbox = NetBox.__new__(NetBox)
        netbox.handle = handle
        netbox.counter = Counter()
        netbox.modules = False
        netbox.url = "https://netbox.example"
        netbox.token = "token"
        netbox.import_filters = ImportFilters(handle, excluded_objects=["device-types:shared-model"])
        netbox.device_types = SimpleNamespace(
            existing_device_types={},
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

        self.assertEqual(endpoint.create_calls, [])
        self.assertEqual(netbox.counter["added"], 0)

    def test_create_device_types_scopes_exclusions_by_manufacturer(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint(
            create_result=SimpleNamespace(
                manufacturer=SimpleNamespace(name="Vendor B", slug="vendor-b"),
                model="SharedModel",
                id=42,
            )
        )
        netbox = NetBox.__new__(NetBox)
        netbox.handle = handle
        netbox.counter = Counter()
        netbox.modules = False
        netbox.url = "https://netbox.example"
        netbox.token = "token"
        netbox.import_filters = ImportFilters(
            handle,
            excluded_objects=["device-types:vendor-a:shared-model"],
        )
        netbox.device_types = SimpleNamespace(
            existing_device_types={},
            get_device_type_key=DeviceTypes.get_device_type_key,
        )
        netbox.netbox = SimpleNamespace(dcim=SimpleNamespace(device_types=endpoint))

        netbox.create_device_types(
            [
                {
                    "manufacturer": {"name": "Vendor A", "slug": "vendor-a"},
                    "model": "SharedModel",
                    "slug": "shared-model",
                    "src": "/tmp/device-a.yml",
                },
                {
                    "manufacturer": {"name": "Vendor B", "slug": "vendor-b"},
                    "model": "SharedModel",
                    "slug": "shared-model",
                    "src": "/tmp/device-b.yml",
                },
            ]
        )

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual(endpoint.create_calls[0]["manufacturer"]["slug"], "vendor-b")

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

    def test_create_interfaces_skips_excluded_object_types(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint(create_result=[])
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False
        device_types.new_filters = False
        device_types.import_filters = ImportFilters(handle, excluded_object_types=["interfaces"])
        device_types.netbox = SimpleNamespace(dcim=SimpleNamespace(interface_templates=endpoint))

        device_types.create_interfaces([{"name": "mgmt0", "type": "1000base-t"}], 1)

        self.assertEqual(endpoint.filter_calls, [])
        self.assertEqual(endpoint.create_calls, [])

    def test_create_interfaces_skips_scoped_excluded_objects(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint(create_result=[], filter_records=[])
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False
        device_types.new_filters = False
        device_types.import_filters = ImportFilters(handle, excluded_objects=["interfaces:mgmt0"])
        device_types.netbox = SimpleNamespace(dcim=SimpleNamespace(interface_templates=endpoint))

        device_types.create_interfaces(
            [
                {"name": "mgmt0", "type": "1000base-t"},
                {"name": "xe-0/0/0", "type": "10gbase-x-sfpp"},
            ],
            1,
        )

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual([item["name"] for item in endpoint.create_calls[0]], ["xe-0/0/0"])

    def test_create_interfaces_skips_unscoped_excluded_objects(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint(create_result=[], filter_records=[])
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False
        device_types.new_filters = False
        device_types.import_filters = ImportFilters(handle, excluded_objects=["mgmt0"])
        device_types.netbox = SimpleNamespace(dcim=SimpleNamespace(interface_templates=endpoint))

        device_types.create_interfaces(
            [
                {"name": "mgmt0", "type": "1000base-t"},
                {"name": "xe-0/0/0", "type": "10gbase-x-sfpp"},
            ],
            1,
        )

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual([item["name"] for item in endpoint.create_calls[0]], ["xe-0/0/0"])

    def test_create_interfaces_scopes_exclusions_by_manufacturer(self):
        handle = FakeHandle()
        endpoint = FakeEndpoint(create_result=[], filter_records=[])
        device_types = DeviceTypes.__new__(DeviceTypes)
        device_types.handle = handle
        device_types.counter = Counter()
        device_types.ignore_ssl = False
        device_types.new_filters = False
        device_types.import_filters = ImportFilters(handle, excluded_objects=["interfaces:vendor-a:mgmt0"])
        device_types.netbox = SimpleNamespace(dcim=SimpleNamespace(interface_templates=endpoint))

        device_types.create_interfaces(
            [
                {"name": "mgmt0", "type": "1000base-t"},
                {"name": "xe-0/0/0", "type": "10gbase-x-sfpp"},
            ],
            1,
            manufacturer={"name": "Vendor A", "slug": "vendor-a"},
        )

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual([item["name"] for item in endpoint.create_calls[0]], ["xe-0/0/0"])

        endpoint.create_calls.clear()

        device_types.create_interfaces(
            [
                {"name": "mgmt0", "type": "1000base-t"},
                {"name": "xe-0/0/0", "type": "10gbase-x-sfpp"},
            ],
            1,
            manufacturer={"name": "Vendor B", "slug": "vendor-b"},
        )

        self.assertEqual(len(endpoint.create_calls), 1)
        self.assertEqual(
            [item["name"] for item in endpoint.create_calls[0]],
            ["mgmt0", "xe-0/0/0"],
        )

    def test_import_filters_support_manufacturer_only_scope(self):
        handle = FakeHandle()
        import_filters = ImportFilters(handle, excluded_objects=["vendor-a:mgmt0"])

        self.assertTrue(
            import_filters.is_object_excluded(
                "interfaces",
                "mgmt0",
                manufacturer={"name": "Vendor A", "slug": "vendor-a"},
            )
        )
        self.assertFalse(
            import_filters.is_object_excluded(
                "interfaces",
                "mgmt0",
                manufacturer={"name": "Vendor B", "slug": "vendor-b"},
            )
        )


if __name__ == "__main__":
    unittest.main()
