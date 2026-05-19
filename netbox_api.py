from collections import Counter
from contextlib import ExitStack
import pynetbox
import requests
import os
import glob
# from pynetbox import RequestError as APIRequestError


class ImportFilters:
    OBJECT_TYPE_ALIASES = {
        "device-type": "device-types",
        "device-types": "device-types",
        "module-type": "module-types",
        "module-types": "module-types",
        "interface": "interfaces",
        "interfaces": "interfaces",
        "power-port": "power-ports",
        "power-ports": "power-ports",
        "console-port": "console-ports",
        "console-ports": "console-ports",
        "power-outlet": "power-outlets",
        "power-outlets": "power-outlets",
        "console-server-port": "console-server-ports",
        "console-server-ports": "console-server-ports",
        "rear-port": "rear-ports",
        "rear-ports": "rear-ports",
        "front-port": "front-ports",
        "front-ports": "front-ports",
        "device-bay": "device-bays",
        "device-bays": "device-bays",
        "module-bay": "module-bays",
        "module-bays": "module-bays",
        "image": "images",
        "images": "images",
        "front-image": "images",
        "rear-image": "images",
    }

    def __init__(self, handle, excluded_object_types=None, excluded_objects=None):
        self.handle = handle
        self.excluded_object_types = {
            canonical
            for object_type in (excluded_object_types or [])
            if (canonical := self.canonical_object_type(object_type))
        }
        self.excluded_objects = set()
        self.excluded_objects_by_type = {}
        self.excluded_objects_by_manufacturer = {}
        self.excluded_objects_by_type_and_manufacturer = {}

        for excluded_object in excluded_objects or []:
            self.add_excluded_object(excluded_object)

    @classmethod
    def normalize_identifier(cls, value):
        if value is None:
            return ""
        return str(value).strip().casefold()

    @classmethod
    def canonical_object_type(cls, value):
        normalized = cls.normalize_identifier(value).replace("_", "-").replace(" ", "-").strip("-")
        return cls.OBJECT_TYPE_ALIASES.get(normalized, normalized)

    def add_excluded_object(self, value):
        normalized = self.normalize_identifier(value)
        if not normalized:
            return

        parts = [part.strip() for part in normalized.split(":") if part.strip()]
        if not parts:
            return

        if len(parts) >= 3:
            canonical_object_type = self.canonical_object_type(parts[0])
            if canonical_object_type in self.OBJECT_TYPE_ALIASES.values():
                manufacturer = parts[1]
                identifier = ":".join(parts[2:])
                self.excluded_objects_by_type_and_manufacturer.setdefault(
                    canonical_object_type,
                    {},
                ).setdefault(manufacturer, set()).add(identifier)
                return

        if len(parts) >= 2:
            canonical_object_type = self.canonical_object_type(parts[0])
            identifier = ":".join(parts[1:])
            if canonical_object_type in self.OBJECT_TYPE_ALIASES.values():
                self.excluded_objects_by_type.setdefault(canonical_object_type, set()).add(identifier)
                return

            manufacturer = parts[0]
            self.excluded_objects_by_manufacturer.setdefault(manufacturer, set()).add(identifier)
            return

        self.excluded_objects.add(normalized)

    def is_object_type_excluded(self, object_type):
        return self.canonical_object_type(object_type) in self.excluded_object_types

    @classmethod
    def manufacturer_identifiers(cls, manufacturer):
        if not manufacturer:
            return ()

        if isinstance(manufacturer, dict):
            return tuple(
                normalized
                for value in (manufacturer.get("slug"), manufacturer.get("name"))
                if (normalized := cls.normalize_identifier(value))
            )

        return tuple(
            normalized
            for normalized in (cls.normalize_identifier(manufacturer),)
            if normalized
        )

    def is_object_excluded(self, object_type, *identifiers, manufacturer=None):
        typed_identifiers = self.excluded_objects_by_type.get(self.canonical_object_type(object_type), set())
        manufacturer_identifiers = self.manufacturer_identifiers(manufacturer)
        manufacturer_scoped_identifiers = set()
        typed_manufacturer_scoped_identifiers = set()

        for manufacturer_identifier in manufacturer_identifiers:
            manufacturer_scoped_identifiers.update(
                self.excluded_objects_by_manufacturer.get(manufacturer_identifier, set())
            )
            typed_manufacturer_scoped_identifiers.update(
                self.excluded_objects_by_type_and_manufacturer.get(
                    self.canonical_object_type(object_type),
                    {},
                ).get(manufacturer_identifier, set())
            )

        for identifier in identifiers:
            normalized = self.normalize_identifier(identifier)
            if normalized and (
                normalized in self.excluded_objects
                or normalized in typed_identifiers
                or normalized in manufacturer_scoped_identifiers
                or normalized in typed_manufacturer_scoped_identifiers
            ):
                return True
        return False

    def filter_objects(self, object_type, objects, manufacturer=None):
        if self.is_object_type_excluded(object_type):
            self.handle.verbose_log(f"Skipping object type due to exclusion filter: {object_type}")
            return []

        filtered_objects = []
        for object_definition in objects:
            identifiers = (
                object_definition.get("name"),
                object_definition.get("label"),
                object_definition.get("slug"),
                object_definition.get("model"),
            )
            if self.is_object_excluded(object_type, *identifiers, manufacturer=manufacturer):
                object_name = next((identifier for identifier in identifiers if identifier), object_definition)
                self.handle.verbose_log(
                    f"Skipping {object_type} object due to exclusion filter: {object_name}"
                )
                continue
            filtered_objects.append(object_definition)

        return filtered_objects

class NetBox:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, settings):
        self.counter = Counter(
            added=0,
            updated=0,
            manufacturer=0,
            module_added=0,
            module_port_added=0,
            images=0,
        )
        self.url = settings.NETBOX_URL
        self.token = settings.NETBOX_TOKEN
        self.handle = settings.handle
        self.netbox = None
        self.ignore_ssl = settings.IGNORE_SSL_ERRORS
        self.modules = False
        self.new_filters = False
        self.import_filters = ImportFilters(
            self.handle,
            getattr(settings.args, "exclude_object_types", []),
            getattr(settings.args, "exclude_objects", []),
        )
        self.connect_api()
        self.verify_compatibility()
        self.existing_manufacturers = self.get_manufacturers()
        self.device_types = DeviceTypes(
            self.netbox,
            self.handle,
            self.counter,
            self.ignore_ssl,
            self.new_filters,
            self.import_filters,
        )

    def connect_api(self):
        try:
            self.netbox = pynetbox.api(self.url, token=self.token)
            if self.ignore_ssl:
                self.handle.verbose_log("IGNORE_SSL_ERRORS is True, catching exception and disabling SSL verification.")
                #requests.packages.urllib3.disable_warnings()
                self.netbox.http_session.verify = False
        except Exception as e:
            self.handle.exception("Exception", 'NetBox API Error', e)

    def get_api(self):
        return self.netbox

    def get_counter(self):
        return self.counter

    def verify_compatibility(self):
        # nb.version should be the version in the form '3.2'
        version_split = [int(x) for x in self.netbox.version.split('.')]
        version_major, version_minor = (version_split + [0, 0])[:2]

        # Later than 3.2
        # Might want to check for the module-types entry as well?
        if version_major > 3 or (version_major == 3 and version_minor >= 2):
            self.modules = True

        # check if version >= 4.1 in order to use new filter names (https://github.com/netbox-community/netbox/issues/15410)
        if version_major > 4 or (version_major == 4 and version_minor >= 1):
            self.new_filters = True
            self.handle.log(f'Netbox version {self.netbox.version} found. Using new filters.')
    
    def get_manufacturers(self):
        return {str(item): item for item in self.netbox.dcim.manufacturers.all()}

    def create_manufacturers(self, vendors):
        to_create = []
        self.existing_manufacturers = self.get_manufacturers()
        for vendor in vendors:
            try:
                manGet = self.existing_manufacturers[vendor["name"]]
                self.handle.verbose_log(f'Manufacturer Exists: {manGet.name} - {manGet.id}')
            except KeyError:
                to_create.append(vendor)
                self.handle.verbose_log(f"Manufacturer queued for addition: {vendor['name']}")

        if to_create:
            try:
                created_manufacturers = self.netbox.dcim.manufacturers.create(to_create)
                for manufacturer in created_manufacturers:
                    self.handle.verbose_log(f'Manufacturer Created: {manufacturer.name} - '
                        + f'{manufacturer.id}')
                    self.counter.update({'manufacturer': 1})
            except pynetbox.RequestError as request_error:
                self.handle.log("Error creating manufacturers")
                self.handle.verbose_log(f"Error during manufacturer creation. - {request_error.error}")

    def create_device_types(self, device_types_to_add):
        if self.import_filters.is_object_type_excluded("device-types"):
            self.handle.verbose_log("Skipping device types due to exclusion filter.")
            return

        for device_type in device_types_to_add:
            device_type_slug = device_type.get("slug")
            device_type_model = device_type.get("model")
            device_type_manufacturer = device_type.get("manufacturer")
            if self.import_filters.is_object_excluded(
                "device-types",
                device_type_slug,
                device_type_model,
                manufacturer=device_type_manufacturer,
            ):
                self.handle.verbose_log(
                    f"Skipping device type due to exclusion filter: "
                    f'{device_type_model or device_type_slug}'
                )
                continue

            # Remove file base path
            src_file = device_type["src"]
            del device_type["src"]

            # Pre-process front/rear_image flag, remove it if present
            saved_images = {}
            image_base = os.path.dirname(src_file).replace("device-types","elevation-images")
            for i in ["front_image","rear_image"]:
                if i in device_type:
                    if device_type[i]:
                        image_glob = f"{image_base}/{device_type['slug']}.{i.split('_')[0]}.*"
                        images = glob.glob(image_glob, recursive=False)
                        if images:
                          saved_images[i] = images[0]
                        else:
                          self.handle.log(f"Error locating image file using '{image_glob}'")
                    del device_type[i]

            try:
                dt = self.device_types.existing_device_types[
                    self.device_types.get_device_type_key(
                        device_type["manufacturer"]["slug"],
                        device_type["model"],
                    )
                ]
                self.handle.verbose_log(f'Device Type Exists: {dt.manufacturer.name} - '
                    + f'{dt.model} - {dt.id}')
            except KeyError:
                try:
                    dt = self.netbox.dcim.device_types.create(device_type)
                    self.device_types.existing_device_types[
                        self.device_types.get_device_type_key(
                            dt.manufacturer.slug,
                            dt.model,
                        )
                    ] = dt
                    self.counter.update({'added': 1})
                    self.handle.verbose_log(f'Device Type Created: {dt.manufacturer.name} - '
                        + f'{dt.model} - {dt.id}')
                except pynetbox.RequestError as e:
                    self.handle.log(f'Error {e.error} creating device type:'
                                    f' {device_type["manufacturer"]["name"]} {device_type["model"]}')
                    continue

            if "interfaces" in device_type:
                self.device_types.create_interfaces(
                    device_type["interfaces"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "power-ports" in device_type:
                self.device_types.create_power_ports(
                    device_type["power-ports"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "power-port" in device_type:
                self.device_types.create_power_ports(
                    device_type["power-port"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "console-ports" in device_type:
                self.device_types.create_console_ports(
                    device_type["console-ports"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "power-outlets" in device_type:
                self.device_types.create_power_outlets(
                    device_type["power-outlets"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "console-server-ports" in device_type:
                self.device_types.create_console_server_ports(
                    device_type["console-server-ports"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "rear-ports" in device_type:
                self.device_types.create_rear_ports(
                    device_type["rear-ports"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "front-ports" in device_type:
                self.device_types.create_front_ports(
                    device_type["front-ports"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if "device-bays" in device_type:
                self.device_types.create_device_bays(
                    device_type["device-bays"],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )
            if self.modules and 'module-bays' in device_type:
                self.device_types.create_module_bays(
                    device_type['module-bays'],
                    dt.id,
                    manufacturer=device_type_manufacturer,
                )

            # Finally, update images if any
            if saved_images:
                if self.import_filters.is_object_type_excluded("images") or self.import_filters.is_object_excluded(
                    "images",
                    device_type_slug,
                    device_type_model,
                    manufacturer=device_type_manufacturer,
                ):
                    self.handle.verbose_log(
                        f"Skipping images due to exclusion filter: {device_type_model}"
                    )
                else:
                    self.device_types.upload_images(self.url, self.token, saved_images, dt.id)

    def create_module_types(self, module_types):
        if self.import_filters.is_object_type_excluded("module-types"):
            self.handle.verbose_log("Skipping module types due to exclusion filter.")
            return

        all_module_types = {}
        for curr_nb_mt in self.netbox.dcim.module_types.all():
            if curr_nb_mt.manufacturer.slug not in all_module_types:
                all_module_types[curr_nb_mt.manufacturer.slug] = {}

            all_module_types[curr_nb_mt.manufacturer.slug][curr_nb_mt.model] = curr_nb_mt


        for curr_mt in module_types:
            src_file = curr_mt.pop("src", None)
            src_name = os.path.splitext(os.path.basename(src_file))[0] if src_file else None
            module_type_manufacturer = curr_mt.get("manufacturer")
            if self.import_filters.is_object_excluded(
                "module-types",
                curr_mt.get("slug"),
                curr_mt.get("model"),
                src_name,
                manufacturer=module_type_manufacturer,
            ):
                self.handle.verbose_log(
                    f"Skipping module type due to exclusion filter: "
                    f'{curr_mt.get("model") or src_name}'
                )
                continue
            try:
                module_type_res = all_module_types[curr_mt['manufacturer']['slug']][curr_mt["model"]]
                self.handle.verbose_log(f'Module Type Exists: {module_type_res.manufacturer.name} - '
                    + f'{module_type_res.model} - {module_type_res.id}')
            except KeyError:
                try:
                    module_type_res = self.netbox.dcim.module_types.create(curr_mt)
                    all_module_types.setdefault(module_type_res.manufacturer.slug, {})[module_type_res.model] = module_type_res
                    self.counter.update({'module_added': 1})
                    self.handle.verbose_log(f'Module Type Created: {module_type_res.manufacturer.name} - '
                        + f'{module_type_res.model} - {module_type_res.id}')
                except pynetbox.RequestError as exce:
                    self.handle.log(f"Error '{exce.error}' creating module type: " +
                        f"{curr_mt}")
                    if src_file:
                        curr_mt["src"] = src_file
                    continue

            if src_file:
                curr_mt["src"] = src_file

            if "interfaces" in curr_mt:
                self.device_types.create_module_interfaces(
                    curr_mt["interfaces"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "power-ports" in curr_mt:
                self.device_types.create_module_power_ports(
                    curr_mt["power-ports"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "console-ports" in curr_mt:
                self.device_types.create_module_console_ports(
                    curr_mt["console-ports"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "power-outlets" in curr_mt:
                self.device_types.create_module_power_outlets(
                    curr_mt["power-outlets"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "console-server-ports" in curr_mt:
                self.device_types.create_module_console_server_ports(
                    curr_mt["console-server-ports"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "rear-ports" in curr_mt:
                self.device_types.create_module_rear_ports(
                    curr_mt["rear-ports"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )
            if "front-ports" in curr_mt:
                self.device_types.create_module_front_ports(
                    curr_mt["front-ports"],
                    module_type_res.id,
                    manufacturer=module_type_manufacturer,
                )

class DeviceTypes:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, netbox, handle, counter, ignore_ssl, new_filters, import_filters):
        self.netbox = netbox
        self.handle = handle
        self.counter = counter
        self.existing_device_types = self.get_device_types()
        self.ignore_ssl = ignore_ssl
        self.new_filters = new_filters
        self.import_filters = import_filters

    @staticmethod
    def get_device_type_key(manufacturer_slug, model):
        """Build a case-insensitive uniqueness key for device types."""
        return (manufacturer_slug.casefold(), model.casefold())

    def get_device_types(self):
        return {
            self.get_device_type_key(item.manufacturer.slug, item.model): item
            for item in self.netbox.dcim.device_types.all()
        }

    def get_power_ports(self, device_type):
        return {str(item): item for item in self.netbox.dcim.power_port_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
      
    def get_rear_ports(self, device_type):
        return {str(item): item for item in self.netbox.dcim.rear_port_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}

    def get_module_power_ports(self, module_type):
        return {str(item): item for item in self.netbox.dcim.power_port_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}

    def get_module_rear_ports(self, module_type):
        return {str(item): item for item in self.netbox.dcim.rear_port_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}

    def get_device_type_ports_to_create(self, dcim_ports, device_type, existing_ports):
        to_create = [port for port in dcim_ports if port['name'] not in existing_ports]
        for port in to_create:
            port['device_type'] = device_type

        return to_create

    def get_module_type_ports_to_create(self, module_ports, module_type, existing_ports):
        to_create = [port for port in module_ports if port['name'] not in existing_ports]
        for port in to_create:
            port['module_type'] = module_type

        return to_create

    def filter_objects(self, object_type, objects, manufacturer=None):
        return self.import_filters.filter_objects(object_type, objects, manufacturer=manufacturer)

    def create_interfaces(self, interfaces, device_type, manufacturer=None):
        interfaces = self.filter_objects("interfaces", interfaces, manufacturer=manufacturer)
        if not interfaces:
            return
        existing_interfaces = {str(item): item for item in self.netbox.dcim.interface_templates.filter(
            **{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(
            interfaces, device_type, existing_interfaces)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.interface_templates.create(to_create), "Interface")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Interface")

    def create_power_ports(self, power_ports, device_type, manufacturer=None):
        power_ports = self.filter_objects("power-ports", power_ports, manufacturer=manufacturer)
        if not power_ports:
            return
        existing_power_ports = self.get_power_ports(device_type)
        to_create = self.get_device_type_ports_to_create(power_ports, device_type, existing_power_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.power_port_templates.create(to_create), "Power Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Power Port")

    def create_console_ports(self, console_ports, device_type, manufacturer=None):
        console_ports = self.filter_objects("console-ports", console_ports, manufacturer=manufacturer)
        if not console_ports:
            return
        existing_console_ports = {str(item): item for item in self.netbox.dcim.console_port_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(console_ports, device_type, existing_console_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.console_port_templates.create(to_create), "Console Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Console Port")

    def create_power_outlets(self, power_outlets, device_type, manufacturer=None):
        power_outlets = self.filter_objects("power-outlets", power_outlets, manufacturer=manufacturer)
        if not power_outlets:
            return
        existing_power_outlets = {str(item): item for item in self.netbox.dcim.power_outlet_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(power_outlets, device_type, existing_power_outlets)

        if to_create:
            existing_power_ports = self.get_power_ports(device_type)
            for outlet in to_create:
                try:
                    power_port = existing_power_ports[outlet["power_port"]]
                    outlet['power_port'] = power_port.id
                except KeyError:
                    pass

            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.power_outlet_templates.create(to_create), "Power Outlet")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Power Outlet")

    def create_console_server_ports(self, console_server_ports, device_type, manufacturer=None):
        console_server_ports = self.filter_objects("console-server-ports", console_server_ports, manufacturer=manufacturer)
        if not console_server_ports:
            return
        existing_console_server_ports = {str(item): item for item in self.netbox.dcim.console_server_port_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(console_server_ports, device_type, existing_console_server_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.console_server_port_templates.create(to_create), "Console Server Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Console Server Port")

    def create_rear_ports(self, rear_ports, device_type, manufacturer=None):
        rear_ports = self.filter_objects("rear-ports", rear_ports, manufacturer=manufacturer)
        if not rear_ports:
            return
        existing_rear_ports = self.get_rear_ports(device_type)
        to_create = self.get_device_type_ports_to_create(rear_ports, device_type, existing_rear_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.rear_port_templates.create(to_create), "Rear Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Rear Port")

    def create_front_ports(self, front_ports, device_type, manufacturer=None):
        front_ports = self.filter_objects("front-ports", front_ports, manufacturer=manufacturer)
        if not front_ports:
            return
        existing_front_ports = {str(item): item for item in self.netbox.dcim.front_port_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(front_ports, device_type, existing_front_ports)

        if to_create:
            all_rearports = self.get_rear_ports(device_type)
            for port in to_create:
                try:
                    rear_port = all_rearports[port["rear_port"]]
                    port['rear_port'] = rear_port.id
                except KeyError:
                    self.handle.log(f'Could not find Rear Port for Front Port: {port["name"]} - '
                        + f'{port["type"]} - {device_type}')

            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.front_port_templates.create(to_create), "Front Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Front Port")

    def create_device_bays(self, device_bays, device_type, manufacturer=None):
        device_bays = self.filter_objects("device-bays", device_bays, manufacturer=manufacturer)
        if not device_bays:
            return
        existing_device_bays = {str(item): item for item in self.netbox.dcim.device_bay_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(device_bays, device_type, existing_device_bays)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.device_bay_templates.create(to_create), "Device Bay")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Device Bay")

    def create_module_bays(self, module_bays, device_type, manufacturer=None):
        module_bays = self.filter_objects("module-bays", module_bays, manufacturer=manufacturer)
        if not module_bays:
            return
        existing_module_bays = {str(item): item for item in self.netbox.dcim.module_bay_templates.filter(**{'device_type_id' if self.new_filters else 'devicetype_id': device_type})}
        to_create = self.get_device_type_ports_to_create(module_bays, device_type, existing_module_bays)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_device_ports_created(
                                         self.netbox.dcim.module_bay_templates.create(to_create), "Module Bay")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Bay")

    def create_module_interfaces(self, module_interfaces, module_type, manufacturer=None):
        module_interfaces = self.filter_objects("interfaces", module_interfaces, manufacturer=manufacturer)
        if not module_interfaces:
            return
        existing_interfaces = {str(item): item for item in self.netbox.dcim.interface_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}
        to_create = self.get_module_type_ports_to_create(module_interfaces, module_type, existing_interfaces)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.interface_templates.create(to_create), "Module Interface")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Interface")

    def create_module_power_ports(self, power_ports, module_type, manufacturer=None):
        power_ports = self.filter_objects("power-ports", power_ports, manufacturer=manufacturer)
        if not power_ports:
            return
        existing_power_ports = self.get_module_power_ports(module_type)
        to_create = self.get_module_type_ports_to_create(power_ports, module_type, existing_power_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.power_port_templates.create(to_create), "Module Power Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Power Port")

    def create_module_console_ports(self, console_ports, module_type, manufacturer=None):
        console_ports = self.filter_objects("console-ports", console_ports, manufacturer=manufacturer)
        if not console_ports:
            return
        existing_console_ports = {str(item): item for item in self.netbox.dcim.console_port_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}
        to_create = self.get_module_type_ports_to_create(console_ports, module_type, existing_console_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.console_port_templates.create(to_create), "Module Console Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Console Port")

    def create_module_power_outlets(self, power_outlets, module_type, manufacturer=None):
        power_outlets = self.filter_objects("power-outlets", power_outlets, manufacturer=manufacturer)
        if not power_outlets:
            return
        existing_power_outlets = {str(item): item for item in self.netbox.dcim.power_outlet_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}
        to_create = self.get_module_type_ports_to_create(power_outlets, module_type, existing_power_outlets)

        if to_create:
            existing_power_ports = self.get_module_power_ports(module_type)
            for outlet in to_create:
                try:
                    power_port = existing_power_ports[outlet["power_port"]]
                    outlet['power_port'] = power_port.id
                except KeyError:
                    pass

            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.power_outlet_templates.create(to_create), "Module Power Outlet")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Power Outlet")

    def create_module_console_server_ports(self, console_server_ports, module_type, manufacturer=None):
        console_server_ports = self.filter_objects("console-server-ports", console_server_ports, manufacturer=manufacturer)
        if not console_server_ports:
            return
        existing_console_server_ports = {str(item): item for item in self.netbox.dcim.console_server_port_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}
        to_create = self.get_module_type_ports_to_create(console_server_ports, module_type, existing_console_server_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.console_server_port_templates.create(to_create), "Module Console Server Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Console Server Port")

    def create_module_rear_ports(self, rear_ports, module_type, manufacturer=None):
        rear_ports = self.filter_objects("rear-ports", rear_ports, manufacturer=manufacturer)
        if not rear_ports:
            return
        existing_rear_ports = self.get_module_rear_ports(module_type)
        to_create = self.get_module_type_ports_to_create(rear_ports, module_type, existing_rear_ports)

        if to_create:
            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.rear_port_templates.create(to_create), "Module Rear Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Rear Port")

    def create_module_front_ports(self, front_ports, module_type, manufacturer=None):
        front_ports = self.filter_objects("front-ports", front_ports, manufacturer=manufacturer)
        if not front_ports:
            return
        existing_front_ports = {str(item): item for item in self.netbox.dcim.front_port_templates.filter(**{'module_type_id' if self.new_filters else 'moduletype_id': module_type})}
        to_create = self.get_module_type_ports_to_create(front_ports, module_type, existing_front_ports)

        if to_create:
            existing_rear_ports = self.get_module_rear_ports(module_type)
            for port in to_create:
                try:
                    rear_port = existing_rear_ports[port["rear_port"]]
                    port['rear_port'] = rear_port.id
                except KeyError:
                    self.handle.log(f'Could not find Rear Port for Front Port: {port["name"]} - '
                        + f'{port["type"]} - {module_type}')

            try:
                self.counter.update({'updated':
                                     self.handle.log_module_ports_created(
                                         self.netbox.dcim.front_port_templates.create(to_create), "Module Front Port")
                                     })
            except pynetbox.RequestError as excep:
                self.handle.log(f"Error '{excep.error}' creating Module Front Port")

    def upload_images(self,baseurl,token,images,device_type):
        '''Upload front_image and/or rear_image for the given device type

        Args:
        baseurl: URL for Netbox instance
        token: Token to access Netbox instance
        images: map of front_image and/or rear_image filename
        device_type: id for the device-type to update

        Returns:
        None
        '''
        url = f"{baseurl}/api/dcim/device-types/{device_type}/"
        headers = { "Authorization": f"Token {token}" }
        with ExitStack() as exit_stack:
            files = {
                image_type: (os.path.basename(file_name), exit_stack.enter_context(open(file_name, "rb")))
                for image_type, file_name in images.items()
            }
            response = requests.patch(url, headers=headers, files=files, verify=(not self.ignore_ssl))

        if response.ok:
            self.handle.log(f'Images {images} updated at {url}: {response}')
            self.counter["images"] += len(images)
        else:
            self.handle.log(
                f'Failed to update images {images} at {url}: '
                f'{response.status_code} {response.text}')
