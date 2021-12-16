# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

""" Utility functions allowing conditional run of multiple execution stages """

import logging
import pathlib


def stage(stage_name, stages):
    """ Convenient decorator for main stage functions """
    if stage_name not in stages.keys():
        raise ValueError(f"Stage '{stage_name}' not defined.")

    def func_wrapper(func):
        def wrapper(*args, **kwargs):
            if pathlib.Path(stages[stage_name]['status_file']).exists():
                logging.info("Skipping stage %s", stages[stage_name]['display'])
                return None

            logging.info("STAGE: %s", stages[stage_name]['display'])
            res = func(*args, **kwargs)
            # create timestamp file
            pathlib.Path(stages[stage_name]['status_file']).touch()
            return res
        return wrapper
    return func_wrapper


def check_stages(start_from, stages):
    """ Trigger stages rerun """

    # nothing to do if no stage passed on cmd line
    if not start_from:
        return

    def tryint(i):
        # we usually expect int, can be also single char like 'a' or 'b'
        try:
            return int(i)
        except ValueError:
            return i.strip()

    def to_indices(order):
        return [tryint(i)  for i in order.split('.')]

    start_order = to_indices(stages[start_from]['order'])

    # trigger stages rerun by removing status files
    for other_stage_name, other_stage in stages.items():
        other_order = to_indices(other_stage['order'])
        status_file = pathlib.Path(other_stage['status_file'])
        # remove status file for this stage and all beyond, including branches
        if len(start_order) == 1 and start_order[0] <= other_order[0]:
            if status_file.exists():
                logging.info("Will rerun stage %s", other_stage_name)
                status_file.unlink()
        # if we have a split, don't interfere with other branch, but if those branches
        # join back afterwards, remove resulting children and beyond.
        elif len(start_order) == 2:
            if len(other_order) == 1 and start_order[0] < other_order[0] or \
               len(other_order) == 2 and start_order == other_order:
                if status_file.exists():
                    status_file.unlink()
        # TODO: in case more nesting levels than 2 are required, support it here
