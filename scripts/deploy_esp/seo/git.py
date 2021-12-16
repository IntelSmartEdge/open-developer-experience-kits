# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

""" Git utilities """

import logging
import urllib

import seo.error


def apply_token(url, token):
    """Return the provided url with the user:password part replaced with the given token string"""

    parsed = urllib.parse.urlparse(url)

    if parsed.hostname is None:
        logging.debug(
            "The url ('%s') doesn't contain recognizable host name part (maybe it is missing the schema part?)."
            " The token won't be applied", url)

        return url

    try:
        port = parsed.port
    except ValueError as e:
        raise seo.error.AppException(
            seo.error.Codes.CONFIG_ERROR,
            f"The url ('{url}') contains invalid port number") from e

    if not token and port is None:
        netloc = parsed.hostname
    elif not token:
        netloc = f"{parsed.hostname}:{port}"
    elif port is None:
        netloc = f"{token}@{parsed.hostname}"
    else:
        netloc = f"{token}@{parsed.hostname}:{port}"

    return parsed._replace(netloc=netloc).geturl()
