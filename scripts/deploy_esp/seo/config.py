# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021-2022 Intel Corporation

""" Provisioning configuration handling related utilities. """

import json
import logging
import os.path
import importlib.util
import sys

import jsonschema

import seo.error
import seo.yaml


def validate(config, config_path, schema):
    """ Validate the provisioning configuration data using the provided schema

        The config_path parameter serves the error message composition purposes only
    """
    validator = jsonschema.Draft7Validator(schema,
            format_checker=jsonschema.draft7_format_checker)

    if validator.is_valid(config):
        return

    msg = [f"The provisioning configuration file ('{config_path}') validation failed:"]

    for error in validator.iter_errors(config):
        node = '/'.join([str(p) for p in error.path])
        msg += [
            f"    {node}:",
            f"        {error.message}"]

    msg.append(f"    {seo.error.TS_REF}")

    raise seo.error.AppException(seo.error.Codes.CONFIG_ERROR, "\n".join(msg))


def load_provisioning_cfg(config_path, root_path):
    """ Load and validate specified provisioning configuration file

        Params:
            config_path - path to the configuration file to be handled
            root_path - path to the shared provisioning script root directory (the one containing the 'deploy_esp.py'
                script and the 'seo' python module)
    """

    cfg = seo.yaml.load(config_path)
    schema_path = os.path.join(root_path, "config_schema.json")
    schema = json.load(open(schema_path))

    # for checking valid hostname
    if not importlib.util.find_spec("fqdn"):
        sys.stderr.write(
        "ERROR: Couldn't import fqdn module.\n"
        "   It can be installed using following command:\n"
        "   $ pip3 install fqdn\n")
        sys.exit(seo.error.Codes.MISSING_PREREQUISITE)

    # Fundamental schema validation:
    validate(cfg, config_path, schema)

    # Extended validation:
    verify_esp_path_length(cfg["esp"]["dest_dir"])

    logging.debug("The provisioning configuration file ('%s') is valid", config_path)
    return cfg


def verify_esp_path_length(dest_path):
    """The ESP repository destination directory path mustn't be too long to not hit the unix socket path limit within
       the ESP code.

       See: ESS-3861 and https://man7.org/linux/man-pages/man7/unix.7.html
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
            f"    {seo.error.TS_REF}")
