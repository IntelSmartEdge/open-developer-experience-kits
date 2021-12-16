#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

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
import tempfile
import traceback
import urllib.parse

import seo.error
import seo.git
import seo.stage


_GH_TOKEN_OPT = "--github-token" # nosec - B105 (Possible hardcoded password)
_GH_USER_OPT = "--github-user"
_TS_REF = "See the Troubleshooting section of the Intel® Smart Edge Open Provisioning Process document"


_CONNECTIVITY_TEST_TIMEOUT = 60 # seconds
_CONNECTIVITY_TEST_IMAGE = "alpine:3.13"

try:
    import yaml
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: Couldn't import yaml module.\n"
        "   It can be installed using following command:\n"
        "   $ pip3 install pyyaml\n")
    sys.exit(seo.error.Codes.MISSING_PREREQUISITE)

# ---------- UTILS ----------

# https://github.com/yaml/pyyaml/issues/234
class Dumper(yaml.Dumper):  # pylint: disable=too-many-ancestors
    """ Custom dumper to keep proper indentation level """
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


def is_profile_bare_os(profile):
    """ Check if profile is set up as bare os profile """
    # bare_os field is optional
    return 'bare_os' in profile and profile['bare_os'] is True

# ---------------------------------

SCENARIOS = ["single-node", "multi-node"]
DISTROS = ['centos', 'rhel', 'ubuntu']

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
            media preparation, and the deployment of cluster nodes on selected machines.
            For details see the scripts/deploy_esp/README.md document""")
    p.add_argument(
        "--init-config", action="store_true",
        help="generate default provisioning configuration and print it to the standard output")
    p.add_argument(
        "-c", "--config", action="store", dest="config_file", metavar="PATH",
        default=default_config_path,
        help="provisioning configuration file PATH (default: %(default)s)")
    p.add_argument(
        _GH_USER_OPT, action="store", dest="github_user", metavar="NAME",
        help="NAME of the GitHub user to be used to clone required Smart Edge Open repositories")
    p.add_argument(
        _GH_TOKEN_OPT, action="store", dest="github_token", metavar="VALUE",
        help="GitHub token to be used to clone required Smart Edge Open repositories")
    p.add_argument(
        "--dockerhub-user", action="store", dest="dockerhub_user", metavar="NAME",
        help="NAME of the user to authenticate with DockerHub during Live System stage")
    p.add_argument(
        "--dockerhub-pass", action="store", dest="dockerhub_pass", metavar="VALUE",
        help="Password used to authenticate with DockerHub during Live System stage")
    p.add_argument(
        "--registry-mirror", action="store", dest="registry_mirror", metavar="URL",
        help="add the URL to the list of local Docker registry mirrors")
    p.add_argument(
        "--start-from", action="store", help="restart build process from selected phase",
        choices=STAGES.keys())
    p.add_argument("--run-esp-for-usb-boot", action="store_true", default=False,
                   help="start ESP services for booting from USB image")
    p.add_argument("--run-esp-for-pxe-boot", action="store_true", default=False,
                   help="start ESP services for booting from PXE")
    p.add_argument("--stop-esp", action="store_true", default=False,
                   help="stop ESP services")
    p.add_argument(
        "--debug", action="store_true", dest="debug",
        help="provide more verbose diagnostic information")
    p.add_argument(
        "--cleanup", action="store_true", dest="force",
        help="cleanup existing build artifacts before taking any other actions (stop the services if needed)")
    return p.parse_args()


def init_config(default_config_path):
    """ Dump content of the default configuration file to the screen (standard output) """

    with open(default_config_path) as cfg_file:
        for line in cfg_file:
            sys.stdout.write(line)

    logging.info("Provisioning configuration generated")


def get_config(config_file_path):
    """ Read and parse given provisioning config file """

    logging.debug("Trying to read and parse provisioning configuration file ('%s')", config_file_path)

    try:
        with open(config_file_path) as config_file:
            raw_config = config_file.read()
    except (FileNotFoundError, PermissionError) as e:
        raise seo.error.AppException(
            seo.error.Codes.ARGUMENT_ERROR,
            f"Failed to load the config file: {e}") from e

    try:
        return yaml.safe_load(raw_config)
    except yaml.YAMLError as e:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Config file format error: {e}") from e


def apply_args(cfg, args):
    """ Overwrite loaded configuration with applicable command line arguments (if specified) """

    if args.github_user is not None:
        cfg.setdefault("github", {})["user"] = args.github_user

    if args.github_token is not None:
        cfg.setdefault("github", {})["token"] = args.github_token

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
        the provided GitHub credentials allow to access it. In case of
        the access failure raise the application exception
    """

    if is_repo_accessible(url, args):
        logging.info("%s repository is public: %s", desc, url)
        return

    logging.debug("%s repository is not public: %s", desc, url)

    if not config['github']['user']:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either, the {desc} repository is private and requires the github user to be specified using the"
            f" {_GH_USER_OPT} option, or the repository url ('{url}') is incorrect")
    if not config['github']['token']:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either the {desc} repository is private and requires the github token to be specified using the"
            f" {_GH_TOKEN_OPT} option, or the repository url ('{url}') is incorrect")

    auth_url = seo.git.apply_token(url, "{0}:{1}".format(config['github']['user'], config['github']['token']))

    if not is_repo_accessible(auth_url, args):
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"Either the {desc} repository url ('{url}') or the provided github credentials are incorrect")

    logging.info(
        "%s repository is private and the %s's credentials are working: %s",
        desc, config['github']['user'], url)


def verify_esp_path_length(dest_path):
    """
    The ESP repository destination directory path mustn't be too long to not hit the unix socket path limit within the
    ESP code.

    See ESS-3861 and https://man7.org/linux/man-pages/man7/unix.7.html
    """

    expected_socket_path = os.path.join(
        os.path.realpath(os.path.abspath(dest_path)),
        "data/tmp/build/docker.sock")

    # How the limit was calculated:
    # For a path of length 107 following error could be seen in the builder.log:
    #     Cannot connect to the Docker daemon at unix:////[...]/docker.sock. Is the docker daemon running?
    # For a path of length greater than 107 following error could be seen in the builder.log:
    #     Unix socket path "//[...]/docker.sock" is too long

    diff = len(expected_socket_path) - 106

    if diff > 0:
        diff_str = "1 character" if diff == 1 else f"{diff} characters"

        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            "The ESP destination directory path is too long.\n"
            f"    Please make the following path shorter by at least {diff_str} to be able to proceed:\n"
            f"    {expected_socket_path}\n"
            f"    {_TS_REF}")


def validate_config(config):
    """ Perform some basic sanity check of provided user config """

    logging.debug("Validating the provisioning configuration")

    # Check correctness of first 2 levels of config nesting (missing sections, missing fields,
    #  incorrect types):

    assert isinstance(config, dict) # nosec B101 - used just for development

    # NOTE: We should use some YAML schema validation library for most of these checks

    for main_section in ('github', 'esp', 'profiles', 'dnsmasq', 'usb_images', 'ntp_server', 'docker'):
        if main_section not in config:
            raise seo.error.AppException(
                seo.error.Codes.CONFIG_ERROR,
                f"The provisioning configuration file is missing the '{main_section}' section")

    for main_section in ('github', 'esp', 'dnsmasq', 'usb_images', 'docker'):
        if not isinstance(config[main_section], dict):
            raise ValueError(f"Config: section '{main_section}' must be a dictionary")

    if not isinstance(config['ntp_server'], str):
        raise ValueError("Config: section 'ntp_server' must be a string")

    if not isinstance(config['docker']['registry_mirrors'], list):
        raise ValueError("Config: section 'docker.registry_mirrors' must be a list of strings")

    if not isinstance(config['docker']['dockerhub'], dict):
        raise ValueError("Config: section 'docker.dockerhub' must be a dictionary")

    if not isinstance(config['docker']['dockerhub']['username'], str):
        raise ValueError("Config: section 'docker.dockerhub.username' must be a string")

    if not isinstance(config['docker']['dockerhub']['password'], str):
        raise ValueError("Config: section 'docker.dockerhub.password' must be a string")

    if not isinstance(config['profiles'], list):
        raise ValueError("Config: section 'profiles' must be a list")

    for field in ('token', 'user'):
        if field not in config['github']:
            raise seo.error.AppException(
                seo.error.Codes.CONFIG_ERROR,
                "The 'githhub' section of the provisioning configuration file is missing the"
                f"'{field}' field")

    for field in ('url', 'branch', 'dest_dir'):
        if field not in config['esp']:
            raise ValueError(f"Config: section 'esp' is missing field '{field}'")

    verify_esp_path_length(config["esp"]["dest_dir"])

    for field in ('build', 'bios', 'efi', 'all_in_one', 'output_path'):
        if field not in config['usb_images']:
            raise ValueError(f"Config: section 'usb_images' is missing field '{field}'")

    if 'enabled' not in config['dnsmasq']:
        raise ValueError("Config: section 'dnsmasq' is missing field 'enabled'")

    # ---- do a couple of more checks (common mistakes)

    if not config['profiles']:
        raise ValueError("Config: You must define at least a single profile")

    # some fields in profiles are mandatory, while others are optional
    for idx, profile in enumerate(config['profiles']):
        for field in ('name', 'url', 'branch', 'scenario'):
            if field not in profile:
                raise ValueError(f"Config: profile no.{idx+1} is missing field '{field}'")

        if profile['scenario'] not in SCENARIOS:
            raise ValueError(
                f"Config: Invalid scenario: {profile['scenario']}. Possible options: {SCENARIOS}")

        if is_profile_bare_os(profile):
            redundant = []
            for field in ('experience_kit', 'group_vars', 'host_vars', 'sideload'):
                if field in profile:
                    redundant.append(field)
            if redundant:
                raise ValueError(f"Config: profile no.{idx+1} (bare_os) has redundant fields: {', '.join(redundant)}")
        else:
            if 'experience_kit' not in profile:
                raise ValueError(f"Config: profile no.{idx+1} is missing field 'experience_kit'")

            if not isinstance(profile['experience_kit'], dict):
                raise ValueError(f"Config: profile no.{idx+1} section 'experience_kit' must be a dictionary")

            for field in ('url', 'branch', 'deployment'):
                if field not in profile['experience_kit']:
                    raise ValueError(f"Config: profile no.{idx+1} is missing field 'experience_kit.{field}'")

        # Check secure boot profile options
        if 'bmc' in profile:
            bmc = profile['bmc']
            if not isinstance(bmc, dict):
                raise ValueError("Config: section 'bmc' must be a dictionary")

            # check all required fields
            fields = [
                ('secure_boot', bool),
                ('tpm', bool),
                ('address', str),
                ('user', str),
                ('password', str)
            ]
            for field, type_ in fields:
                if field not in bmc or not isinstance(bmc[field], type_):
                    raise ValueError(f"Config: Profile '{profile['name']}' "
                                     f"is missing field 'bmc.{field}' of type {type_.__name__}")

            # check if user forgot to fill ip and credentials
            if bmc['secure_boot'] or bmc['tpm']:
                for field in ('address', 'user', 'password'):
                    if bmc[field] == '':
                        raise ValueError(f"Config: Profile '{profile['name']}' has field 'bmc.{field}' "
                                         "that cannot be empty")


def check_repositories(config, args):
    """Check if all the repositories occurring in the configuration file are accessible using given configuration"""

    verify_repo_status("ESP", config["esp"]["url"], config, args)
    for profile in config['profiles']:
        verify_repo_status("ESP Profile", profile["url"], config, args)
        if not is_profile_bare_os(profile):
            verify_repo_status("Experience Kit", profile["experience_kit"]["url"], config, args)


def check_rpm_package(pkgname, friendly_name):
    """ Check if RPM package is installed """

    cmd = ["rpm", "--quiet", "-q", pkgname]
    proc = subprocess.run( # nosec - B603 (subprocess call)
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=False)
    if proc.returncode == 0:
        return True
    else:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"{friendly_name} has to be installed on this machine for the provisioning process to succeed.\n"
            f"    {_TS_REF}")


def check_apt_package(pkgname, friendly_name):
    """ Check if APT-GET package is installed """

    cmd = ["apt", "-qq", "list", pkgname]
    proc = subprocess.run( # nosec - B603 (subprocess call)
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=False)
    if proc.returncode == 0 and '[installed]' in proc.stdout:
        return True
    else:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"{friendly_name} has to be installed on this machine for the provisioning process to succeed.\n"
            f"    {_TS_REF}")


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

    # check if docker is installed
    if distro in ("rhel", "centos"):
        check_rpm_package("docker-ce", "Docker")
        check_rpm_package("docker-ce-cli", "Docker CLI")
        check_rpm_package("containerd.io", "The containerd.io runtime")
    elif distro == "ubuntu":
        check_apt_package("docker-ce", "Docker")
        check_apt_package("docker-ce-cli", "Docker CLI")
        check_apt_package("containerd.io", "The containerd.io runtime")

    # hint about docker autostart
    cmd = "systemctl list-unit-files | grep docker.service | awk '{print $2}'"
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                          shell=True, check=False) # nosec - B602
    if proc.returncode == 0 and proc.stdout.strip() == 'disabled':
        logging.warning("Docker package is not configured to run at system boot. "
                        "Enable it with 'systemctl enable docker --now'")

    # check if docker-compose is installed (local, not rpm, as we need newer version than available in repo)
    pkgname = 'docker-compose'
    if shutil.which(pkgname) is None:
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            "The docker-compose tool has to be installed on this machine for the provisioning process to succeed.\n"
            f"    {_TS_REF}")

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
            raise seo.error.AppException(seo.error.Codes.MISSING_PREREQUISITE,
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
                    f"    {_TS_REF}")
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


def configure_se_profile_group_vars_all(cfg, profile_path):
    """ Configure profile's group_vars/all.yml file based on config variables and env vars """

    all_vars = {}
    all_vars['git_repo_token'] = cfg['github']['token']

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
        output = yaml.dump(body, Dumper=Dumper, default_flow_style=False)
        # since we already dumped some vars to all.yml, append in that case
        if name == 'all':
            mode = 'a'
        else:
            mode = 'w'
        open(profile_path / "files/seo" / seo_path, mode).write(output)


def configure_se_profile_config_yaml(config, profile, profile_path):
    """ Configure profile's conf/config.yml file, which contain kernel parameters """

    with open(profile_path / "conf/config.yml", "r+") as f:
        content = f.read()

        if 'account' in profile and \
            'username' in profile['account'] and \
            'password' in profile['account']:
            content = re.sub(
                r'username=([^\s]+)', f"username={profile['account']['username']}", content)
            content = re.sub(
                r'password=([^\s]+)', f"password={profile['account']['password']}", content)

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


def configure_se_profile_provision_settings(config, profile, profile_path):
    """ Configure profile's provision_settings file """

    with open(profile_path / "files/seo/provision_settings", "r+") as f:
        content = f.read()

        content = re.sub(
            r'scenario=(.*)', f"scenario={profile['scenario']}", content)
        content = re.sub(
            r'gh_token=(.*)', f"gh_token={config['github']['token']}", content)
        if 'controlplane_mac' in profile and profile['controlplane_mac']:
            content = re.sub(
                r'controller_mac=(.*)', f"controller_mac={profile['controlplane_mac']}", content)

        # first clean any leftovers
        content = re.sub(r'redfish_ip=(.*)', "redfish_ip=", content)
        content = re.sub(r'redfish_user=(.*)', "redfish_user=", content)
        content = re.sub(r'redfish_password=(.*)', "redfish_password=", content)
        # now dump current data
        if 'bmc' in profile:
            bmc = profile['bmc']

            sb_value = str(bmc['secure_boot']).lower()
            tpm_value = str(bmc['tpm']).lower()
            content = re.sub(
            r'enable_secure_boot=(.*)', f"enable_secure_boot={sb_value}", content)
            content = re.sub(
            r'enable_tpm=(.*)', f"enable_tpm={tpm_value}", content)

            if bmc['secure_boot'] or bmc['tpm']:
                content = re.sub(r'redfish_ip=(.*)', f"redfish_ip={bmc ['address']}", content)
                content = re.sub(r'redfish_user=(.*)', f"redfish_user={bmc ['user']}", content)
                content = re.sub(r'redfish_password=(.*)', f"redfish_password={bmc ['password']}", content)
        else:
            content = re.sub(
            r'enable_secure_boot=(.*)', "enable_secure_boot=false", content)
            content = re.sub(
            r'enable_tpm=(.*)', "enable_tpm=false", content)

        if not is_profile_bare_os(profile):
            ek_url = profile['experience_kit']['url'].replace('https://', '').replace('http://', '')
            content = re.sub(
                r'url=(.*)', f"url={ek_url}", content)
            content = re.sub(
                r'flavor=(.*)', f"flavor={profile['experience_kit']['deployment']}", content)
            content = re.sub(
                r'branch=(.*)', f"branch={profile['experience_kit']['branch']}", content)

            # first remove all previous sideload definitions
            content = re.sub(
                r'^files\[(.*)\]=(.*)[\r\n]', '', content, flags=re.MULTILINE)
            if 'sideload' in profile and profile['sideload'] is not None:
                for item in profile['sideload']:
                    filename = os.path.basename(item['file_path'])
                    sideload_filepath = profile_path / "files/seo/sideload" / filename
                    # copy file to sideload dir, replacing a previous one if existing
                    shutil.copyfile(item['file_path'], sideload_filepath)
                    # append sideload definition
                    content += 'files["{0}"]="{1}"\n'.format(filename, item['dest_path'])

        f.seek(0)
        f.write(content)
        f.truncate()


@seo.stage.stage('configure-profiles', STAGES)
def configure_se_profiles(config):
    """ Configure Smart Edge profiles """

    esp_path = pathlib.Path(config['esp']['dest_dir'])
    for profile in config['profiles']:
        profile_path = esp_path / f"data/usr/share/nginx/html/profile/{profile['name']}"
        configure_se_profile_provision_settings(config, profile, profile_path)
        if not is_profile_bare_os(profile):
            configure_se_profile_group_vars_all(config, profile_path)
            configure_se_profile_customize_vars(profile, profile_path)


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

    token = config['github']['token']
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

    def __make_cmd(token):
        return ["git", "clone", seo.git.apply_token(esp_config['url'], token), "--branch", esp_config['branch'], dest]

    cmd_actual = __make_cmd(token)
    cmd_anonym = __make_cmd("<github-token>") if token else cmd_actual

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
            'git_username': config['github']['user'],
            'git_token': config['github']['token'],
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

# ---------------------------------------------

def run_main(default_config_path=None, experience_kit_name=""):
    """ Top level script entry function """
    default_config_path = os.path.relpath(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "default_config.yml")) if default_config_path is None else default_config_path

    args = parse_args(default_config_path, experience_kit_name)

    try:
        sys.exit(main(args, default_config_path).value)
    except seo.error.AppException as e:
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        logging.error(e.code if e.msg is None else e.msg)
        sys.exit(e.code.value)


def main(args, default_config_path):
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

    cfg = get_config(args.config_file)
    validate_config(cfg)
    apply_args(cfg, args)
    check_repositories(cfg, args)
    check_preconditions(args)

    if args.force:
        cleanup(cfg)

    if args.stop_esp:
        run_esp(cfg, args)
        return seo.error.Codes.NO_ERROR

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

    return seo.error.Codes.NO_ERROR


if __name__ == "__main__":
    run_main()
