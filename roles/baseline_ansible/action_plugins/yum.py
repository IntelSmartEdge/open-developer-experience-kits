# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

""" yum module wrapper for handling python3 support on CentOS 7.x and RHEL 7.x.

To enable usage of  python3 interpreter globaly we need to fall back to python2 for yum module,
which is not available for python3
Additional task_vars:
    ansible_python_interpreter -- set to /usr/bin/python if ansible_os_family is Redhat
                                  and os version is less than 8
"""



from __future__ import (absolute_import, division, print_function)
__metaclass__ = type # pylint: disable=invalid-name

from ansible.plugins.action import ActionBase
from ansible.utils.display import Display

display = Display() # pylint: disable=invalid-name


class ActionModule(ActionBase):
    """yum action plugin wrapper handling python3 support on CentOS 7.x and RHEL 7.x"""

    def run(self, tmp=None, task_vars=None):
        '''
        Action plugin wrapper for yum action plugin.

        Prepares support for python3 on CentOS 7.x and RHEL 7.x, where ansible yum module
        is not available.
        Since the Ansible module for yum call python APIs natively on the
        backend, we need to handle this here and execute on the remote system.
        '''

        print("  yum action plugin wrapper was called")
        del tmp  # tmp no longer has any effect

        # Add/Change ansible_python_interpreter to python2 for CentOS 7.x and RHEL 7.x
        # pylint: disable=f-string-without-interpolation
        is_redhat_family_7 = \
            self._templar.template("{{ (ansible_os_family == 'RedHat' and "
                                   "ansible_distribution_version < '8') | bool }}")
        if is_redhat_family_7:
            if 'ansible_python_interpreter' in task_vars:
                display.vv(f"Original ansible_python_interpreter: "
                           f"{task_vars['ansible_python_interpreter']}")
            task_vars['ansible_python_interpreter'] = "/usr/bin/python"
            display.vv(f"Updated ansible_python_interpreter: "
                       f"{task_vars['ansible_python_interpreter']}")


        command_action = \
            self._shared_loader_obj.action_loader.get('ansible.builtin.yum',
                                             task=self._task,
                                             connection=self._connection,
                                             play_context=self._play_context,
                                             loader=self._loader,
                                             templar=self._templar,
                                             shared_loader_obj=self._shared_loader_obj)
        result = command_action.run(task_vars=task_vars)

        return result
