# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021-2022 Intel Corporation

""" Error handling related utilities """

import enum


TS_REF = "See the Troubleshooting section of the Intel® Smart Edge Open Provisioning Process document"


class Codes(enum.Enum):
    """ Script exit codes """
    NO_ERROR = 0
    GENERIC_ERROR = 1
    MISSING_PREREQUISITE = 2
    ARGUMENT_ERROR = 3
    CONFIG_ERROR = 4
    RUNTIME_ERROR = 5


class AppException(Exception):
    """
    Exception indicating application error which, if not handled, should result in the
    application exit with the error message printed to the screen
    """
    def __init__(self, code, msg=None):
        super().__init__()
        self.code = code
        self.msg = msg
