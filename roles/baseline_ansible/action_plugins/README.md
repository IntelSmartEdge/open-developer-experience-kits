```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# action_plugins

action_plugins directory contains following action plugins:
- yum.py      -> Updated yum ansible action plugin to enable python3 support for CentOS 7.x
- package.py  -> Updated package ansible action plugin to enable python3 support for CentOS 7.x
- validate_isolcpus.py -> Action plugin to validate isolated CPUs against CPUs available on target system

# Used global variables

Action plugins require following variables to be set:

yum.py and package.py:
- ansible_python_interpreter
It needs to be set to /usr/bin/python3 only on CentOS 7.x when you want to use python3

validate_isolcpus.py:
- isolcpus
- cpus_present


## Configurability

# To enable python3 support for Centos7.x on cluster nodes add following two lines to inventory.ini
[all:vars]
ansible_python_interpreter=/usr/bin/python3

# Path to this action_plugins directory needs to be added to ansible.cfg file

[defaults]
action_plugins=./action_plugins:~/.ansible/plugins/action:/usr/share/ansible/plugins/action


## Installing python3 packages on CentOS 7.x

```
---
# To enable python3 support for Centos7.x on cluster nodes
# install it as a first step
- hosts: all-centos7
  vars:
    ansible_python_interpreter: '/usr/bin/python'
  tasks:
    - name: install python3
      package:
        name:
          - python3
          - libselinux-python3
        state: present
      environment:
        http_proxy: "{{ http_proxy }}"
      when:
        - ansible_os_family == 'RedHat'
        - ansible_distribution_version < '8'
      any_errors_fatal: true

```
