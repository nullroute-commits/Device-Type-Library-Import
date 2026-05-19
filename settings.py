from argparse import ArgumentParser
import os

from dotenv import load_dotenv

from log_handler import LogHandler
from repo import DTLRepo

load_dotenv()

REPO_URL = os.getenv(
    "REPO_URL",
    "https://github.com/netbox-community/devicetype-library.git",
)
REPO_BRANCH = os.getenv("REPO_BRANCH", "master")
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")
IGNORE_SSL_ERRORS = os.getenv("IGNORE_SSL_ERRORS", "False") == "True"
REPO_PATH = f"{os.path.dirname(os.path.realpath(__file__))}/repo"

# optionally load vendors through a comma separated list as env var
VENDORS = list(filter(None, os.getenv("VENDORS", "").split(",")))

# optionally load device types through a space separated list as env var
SLUGS = os.getenv("SLUGS", "").split()
EXCLUDE_OBJECT_TYPES = os.getenv("EXCLUDE_OBJECT_TYPES", "").split()
EXCLUDE_OBJECTS = os.getenv("EXCLUDE_OBJECTS", "").split()

parser = ArgumentParser(description='Import Netbox Device Types')
parser.add_argument('--vendors', nargs='+', default=VENDORS,
                    help="List of vendors to import eg. apc cisco")
parser.add_argument('--url', '--git', default=REPO_URL,
                    help="Git URL with valid Device Type YAML files")
parser.add_argument('--slugs', nargs='+', default=SLUGS,
                    help="List of device-type slugs to import eg. ap4431 ws-c3850-24t-l")
parser.add_argument('--exclude-object-types', nargs='+', default=EXCLUDE_OBJECT_TYPES,
                    help="List of object types to skip eg. interfaces module-types")
parser.add_argument('--exclude-objects', nargs='+', default=EXCLUDE_OBJECTS,
                    help="List of object names/models/slugs to skip eg. mgmt0 ex4300")
parser.add_argument('--branch', default=REPO_BRANCH,
                    help="Git branch to use from repo")
parser.add_argument('--verbose', action='store_true', default=False,
                    help="Print verbose output")

args = parser.parse_args()

args.vendors = [
    value.casefold()
    for vendor in args.vendors
    for value in vendor.split(",")
    if value.strip()
]
args.slugs = [
    value
    for slug in args.slugs
    for value in slug.split(",")
    if value.strip()
]
args.exclude_object_types = [
    value
    for object_type in args.exclude_object_types
    for value in object_type.split(",")
    if value.strip()
]
args.exclude_objects = [
    value
    for object_name in args.exclude_objects
    for value in object_name.split(",")
    if value.strip()
]

handle = LogHandler(args)
MANDATORY_ENV_VARS = {
    "NETBOX_URL": NETBOX_URL,
    "NETBOX_TOKEN": NETBOX_TOKEN,
}


def validate_environment(exception_handler=None):
    exception_handler = exception_handler or handle
    for var_name, value in MANDATORY_ENV_VARS.items():
        if not value:
            exception_handler.exception(
                "EnvironmentError",
                var_name,
                f'Environment variable "{var_name}" is not set.',
            )


def create_repo(exception_handler=None, cli_args=None, repo_path=None):
    exception_handler = exception_handler or handle
    return DTLRepo(cli_args or args, repo_path or REPO_PATH, exception_handler)
