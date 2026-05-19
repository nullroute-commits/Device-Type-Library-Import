#!/usr/bin/env python3
from datetime import datetime

import settings
from netbox_api import NetBox


def main():
    startTime = datetime.now()
    args = settings.args
    settings.validate_environment()
    dtl_repo = settings.create_repo()

    netbox = NetBox(settings)
    files, vendors = dtl_repo.get_devices(dtl_repo.get_devices_path(), args.vendors)

    settings.handle.log(f'{len(vendors)} Vendors Found')
    device_types = dtl_repo.parse_files(files, slugs=args.slugs)
    settings.handle.log(f'{len(device_types)} Device-Types Found')
    netbox.create_manufacturers(vendors)
    netbox.create_device_types(device_types)

    if netbox.modules:
        settings.handle.log("Modules Enabled. Creating Modules...")
        files, vendors = dtl_repo.get_devices(dtl_repo.get_modules_path(), args.vendors)
        settings.handle.log(f'{len(vendors)} Module Vendors Found')
        module_types = dtl_repo.parse_files(files, slugs=args.slugs)
        settings.handle.log(f'{len(module_types)} Module-Types Found')
        netbox.create_manufacturers(vendors)
        netbox.create_module_types(module_types)

    settings.handle.log('---')
    settings.handle.verbose_log(
        f'Script took {(datetime.now() - startTime)} to run')
    settings.handle.log(f'{netbox.counter["added"]} devices created')
    settings.handle.log(f'{netbox.counter["images"]} images uploaded')
    settings.handle.log(
        f'{netbox.counter["updated"]} interfaces/ports updated')
    settings.handle.log(
        f'{netbox.counter["manufacturer"]} manufacturers created')
    if netbox.modules:
        settings.handle.log(
            f'{netbox.counter["module_added"]} modules created')
        settings.handle.log(
            f'{netbox.counter["module_port_added"]} module interface / ports created')


if __name__ == "__main__":
    main()
