# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

""" Git utilities """

import urllib


def apply_credentials(url, username, password):
    """Return the provided url with the user:password part replaced with the given username and password"""

    p = urllib.parse.urlparse(url)

    netloc = p.netloc.split('@')[-1]

    if username and password:
        c = f"{username}:{password}"
    else:
        c = f"{username or ''}{password or ''}"

    if c:
        p = p._replace(netloc=f"{c}@{netloc}")

    return p.geturl()
