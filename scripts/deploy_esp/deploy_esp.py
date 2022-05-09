#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021-2022 Intel Corporation

# pylint: disable=too-many-lines

"""
This script automatizes otherwise manual steps needed to download, configure, build and run
Edge Software Provisioner (ESP), up to the point where it can be run.
It also checks for prerequisites and instructs user what should be done before building ESP.

Target audience are end customers deploying Experience Kits. Additionally it can be used for
speeding up testing of ESP deployment.

Script was written for Python 3.6+ and uses no external dependencies, except for yaml parser.

Example usage scenario (assuming custom config file is used instead of existing default_config.yml):
init with:          <script> --init-config > my_config.yaml
then:               customize config manually
then build it:      <script> --config my_config.yaml
then:               make use of generated USB images (used for USB boot)
and finally run it: <script> --config my_config.yaml --run-esp-for-usb-boot
or for PXE boot:    <script> --config my_config.yaml --run-esp-for-pxe-boot

Note that if option --run-esp-for-xxx-boot is used when not build yet, it will
be firstly build and then run.

Afterwards, if there is a need to repeat some stages (eg. clone new version of ESP, or rebuild ESP,
or run new version of this script):
stop ESP services:              <script> --stop-esp
restart from selected stage:    <script> --config my_config.yaml --start-from=build-esp
start ESP services again:       <script> --config my_config.yaml --run-esp-for-usb-boot
"""

import argparse
import glob
import logging
import os
import pathlib
import re
import shutil
import signal
import subprocess # nosec - bandit: security considered
import sys
import secrets
import tempfile
import traceback
import urllib.parse

import seo.config
import seo.error
import seo.git
import seo.stage
import seo.shell
import seo.yaml


_GIT_PASSWORD_OPT = "--git-password" # nosec - B105 (Possible hardcoded password)
_GIT_USER_OPT = "--git-user"


_CONNECTIVITY_TEST_TIMEOUT = 60 # seconds
_CONNECTIVITY_TEST_IMAGE = "alpine:3.13"


_REQ_DOCK_VER = (20, 10, 11)
_REQ_DOCK_COMP_VER = (1, 23, 2)

_DEFAULT_BIOS =  { 'tpm': False, 'secure_boot': False}


try:
    import yaml
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: Couldn't import yaml module.\n"
        "   It can be installed using following command:\n"
        "   $ pip3 install pyyaml\n")
    sys.exit(seo.error.Codes.MISSING_PREREQUISITE)

# https://github.com/yaml/pyyaml/issues/234
class Dumper(yaml.Dumper):  # pylint: disable=too-many-ancestors
    """ Custom dumper to keep proper indentation level """
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)

# https://stackoverflow.com/questions/37200150/can-i-dump-blank-instead-of-null-in-yaml-pyyaml
# change a None object representer in custom Dumper class (empty string instead of default 'null')
def represent_none(dumper, _):
    """ Custom representer for None object """
    return dumper.represent_scalar('tag:yaml.org,2002:null', '')
yaml.add_representer(type(None), represent_none, Dumper=Dumper)

# change an empty dict object representer in custom Dumper class (empty string instead of default '{}')
def represent_dict(dumper, data):
    """ Custom representer for empty dict object """
    if not data:
        return dumper.represent_data(None)
    else:
        return dumper.represent_dict(data.items())
yaml.add_representer(dict, represent_dict, Dumper=Dumper)


def is_profile_bare_os(profile):
    """ Check if profile is set up as bare os profile """
    # bare_os field is optional
    return 'bare_os' in profile and profile['bare_os'] is True

# ---------------------------------

# path where Experience Kits will be cloned to
EK_PATH = '/opt/seo'

DISTROS = ['centos', 'rhel', 'ubuntu']
HOST_NAMES = ['controller', 'node01']

# stages 'clone-esp', 'configure-esp', 'build-esp' are sequential, while later stages 'build-usb-images'
# and 'configure-profiles' are optional (can be run independent of each other), as reflected by 'order' field.
STAGES = {
    'clone-esp': {
        'display': 'Cloning ESP',
        'status_file': '.cloned_esp',
        'order': '1'
    },
    'configure-esp': {
        'display': 'Configuring ESP',
        'status_file': '.configured_esp',
        'order': '2'
    },
    'build-esp': {
        'display': 'Building ESP',
        'status_file': '.built_esp',
        'order': '3'
    },
    'build-usb-images': {
        'display': 'Building USB images',
        'status_file': '.built_esp_images',
        'order': '4.a'
    },
    'configure-profiles': {
        'display': 'Configuring profiles',
        'status_file': '.configured_profiles',
        'order': '4.b'
    },
}

def parse_args(default_config_path, experience_kit_name):
    """ Parse script arguments """

    experience_kit_name = (
        "" if experience_kit_name is None else
        "{0:s} ".format(experience_kit_name))

    p = argparse.ArgumentParser(
        description=f"""
            Start the Smart Edge Open {experience_kit_name}cluster provisioning process.
            The provisioning process consists of the provisioning server setup, the installation
            media preparation, and the deployment of cluster nodes on selected machines.""")
    p.add_argument(
        "--init-config", action="store_true",
        help="generate default provisioning configuration and print it to the standard output")
    p.add_argument(
        "-c", "--config", action="store", dest="config_file", metavar="PATH",
        default=default_config_path,
        help="provisioning configuration file PATH (default: %(default)s)")
    p.add_argument(
        _GIT_USER_OPT, action="store", dest="git_user", metavar="NAME",
        help="NAME of the git remote user to be used to clone required Smart Edge Open repositories")
    p.add_argument(
        _GIT_PASSWORD_OPT, action="store", dest="git_password", metavar="VALUE",
        help="Git remote token to be used to clone required Smart Edge Open repositories")
    p.add_argument(
        "--dockerhub-user", action="store", dest="dockerhub_user", metavar="NAME",
        help="NAME of the user to authenticate with DockerHub during Live System stage")
    p.add_argument(
        "--dockerhub-pass", action="store", dest="dockerhub_pass", metavar="VALUE",
        help="Password used to authenticate with DockerHub during Live System stage")
    p.add_argument(
        "--registry-mirror", action="store", dest="registry_mirror", metavar="URL",
        help="add the URL to the list of local Docker registry mirrors")

    p.add_argument("--run-esp-for-usb-boot", action="store_true", default=False,
                   help="start ESP services for booting from USB image")
    p.add_argument("--run-esp-for-pxe-boot", action="store_true", default=False,
                   help="start ESP services for booting from PXE")
    p.add_argument("--stop-esp", action="store_true", default=False,
                   help="stop ESP services")
    p.add_argument("--cleanup", action="store_true", dest="force",
                   help="cleanup existing build artifacts before "
                   "taking any other actions (stop the services if needed)")
    dev_args = p.add_argument_group('Development options')
    dev_args.add_argument("--debug", action="store_true", dest="debug",
                          help="provide more verbose diagnostic information")
    dev_args.add_argument("--start-from", action="store", help="restart build process from selected phase",
                          choices=STAGES.keys())
    return p.parse_args()


def init_config(default_config_path):
    """ Dump content of the default configuration file to the screen (standard output) """

    with open(default_config_path) as cfg_file:
        for line in cfg_file:
            sys.stdout.write(line)

    logging.info("Provisioning configuration generated")


def apply_args(cfg, args):
    """ Overwrite loaded configuration with applicable command line arguments (if specified) """

    if args.git_user is not None:
        cfg.setdefault("git", {})["user"] = args.git_user

    if args.git_password is not None:
        cfg.setdefault("git", {})["password"] = args.git_password

    if args.registry_mirror is not None:
        # Following condition is expected to be enforced earlier (validate_config function):
        assert isinstance(cfg['docker']['registry_mirrors'], list) # nosec B101 - used just for development
        cfg['docker']['registry_mirrors'].append(args.registry_mirror)

    if args.dockerhub_user is not None and args.dockerhub_pass is not None:
        # Following condition is expected to be enforced earlier (validate_config function):
        assert isinstance(cfg['docker']['dockerhub'], dict) # nosec - B101
        assert isinstance(cfg['docker']['dockerhub']['username'], str) # nosec - B101
        assert isinstance(cfg['docker']['dockerhub']['password'], str) # nosec - B101
        cfg['docker']['dockerhub']['username'] = args.dockerhub_user
        cfg['docker']['dockerhub']['password'] = args.dockerhub_pass


def is_repo_accessible(url, args=None):
    """ Check if given repo is accessible.

        The function will work with user credentials included in the
        url as well as without them. This feature allows checking if a
        repo is private and if credentials work.
    """

    parsed = urllib.parse.urlparse(url)
    refs_url = parsed._replace(
        path="/".join([parsed.path.rstrip("/"), "info", "refs"]),
        query="service=git-upload-pack").geturl()

    try:
        cmd = ["wget", "--output-document", "/dev/null", refs_url]
        if args is not None and not args.debug:
            subprocess.run(cmd, stderr=subprocess.DEVNULL, check=True) # nosec - B603 (subprocess call)
        else:
            subprocess.run(cmd, check=True) # nosec - B603 (subprocess call)
    except subprocess.CalledProcessError:
        return False

    return True


def verify_repo_status(desc, url, config, args):
    """ Verify if given repo is a public repo or a private repo but
        the provided credentials allow to access it. In case of
        the access failure raise the application exception
    """

    if is_repo_accessible(url, args):
        logging.info("%s repository is public: %s", desc, url)
        return

    logging.debug("%s repository is not public: %s", desc, url)


    if 'git' not in config:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"The {desc} repository is private and requires the git user and password to be specified using the"
            f" {_GIT_USER_OPT} option or custom config file with git credentials,"
            f" or the repository url ('{url}') is incorrect")

    if not config['git']['user']:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either, the {desc} repository is private and requires the git remote user to be specified using the"
            f" {_GIT_USER_OPT} option, or the repository url ('{url}') is incorrect")

    if not config['git']['password']:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either the {desc} repository is private and requires the git remote token to be specified using the"
            f" {_GIT_PASSWORD_OPT} option, or the repository url ('{url}') is incorrect")

    auth_url = seo.git.apply_credentials(url, config['git']['user'], config['git']['password'])

    if not is_repo_accessible(auth_url, args):
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either the {desc} repository url ('{url}') or the provided git remote credentials are incorrect")

    logging.info(
        "%s repository is private and the %s's credentials are working: %s",
        desc, config['git']['user'], url)


def remove_files_recurse_by_pattern(path, pattern):
    """Iterates recursively over files in given path and removes which match pattern"""
    for root, _, files in os.walk(path):
        for filename in files:
            if re.match(pattern, filename):
                os.remove(os.path.join(root, filename))
                logging.debug("File %s/%s cleaned.", path, filename)


def check_repositories(config, args):
    """Check if all the repositories occurring in the configuration file are accessible using given configuration"""

    verify_repo_status("ESP", config["esp"]["url"], config, args)

    verified_repos = []

    for profile in config['profiles']:
        if profile['url'] not in verified_repos:
            verify_repo_status("ESP Profile", profile["url"], config, args)
            verified_repos.append(profile['url'])

        if not is_profile_bare_os(profile):
            if profile['experience_kit']['url'] not in verified_repos:
                verify_repo_status("Experience Kit", profile["experience_kit"]["url"], config, args)
                verified_repos.append(profile['experience_kit']['url'])


def get_version(command: str) -> tuple:
    """executes command which is supposed to output a version like 1.2.3"""

    try:
        logging.debug("Executing command `%s` to get program version", command)

        out = subprocess.check_output(command.split(" ")).decode("utf-8")  # nosec - B603 (subprocess call)
    except (FileNotFoundError, PermissionError) as ex:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"command: '{command}' cannot be executed\n"
            f"    {seo.error.TS_REF}")
    except subprocess.CalledProcessError as ex:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"{command} returned an error {ex.returncode}.\n"
            f"    {seo.error.TS_REF}")

    match = re.search(r'\d+(\.\d+)+', out)

    if match is None:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"cannot parse version string from `{command}` output\n"
            f"    {seo.error.TS_REF}")

    version = match.group(0)
    version = tuple(map(int, version.split(".")))

    logging.debug("Version parsed is %s", ".".join(map(str, version)))

    return version


def check_version(command: str, required: tuple):
    """ Check if tool is installed and is at least the minimum required version
        Throws an exception if version requirements are not satisfied to stop program execution"""

    current = get_version(command)

    cur_str = '.'.join(map(str, current))
    req_str = '.'.join(map(str, required))

    if current < required:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"{command} doesn't meet minimum version requirement. Current version: {cur_str} is less than {req_str}.\n"
            f"    {seo.error.TS_REF}")

    logging.debug("Version check %s required: %s current: %s passed", command, req_str, cur_str)


def check_preconditions(args):
    """ Check script's preconditions """

    logging.debug("Check preconditions")

    # check current user permissions
    if os.getuid() != 0:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            "This script must be run as the root user; Use the 'sudo su -' command to change it")

    # detect OS (works at least for CentOS, RHEL and Ubuntu)
    for distro in DISTROS:
        # note: for centos/rhel ID is within double-quotes, while for ubuntu there are no double-quotes
        cmd = "cat /etc/os-release | grep -e ^ID=.*"
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                              shell=True, check=False) # nosec - B602
        if proc.returncode == 0 and distro in proc.stdout:
            logging.debug("Detected host Linux: %s", distro)
            break
    else:
        logging.warning("No detected host Linux distribution!")

    if distro not in ("rhel", "centos", "ubuntu"):
        logging.warning("Unsupported linux distribution. There might be some issues.")

    # check if Docker is installed and is at least the minimum required version
    check_version("docker --version", _REQ_DOCK_VER)

    # hint about docker autostart
    cmd = "systemctl list-unit-files | grep docker.service | awk '{print $2}'"
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                          shell=True, check=False) # nosec - B602
    if proc.returncode == 0 and proc.stdout.strip() == 'disabled':
        logging.warning("Docker package is not configured to run at system boot. "
                        "Enable it with 'systemctl enable docker --now'")

    # check if Docker-Compose is installed and is at least the minimum required version
    check_version("docker-compose --version", _REQ_DOCK_COMP_VER)

    # sanity checks for docker
    tmpdir = tempfile.mkdtemp()
    with open(f"{tmpdir}/Dockerfile", "w") as f:
        f.write(f"FROM {_CONNECTIVITY_TEST_IMAGE}\nRUN apk update && apk add --no-cache wget")

    cmds = [
        ["docker", "pull", _CONNECTIVITY_TEST_IMAGE],
        ["docker", "run", "--rm", "--init", _CONNECTIVITY_TEST_IMAGE, "sh", "-c",
         f"timeout {_CONNECTIVITY_TEST_TIMEOUT} apk update"],
        # timeout does not work inside docker build, so it'll be used to wrap whole `docker build` command
        ["timeout", f"{_CONNECTIVITY_TEST_TIMEOUT}",
         "docker", "build", "--no-cache", "-t", "provision-docker-test", tmpdir],
        ['docker', 'image', 'rm', 'provision-docker-test']
    ]

    for cmd in cmds:
        logging.info("Testing Docker configuration: %s", subprocess.list2cmdline(cmd))
        try:
            if not args.debug:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True) # nosec - B602
            else:
                subprocess.run(cmd, check=True) # nosec - B602
        except subprocess.CalledProcessError as e:
            shutil.rmtree(tmpdir)
            raise seo.error.AppException(
                seo.error.Codes.MISSING_PREREQUISITE,
                f"Failed to confirm that Docker is configured correctly\n"
                f"    Following command failed:\n"
                f"    {subprocess.list2cmdline(cmd)}") from e

    shutil.rmtree(tmpdir)

def run_esp_script(cmd, workdir):
    """ Helper to run ESP scripts: build.sh, makeusb.sh and run.sh """
    script_name = os.path.basename(cmd[0])
    cmd = " ".join(cmd)

    # convert to Path if string was passed
    workdir = pathlib.Path(workdir)
    if not workdir.exists():
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Workdir does not exist in expected location '{workdir}', required by '{cmd}'")

    logging.debug("Running command: %s", cmd)
    with subprocess.Popen(cmd, shell=True, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, # nosec - B602
                          universal_newlines=True) as proc:
        try:
            while proc.poll() is None:
                line = proc.stdout.readline()
                if line:
                    # newlines are already contained in the output
                    print(line, end='')

            if proc.poll() != 0:
                raise seo.error.AppException(
                    seo.error.Codes.RUNTIME_ERROR,
                    f"ESP script failed: {script_name}\n"
                    f"    {seo.error.TS_REF}")
        except KeyboardInterrupt as e:
            # gracefully handle SIGINT, kill script that may be stuck in background.
            # note: since script can start bunch of other scripts, it sometimes is not killed with simple
            # proc.terminate() or proc.kill(), therefore we need to kill whole process group.
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            raise RuntimeError("Interrupted by user") from e


def is_esp_running(workdir, service='web'):
    """ Helper to get info if ESP server is currently running """

    # this will print just id/hex of a given ESP service if it's up, and nothing if it's down.
    # we check web service to determine if script was already ran by user with --run-esp-for-xxx option,
    # (note: some base services like core or mirror are up right after build.sh, before run.sh was even started)
    cmd_tmpl = ['docker-compose', 'ps', '-q']

    # convert to Path if string was passed
    workdir = pathlib.Path(workdir)
    if not workdir.exists():

        cmd = " ".join(cmd_tmpl)
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Workdir does not exist in expected location '{workdir}', required by '{cmd}'")

    cmd = cmd_tmpl.copy() + [service]
    proc = subprocess.run(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, # nosec - B603
                          universal_newlines=True, check=False)

    return proc.returncode == 0 and proc.stdout.strip() != ''


def stop_esp(workdir):
    """ Executes ESP's run.sh with --down flag """
    logging.debug("Stopping provisioning services")

    cmd = ['./run.sh', '--down']
    run_esp_script(cmd, workdir)


def run_esp(config, args):
    """ Executes ESP's run.sh script """
    usb_boot_cmd = ['./run.sh', '--no-tail-logs', '--no-dnsmasq']
    pxe_boot_cmd = ['./run.sh', '--no-tail-logs']

    workdir = pathlib.Path(config['esp']['dest_dir'])

    if args.run_esp_for_usb_boot:
        if is_esp_running(workdir):
            logging.warning("ESP seems already running. Stopping it first...")
            stop_esp(workdir)
        logging.info("Starting ESP...")
        run_esp_script(usb_boot_cmd, workdir)

    elif args.run_esp_for_pxe_boot:
        logging.warning("Running DHCP/PXE server. This will disrupt your network if running in non isolated network, "
                        "with other DHCP server running on the same network!")

        if not config['dnsmasq']['enabled']:
            raise ValueError("User wanted to run for PXE boot, but 'dnsmasq.enabled' is set to False")

        if is_esp_running(workdir):
            logging.warning("ESP seems already running. Stopping it first...")
            stop_esp(workdir)
        logging.info("Starting ESP...")
        run_esp_script(pxe_boot_cmd, workdir)

    elif args.stop_esp:
        if not is_esp_running(workdir):
            logging.warning("ESP seems already stopped.")
        else:
            stop_esp(workdir)


def print_profile_credentials(config):
    """ Display profile credentials if available """

    for profile in config['profiles']:
        try:
            username = profile['account']['username']
            password = profile['account']['password']
        except (TypeError, KeyError):
            pass
        else:
            print(f"Credentials for profile {profile['name']}:\n\tUsername: {username}\n\tPassword: {password}")


def configure_se_profile_group_vars_all(cfg, profile_path):
    """ Configure profile's group_vars/all.yml file based on config variables and env vars """

    all_vars = {}
    all_vars['git_repo_token'] = cfg['git']['password']

    proxy = {}
    for p in ['http_proxy', 'https_proxy', 'no_proxy', 'ftp_proxy']:
        if os.environ.get(p) is not None:
            proxy[p] = os.environ[p]
    if proxy:
        all_vars['proxy_env'] = proxy

    if cfg['ntp_server']:
        all_vars['ntp_enable'] = True
        all_vars['ntp_servers'] = [cfg['ntp_server']]

    if cfg['docker']['registry_mirrors']:
        all_vars['docker_registry_mirrors'] = cfg['docker']['registry_mirrors']

    # serialize all vars, overwrite existing file
    output = yaml.dump(all_vars, Dumper=Dumper, default_flow_style=False)
    open(profile_path / "files/seo/group_vars/all.yml", "w").write(output)


def configure_se_profile_customize_vars(profile, profile_path):
    """ Configure profile's group_vars and host_vars with user-provided customizations """

    items = []
    if 'group_vars' in profile and 'groups' in profile['group_vars']:
        for group_name, body in profile['group_vars']['groups'].items():
            if body is not None:
                items.append((group_name, body, f"group_vars/{group_name}.yml"))
    if 'host_vars' in profile and 'hosts' in profile['host_vars']:
        for host_name, body in profile['host_vars']['hosts'].items():
            if body is not None:
                items.append((host_name, body, f"host_vars/{host_name}.yml"))

    # serialize vars
    for name, body, seo_path in items:
        # since we already dumped some vars to all.yml, append or overwrite in that case
        seo_full_path = profile_path / "files/seo" / seo_path
        if name == 'all':
            all_vars = seo.yaml.load(seo_full_path) # nosec - B506 (False positive: It is not a yaml.load call)
            for key, value in body.items():
                if key in all_vars and isinstance(value, dict):
                    all_vars[key].update(value)
                else:
                    all_vars[key] = value
            content = all_vars
        else:
            content = body

        output = yaml.dump(content, Dumper=Dumper, default_flow_style=False)
        with open(seo_full_path, "w") as f:
            f.write(output)


def configure_se_profile_config_yaml(config, profile, profile_path):
    """ Configure profile's conf/config.yml file, which contain kernel parameters """

    with open(profile_path / "conf/config.yml", "r+") as f:
        content = f.read()

        # first clean any leftovers
        for param in ('username', 'password', 'ntp_server', 'docker_login_user', 'docker_login_pass', 'bare_os'):
            regexp = fr'( {param}=\S*)'
            content = re.sub(regexp, '', content)

        try:
            username = profile['account']['username']
        except (TypeError, KeyError):
            username = "smartedge-open"
            print(f"Setting default username '{username}' for profile {profile['name']}")

        try:
            password = profile['account']['password']
        except (TypeError, KeyError):
            password = secrets.token_urlsafe(32)
            print(f"Setting default password '{password}' for profile {profile['name']}")

        content = re.sub(
            r'(kernel_arguments:.*)$',
            f"\\1 username={username} "
            f"password={password}",
            content)

        profile['account'] = dict(username=username, password=password)

        if config['docker']['dockerhub']['username'] and config['docker']['dockerhub']['password']:
            content = re.sub(
                r'(kernel_arguments:.*)$',
                f"\\1 docker_login_user={config['docker']['dockerhub']['username']} "
                f"docker_login_pass={config['docker']['dockerhub']['password']}",
                content)

        if config['ntp_server']:
            content = re.sub(
                r'(kernel_arguments:.*)$',
                f"\\1 ntp_server={config['ntp_server']}",
                content)

        if is_profile_bare_os(profile):
            content = re.sub(
                r'(kernel_arguments:.*)$',
                "\\1 bare_os=true",
                content)

        f.seek(0)
        f.write(content)
        f.truncate()


def configure_se_profile_customize_inventory(profile, profile_path):
    """ Configure profile's inventory files, with additional hosts groups """

    if profile['scenario'] == 'single-node':
        items = [('all', 'single_node.yml'), (None, 'controller.yml'), (None, 'node.yml')]
    elif profile['scenario'] == 'multi-node':
        items = [(None, 'single_node.yml'), ('only_controller', 'controller.yml'), ('all', 'node.yml')]

    for mode, inventory_filename in items:
        inventory_groups = {}
        inventory_output = ''
        # no need to fill inventory groups if mode is None, this will effectively
        # remove leftovers from unused files, in case of switching single-node <-> multi-node
        if 'extra_inventory_groups' in profile and \
           profile['extra_inventory_groups'] is not None \
           and mode is not None:
            for group_name, hosts in profile['extra_inventory_groups'].items():
                # insert new items if not existing yet
                inventory_groups.setdefault(group_name, {})
                inventory_groups[group_name].setdefault('hosts', {})
                if hosts:
                    for host_name in hosts.keys():
                        if host_name not in HOST_NAMES:
                            logging.warning("Inventory group contains unsupported host name: %s", host_name)
                        else:
                            # when dumping for controller's multi-node, skip over node group hosts
                            if mode == 'only_controller' and host_name != 'controller':
                                continue
                            # insert new items if not existing yet
                            inventory_groups[group_name]['hosts'].setdefault(host_name)
            if inventory_groups:
                inventory_output = yaml.dump(inventory_groups, Dumper=Dumper, default_flow_style=False)

        # replace inventory groups
        with open(profile_path / f"files/seo/inventories/{inventory_filename}", "r+") as f:
            content = f.read()

            marker_beg = '##extra_inventory_groups_begin##'
            marker_end = '##extra_inventory_groups_end##'
            content = re.sub(
                fr'^({marker_beg}[\r\n])(.*[\r\n])*({marker_end})[\r\n]*', fr"\1{inventory_output}\3\n",
                content, flags=re.MULTILINE)

            f.seek(0)
            f.write(content)
            f.truncate()

def adapt_to_profile(variables):
    '''Adapts variable names to profile variable names according to mapping, temporary'''

    mapping = {'address': 'redfish_ip',
                'user': 'redfish_user',
                'password': 'redfish_password',
                'name': 'node_hostname',
                'secure_boot': 'enable_secure_boot',
                'tpm': 'enable_tpm'
        }

    return {mapping.get(name, name): value for name, value in variables.items()}


def global_bmc_and_bios_configuration(config):
    '''Returns global bios and bmc configuration in a single dictionary'''
    variables = dict(_DEFAULT_BIOS)

    if 'bmc' in config:
        variables.update(config['bmc'])

    if 'bios' in config:
        variables.update(config['bios'])

    return variables

def configure_profile_settings(config, profile, profile_path):
    """ Configure profile's provision_settings file """

    variables = {
        'ek_path': EK_PATH,
        'scenario': profile['scenario'],
        'git_user': config['git']['user'],
        'git_password': config['git']['password']
    }

    if 'controlplane_mac' in profile and profile['controlplane_mac']:
        variables['controller_mac'] = profile['controlplane_mac']

    variables.update(global_bmc_and_bios_configuration(config))

    if 'bios' in profile:
        variables.update(profile['bios'])


    if not is_profile_bare_os(profile):
        variables.update({
            'url':  profile['experience_kit']['url'],
            'deployment': profile['experience_kit']['deployment'],
            'branch': profile['experience_kit']['branch']
        })

    variables = adapt_to_profile(variables)

    seo.shell.create_variables_file(profile_path / "files/seo/provision_settings", variables)


def configure_se_profile_sideload_files(profile, profile_path):
    """ Prepare files for sideloading onto provisioned system """

    gen_script = profile_path / "files/seo/download_sideload_files.sh"
    # remove leftover file
    if gen_script.exists():
        gen_script.unlink()

    sideload_dir = profile_path / "files/seo/sideload"

    # purge all previous sideload dir content, aside of .keep file
    for p in sideload_dir.glob('*'):
        if p.name != '.keep':
            logging.debug("Purging file in sideload dir: %s", p.name)
            shutil.rmtree(sideload_dir / p.name)

    cmd_tmpl = 'mkdir -p %(parent_dir)s\n' \
    'wget --header "Authorization: token ${param_token}" -O "%(dest_path)s" ' \
    '"${param_bootstrapurl}/files/seo/sideload/%(sideload_path)s"\n'

    output = ''
    if 'sideload' in profile and profile['sideload'] is not None:
        for idx, item in enumerate(profile['sideload']):
            file_path = pathlib.Path(item['file_path'])
            dest_path = pathlib.Path(item['dest_path'])
            # dest_path can be absolute or relative (to the EK_PATH dir)
            if not dest_path.is_absolute():
                dest_path = pathlib.Path(EK_PATH, item['dest_path'])

            if not file_path.exists():
                logging.warning("File path for sideload '%s' does not exist! "
                                "Make sure you passed absolute path", file_path)
                continue

            # create intermediate folders, to prevent name collisions
            idx_dir = sideload_dir / f"item_{idx:0>3}"
            idx_dir.mkdir()

            if file_path.is_file():
                # copy file to sideload dir
                sideload_target = idx_dir / os.path.basename(file_path)
                shutil.copyfile(file_path, sideload_target)

                # if dest_path looks like dir path, we assume that filename should be appended to that dir path
                if item['dest_path'].endswith('/'):
                    dest_path = dest_path / os.path.basename(file_path)

                # generate command to download it on the target machine
                output += cmd_tmpl % {'parent_dir': str(dest_path.parent),
                                      'dest_path': str(dest_path),
                                      'sideload_path': sideload_target.relative_to(sideload_dir)}

            elif file_path.is_dir():
                # copy content of a folder to sideload dir
                for p in file_path.glob('*'):
                    sideload_target = idx_dir / p.name
                    if p.is_dir():
                        shutil.copytree(p, sideload_target)
                    else:
                        shutil.copyfile(p, sideload_target)

                # for each file inside folder, generate command to download it on the target machine
                for p in sorted(idx_dir.glob('**/*')):
                    if p.is_file():
                        new_dst_path = dest_path / p.relative_to(idx_dir)
                        output += cmd_tmpl % {'parent_dir': str(new_dst_path.parent),
                                              'dest_path': str(new_dst_path),
                                              'sideload_path': p.relative_to(sideload_dir)}

    # generate even empty file (file is always downloaded to target machine)
    open(gen_script, "w").write(output)


@seo.stage.stage('configure-profiles', STAGES)
def configure_se_profiles(config):
    """ Configure Smart Edge profiles """

    esp_path = pathlib.Path(config['esp']['dest_dir'])
    for profile in config['profiles']:
        profile_path = esp_path / f"data/usr/share/nginx/html/profile/{profile['name']}"
        configure_profile_settings(config, profile, profile_path)
        configure_profile_hosts_specific_settings(config, profile, profile_path)
        if not is_profile_bare_os(profile):
            configure_se_profile_group_vars_all(config, profile_path)
            configure_se_profile_customize_vars(profile, profile_path)
            configure_se_profile_customize_inventory(profile, profile_path)
            configure_se_profile_sideload_files(profile, profile_path)


def copy_usb_image(config, bios, profile="all"):
    """ Copy created image to user's location specified in config.
        Images are renamed to: {profile}-{bios}.img
    """

    workdir = pathlib.Path(config['esp']['dest_dir'])
    usb_config = config['usb_images']

    image_path = workdir / f"data/usr/share/nginx/html/usb/{profile}/uos-{bios}.img"
    if not image_path.exists():
        raise seo.error.AppException(
            seo.error.Codes.RUNTIME_ERROR,
            "Installation image couldn't be found in the expected location:\n"
            f"    {image_path}")

    if usb_config['output_path']:
        output_path = pathlib.Path(usb_config['output_path'])
        if not output_path.exists():
            logging.debug("Creating output dir %s", output_path)
            output_path.mkdir(parents=True, exist_ok=True)

        new_path = output_path / f"{profile}-{bios}.img"
        logging.debug("Copying %s to %s", image_path, new_path)
        shutil.copyfile(image_path, new_path)


def make_usb(workdir, bios, profile="all"):
    """ Runs ESP's makeusb.sh for given bios and profile.
        If no profile is given, then image for all profiles will be built. """

    # because makeusb.sh script turns into interactive mode asking to
    # overwrite older file, and that makes subprocess hang, we need to remove files in advance.
    images_dir = workdir / f"data/usr/share/nginx/html/usb/{profile}"
    for img in glob.glob(f"{images_dir}/*-{bios}.img"):
        logging.debug("Removing old image %s", img)
        os.remove(img)

    # prepare command
    cmd = ['./makeusb.sh', '-b', bios]
    if profile != "all":
        cmd.extend(['-p', profile])

    run_esp_script(cmd, workdir)


@seo.stage.stage('build-usb-images', STAGES)
def build_usb_images(config):
    """ Executes make_usb() function and copies images to user's location """

    workdir = pathlib.Path(config['esp']['dest_dir'])
    usb_config = config['usb_images']
    bioses = [k  for k in ('bios', 'efi')  if usb_config[k]]

    if usb_config['output_path']:
        output_path = pathlib.Path(usb_config['output_path'])
        if output_path.exists():
            if not output_path.is_dir():
                raise ValueError(
                    f"Output path {output_path} exists and it's not a directory")
            logging.info("Removing already existing %s directory (stalled)", output_path)
            shutil.rmtree(usb_config['output_path'], ignore_errors=True)

    if usb_config['all_in_one']:
        for bios in bioses:
            logging.debug("Running makeusb.sh for %s", bios)
            make_usb(workdir, bios)
            copy_usb_image(config, bios)
    else:
        # take profile data from config.yml (script's config may have changed without user repeating configure stage)
        esp_cfg = yaml.safe_load(open(workdir / "conf/config.yml", 'r'))
        for bios in bioses:
            for profile in [p['name']  for p in esp_cfg['profiles']]:
                logging.debug("Running makeusb.sh for %s %s", bios, profile)
                make_usb(workdir, bios, profile)
                copy_usb_image(config, bios, profile)


@seo.stage.stage('clone-esp', STAGES)
def clone_esp(config):
    """ Download ESP """

    esp_config = config['esp']
    dest = esp_config['dest_dir']

    with pathlib.Path(dest) as path:
        if path.exists():
            if not path.is_dir():
                raise seo.error.AppException(
                    seo.error.Codes.CONFIG_ERROR,
                    f"The ESP destination directory ('{dest}') already exists and is not a directory")

            logging.info("Removing already existing %s directory (stalled)", dest)
            shutil.rmtree(dest, ignore_errors=True)

    def __make_cmd(user, password):
        return ["git", "clone", seo.git.apply_credentials(esp_config['url'], user, password),
        "--branch", esp_config['branch'], dest]

    if 'git' in config:
        cmd_actual = __make_cmd(config['git']['user'], config['git']['password'])
        cmd_anonym = __make_cmd("<user>", "<password>")
    else:
        cmd_actual = __make_cmd(None, None)
        cmd_anonym = cmd_actual

    logging.debug("Executing command: %s", " ".join(cmd_anonym))

    try:
        subprocess.run(cmd_actual, check=True) # nosec - B603
    except subprocess.CalledProcessError as e:
        raise seo.error.AppException(seo.error.Codes.RUNTIME_ERROR, "Failed to clone the ESP repository") from e


@seo.stage.stage('configure-esp', STAGES)
def configure_esp(config):
    """ Populate ESP's conf/config.yml file.
        The file contains list of profiles and optional options for dnsmasq. """

    esp_config_fullpath = pathlib.PurePath(config['esp']['dest_dir']) / "conf/config.yml"

    # backup existing config (only first time script runs, otherwise we would repeatedly overwrite backup file)
    bak_file = str(esp_config_fullpath) + '.bak'
    if not pathlib.Path(bak_file).exists():
        logging.debug("Backing up file %s to %s", esp_config_fullpath, bak_file)
        try:
            shutil.copyfile(esp_config_fullpath, bak_file)
        except Exception:
            logging.error("Error occurred while creating %s file.", bak_file)
    else:
        logging.info("Skipping creating %s file (stalled).", bak_file)

    esp_cfg = {}
    if config['dnsmasq']['enabled']:
        # propagate only config entries supported by ESP, that were defined by user
        for k, v in config['dnsmasq'].items():
            if v and k != 'enabled':
                esp_cfg[k] = v

    # populate profiles
    esp_cfg['profiles'] = []
    for p in config['profiles']:
        esp_profile = {
            'git_remote_url': p['url'],
            'profile_branch': p['branch'],
            'profile_base_branch': '',  # empty - SEO profiles do not split code into branches
            'git_username': config['git']['user'],
            'git_token': config['git']['password'],
            'name': p['name'],
            'custom_git_arguments': '--depth=1',
        }
        esp_cfg['profiles'].append(esp_profile)

    # create new ESP config.yml,
    # serialize using custom dumper, to keep indentation compatible with what ESP expects
    # (by default there is no whitespace indentation used)
    output = yaml.dump(esp_cfg, Dumper=Dumper)
    open(esp_config_fullpath, "w").write(output)

    # use provided docker registry mirror (take first one if multiple ones are provided)
    # that ESP's own registry service will fallback to if requested image is not found locally
    if config['docker']['registry_mirrors']:
        registry_config_fullpath = pathlib.PurePath(config['esp']['dest_dir']) / "template/registry/config.yml"
        with open(registry_config_fullpath, "r+") as f:
            content = f.read()
            content = re.sub(
                r'remoteurl:\s([^\s]+)', f"remoteurl: {config['docker']['registry_mirrors'][0]}", content)

            f.seek(0)
            f.write(content)
            f.truncate()


@seo.stage.stage('build-esp', STAGES)
def build_esp(config):
    """ Runs ESP's build.sh script and prints the output. """

    workdir = pathlib.Path(config['esp']['dest_dir'])
    # Remove .build.lock just in case because ESP's prompt needs user input
    build_lock = workdir / "conf/.build.lock"
    if build_lock.exists():
        build_lock.unlink()

    # because we need to configure profile's conf/config.yml, which is being used by build.sh
    # for generating boot menus, we first build everything, then alter that config, and
    # then just regenerate boot menu using new config.
    build_cmd = ['./build.sh']
    run_esp_script(build_cmd, workdir)

    for profile in config['profiles']:
        profile_path = workdir / f"data/usr/share/nginx/html/profile/{profile['name']}"
        configure_se_profile_config_yaml(config, profile, profile_path)

    rebuild_boot_menu_cmd = ['./build.sh', '-S', '-P']
    run_esp_script(rebuild_boot_menu_cmd, workdir)


def cleanup(config):
    """
    This function perform cleanups:
    - Stops and removes ESP containers
    - Removes ESP from disk
    - Removes stage status files (e.g. .cloned_esp)

    Docker images & cache are left intact.
    """

    logging.info("Cleaning the provisioning environment")

    esp_path = pathlib.Path(config['esp']['dest_dir'])

    if esp_path.exists():
        if is_esp_running(esp_path, service='core'):
            # in the end, this runs docker-compose down, which stops and removes containers
            stop_esp(esp_path)
        shutil.rmtree(esp_path)

    for _, v in STAGES.items():
        status_file = pathlib.Path(v['status_file'])
        if status_file.exists():
            status_file.unlink()

    output_dir = pathlib.Path(config['usb_images']['output_path'])

    try:
        shutil.rmtree(output_dir)
    except FileNotFoundError as e:
        logging.debug("Path '%s' doesn't exist", e.filename)


def credentials_check_needed():
    ''' Check stages that can be impacted by credentials change. '''

    status_files = [
        v['status_file'] for k, v in STAGES.items()
        if k in ['clone-esp', 'configure-esp', 'configure-profiles']]
    for status_file in status_files:
        if not pathlib.Path(status_file).exists():
            return True
    return False


def preconditions_check_needed():
    ''' Check stages that can be impacted by environment preconditions change. '''
    return not pathlib.Path(STAGES['build-esp']['status_file']).exists()


def configure_profile_hosts_specific_settings(config, profile, profile_path):
    '''
    The function parse 'hosts' node in config file into separate
    files for each host, files are named provision_settings_{mac}.
    '''
    # clean any old configuration
    remove_files_recurse_by_pattern(path=profile_path, pattern=r'^(.*[0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2})$')

    if 'hosts' in config and config['hosts']:
        variables = global_bmc_and_bios_configuration(config)

        for host in config['hosts']:
            if 'mac' in host:   # no mac -> no special configuration
                host_variables = dict(variables)

                # additional variables, may be more here
                copy = ['name']
                for name in copy:
                    if name in host:
                        host_variables[name] = host[name]

                if 'bmc' in host:
                    host_variables.update(host['bmc'])

                if 'bios' in host:
                    host_variables.update(host['bios'])

                if 'bios' in profile:  # the profile is the most important as selected manually
                    host_variables.update(profile['bios'])

                host_variables = adapt_to_profile(host_variables)

                # Saving file with host parameters (file name: provision_settings_{mac_address})
                path = f"{profile_path}/files/seo/provision_settings_{host['mac'].lower()}"
                seo.shell.create_variables_file(path, host_variables)


def run_main(default_config_path=None, experience_kit_name=""):
    """ Top level script entry function """
    root_path = os.path.dirname(os.path.realpath(__file__))

    default_config_path = (
        os.path.relpath(os.path.join(root_path, "default_config.yml"))
        if default_config_path is None else default_config_path)

    args = parse_args(default_config_path, experience_kit_name)

    try:
        sys.exit(main(args, root_path, default_config_path).value)
    except seo.error.AppException as e:
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        logging.error(e.code if e.msg is None else e.msg)
        sys.exit(e.code.value)


def main(args, root_path, default_config_path):
    """ Internal main function """

    if args.debug:
        log_level = logging.DEBUG
        log_format = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s'
    else:
        log_level = logging.INFO
        log_format = '%(levelname)s: %(message)s'

    logging.basicConfig(level=log_level, format=log_format, datefmt='%Y-%m-%d %H:%M:%S')

    seo.stage.check_stages(args.start_from, STAGES)

    if args.init_config:
        init_config(default_config_path)
        return seo.error.Codes.NO_ERROR

    cfg = seo.config.load_provisioning_cfg(args.config_file, root_path)

    apply_args(cfg, args)

    if args.stop_esp:
        run_esp(cfg, args)
        return seo.error.Codes.NO_ERROR

    if args.force:
        cleanup(cfg)

    if credentials_check_needed():
        check_repositories(cfg, args)

    if preconditions_check_needed():
        check_preconditions(args)

    clone_esp(cfg)
    configure_esp(cfg)
    build_esp(cfg)

    # stage 4a independent from 4b
    if cfg['usb_images']['build'] and args.start_from != 'configure-profiles':
        build_usb_images(cfg)
    else:
        logging.info("Skipping optional stage %s", STAGES['build-usb-images']['display'])

    # stage 4b independent from 4a
    if args.start_from != 'build-usb-images':
        configure_se_profiles(cfg)
    else:
        logging.info("Skipping optional stage %s", STAGES['configure-profiles']['display'])

    if args.run_esp_for_usb_boot or \
       args.run_esp_for_pxe_boot:
        run_esp(cfg, args)

    print_profile_credentials(cfg)

    return seo.error.Codes.NO_ERROR


if __name__ == "__main__":
    run_main()
