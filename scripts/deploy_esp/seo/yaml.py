# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021-2022 Intel Corporation

""" YAML data utilities """

import logging
import sys

import seo.error

try:
    import yaml
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: Couldn't import yaml module.\n"
        "   It can be installed using following command:\n"
        "   $ pip3 install pyyaml\n")
    sys.exit(seo.error.Codes.MISSING_PREREQUISITE)


def load(file_path):
    """ Read and parse given yaml file """

    logging.debug("Trying to read and parse yaml file ('%s')", file_path)

    try:
        with open(file_path) as input_file:
            raw_data = input_file.read()
    except (FileNotFoundError, PermissionError) as e:
        raise seo.error.AppException(
            seo.error.Codes.RUNTIME_ERROR,
            f"Failed to load the {file_path} YAML file: {e}") from e

    try:
        return yaml.safe_load(raw_data)
    except yaml.YAMLError as e:
        raise seo.error.AppException(
            seo.error.Codes.RUNTIME_ERROR,
            f"Failed to parse the {file_path} YAML file: {e}") from e
