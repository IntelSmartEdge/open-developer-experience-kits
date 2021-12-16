# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

""" python script for validate isolcpus """
from ansible.plugins.action import ActionBase

def parse_range(cpu_range):
    """Create cpu range object"""
    if '-' in cpu_range:
        [x, y] = cpu_range.split('-')  # pylint: disable=invalid-name
        cpus = range(int(x), int(y)+1)
        if int(x) >= int(y):
            raise ValueError("incorrect cpu range: " + cpu_range)
    else:
        cpus = [int(cpu_range)]
    return cpus

def parse_cpu_ranges(isolcpus):
    """Create isolated cpu object"""
    ranges = isolcpus.split(',')
    isolated = []
    for r in ranges:  # pylint: disable=invalid-name
        isolated += parse_range(r)
    return isolated

class ActionModule(ActionBase):
    """Base Class"""
    def run(self, tmp=None, task_vars=None):
        """Script entry function"""
        if task_vars is None:
            task_vars = dict()
        result = super(ActionModule, self).run(tmp, task_vars)  # pylint: disable=super-with-arguments
        result['changed'] = False
        result['failed'] = False

        requested = task_vars['isolcpus']
        present = task_vars['cpus_present']

        try:
            all_cpus = parse_cpu_ranges(present)
            isolcpus = parse_cpu_ranges(requested)
            for cpu in isolcpus:
                if cpu not in all_cpus:
                    raise ValueError("requested isolated cpu is not available on the system: "
                    + str(cpu))
        except Exception as e:  # pylint: disable=invalid-name disable=broad-except
            result['failed'] = True
            result['msg'] = str(e)

        return result
