from argparse import ArgumentParser
import os

from dotenv import load_dotenv

from log_handler import LogHandler
from repo import DTLRepo

load_dotenv()

REPO_URL = os.getenv(
    "REPO_URL",
    default="https://github.com/netbox-community/devicetype-library.git",
)
REPO_BRANCH = os.getenv("REPO_BRANCH", default="master")
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")
IGNORE_SSL_ERRORS = os.getenv("IGNORE_SSL_ERRORS", default="False") == "True"
REPO_PATH = f"{os.path.dirname(os.path.realpath(__file__))}/repo"

# optionally load vendors through a comma separated list as env var
VENDORS = list(filter(None, os.getenv("VENDORS", "").split(",")))

# optionally load device types through a space separated list as env var
SLUGS = os.getenv("SLUGS", "").split()

parser = ArgumentParser(description='Import Netbox Device Types')
parser.add_argument('--vendors', nargs='+', default=VENDORS,
                    help="List of vendors to import eg. apc cisco")
parser.add_argument('--url', '--git', default=REPO_URL,
                    help="Git URL with valid Device Type YAML files")
parser.add_argument('--slugs', nargs='+', default=SLUGS,
                    help="List of device-type slugs to import eg. ap4431 ws-c3850-24t-l")
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

handle = LogHandler(args)
MANDATORY_ENV_VARS = {
    "NETBOX_URL": NETBOX_URL,
    "NETBOX_TOKEN": NETBOX_TOKEN,
}


def validate_environment(exception_handler=handle):
    for var_name, value in MANDATORY_ENV_VARS.items():
        if not value:
            exception_handler.exception(
                "EnvironmentError",
                var_name,
                f'Environment variable "{var_name}" is not set.',
            )


def create_repo(exception_handler=handle):
    return DTLRepo(args, REPO_PATH, exception_handler)
