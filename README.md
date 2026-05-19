# Netbox Device Type Import

This library is intended to be your friend and help you import all the device-types defined within the the [NetBox Device Type Library Repository](https://github.com/netbox-community/devicetype-library).

> Tested working with 2.9.4, 2.10.4

## 🪄 Description

This script will clone a copy of the `netbox-community/devicetype-library` repository to your machine to allow it to import the device types you would like without copy and pasting them into the Netbox UI.

## 🚀 Getting Started

1. This script is written in Python, so lets setup a virtual environment.

```
git clone https://github.com/netbox-community/Device-Type-Library-Import.git
cd Device-Type-Library-Import
python3 -m venv venv
source venv/bin/activate
```

2. Now that we have the basics setup, we'll need to install the requirements.

```
pip install -r requirements.txt
```

3. There are two variables that are required when using this script to import device types into your NetBox installation: (1) your NetBox instance URL and (2) a token with **write rights**. `REPO_URL` is optional and defaults to the public NetBox device-type library.

Copy the existing `.env.example` to your own `.env` file, and fill in the variables.

```
cp .env.example .env
vim .env
```

Finally, we are able to execute the script and import some device templates!

## 🔌 Usage

To use the script, simply execute the script as follows. Make sure you're still in the activated virtual environment we created before.

```
./nb-dt-import.py
```

This validates the required NetBox environment variables, clones the selected branch from `netbox-community/devicetype-library` into the `repo` subdirectory, and updates that checkout on later runs.

Next, it will loop over every manufacturer and every device of every manufacturer and begin checking if your Netbox install already has them, and if not, creates them. It will skip preexisting manufacturers, devices, interfaces, etc. so as to not end up with duplicate entries in your Netbox instance.

### 🧰 Arguments

This script supports vendor, slug, and exclusion filters so that you can selectively control what gets imported or updated.

To import only device by APC, for example:

```
./nb-dt-import.py --vendors apc
```

`--vendors` can also accept a comma separated list of vendors if you want to import multiple.

```
./nb-dt-import.py --vendors apc,juniper
```

`--exclude-object-types` skips entire template categories or top-level imports, such as `device-types`, `module-types`, `interfaces`, `power-ports`, or `images`.

```
./nb-dt-import.py --exclude-object-types interfaces,module-types
```

`--exclude-objects` skips specific objects by exact name, slug, or model. Prefix an entry with an object type such as `interfaces:mgmt0` or `device-types:ex4300` when you only want that match ignored within one category. Module type exclusions also match the source filename stem because module YAML files do not include slugs. Image exclusions only skip the image upload step; the device type is still imported.

```
./nb-dt-import.py --exclude-objects device-types:ex4300,interfaces:mgmt0
```

## Docker build

It's possible to use this project as a docker container.

To build :

```
docker build -t netbox-devicetype-import-library .
```

Alternatively you can pull a pre-built image from Github Container Registry (ghcr.io):

```
docker pull ghcr.io/minitriga/netbox-device-type-library-import
```

The container supports the following env var as configuration :

- `REPO_URL`, the repo to look for device types (defaults to _https://github.com/netbox-community/devicetype-library.git_)
- `REPO_BRANCH`, the branch to check out if appropriate, defaults to master.
- `NETBOX_URL`, used to access netbox
- `NETBOX_TOKEN`, token for accessing netbox
- `VENDORS`, a comma-separated list of vendors to import (defaults to None)
- `SLUGS`, a space- or comma-separated list of device type slugs to import
- `EXCLUDE_OBJECT_TYPES`, a space- or comma-separated list of object types to skip
- `EXCLUDE_OBJECTS`, a space- or comma-separated list of specific objects to skip; supports scoped entries like `interfaces:mgmt0`, `device-types:ex4300`, or `images:ex4300`
- `REQUESTS_CA_BUNDLE`, path to a CA_BUNDLE for validation if you are using self-signed certificates(file must be included in the container)

To run :

```
docker run -e "NETBOX_URL=http://netbox:8080/" -e "NETBOX_TOKEN=98765434567890" ghcr.io/minitriga/netbox-device-type-library-import
```

## 🤖 Agent Source of Truth

This repository now includes `/agent.md` as its local AI-agent source of truth, adapted from the upstream [`nullroute-commits/agency-agents`](https://github.com/nullroute-commits/agency-agents) project. Use it as the canonical maintenance brief for repository-aware agents.

## ✅ Validation

Run the focused regression suite with:

```
python -m unittest discover -s tests
```

## 🧑‍💻 Contributing

We're happy about any pull requests!

## 📜 License

MIT
