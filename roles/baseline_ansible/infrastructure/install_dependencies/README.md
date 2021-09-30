```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# install_dependencies module

install_dependencies module expects role specific install_dependencies variable in following format.
Sections are present only when needed.

It was enhance with option which enables forced installation of excluded packages. It is mostly used
for installation of kernel dependencies like kernel-devel and so on.
It should not be used for installation of kernel itself !!!


## Structure of install_dependencies:

It contain two hierarchical levels:
1. The first level is for ansible_os_family. In example bellow it is for 'RedHat:' and 'Debian:'
Each section contain list of packages common for corresponding os_family and subsections for distribution/version specific packages.

2. The second level covers all subsections, Following subsections can be defined:
   - distribution specific packages. Section header contains ansible_distribution. 
     In example bellow it is '- RedHat:' and '- CentOS:'
   - major version specific packages. Section header contains ansible_distribution + '_' + ansible_distribution_major_version.
     In example bellow it is '- CentOS_7:'
   - version specific packages. Section header contains ansible_distribution + '_' + ansible_distribution_version, where are '.' replaced with '_'.
     In example bellow it is '- CentOS_7_9:' and '- RedHat_8_3:'


## Example of install_dependencies definition for role in vars/main.yml

```
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

---
install_dependencies:
  RedHat:
      - tuna
      - tuned-profiles-realtime
      - CentOS_7:
        - tuned-profiles-nfv
        - tuned-profiles-nfv-host
        - tuned-profiles-nfv-guest
      - RedHat_8_3:
        - vim
      - CentOS_7_9:
        - vim
      - CentOS:
        - pciutils
      - RedHat:
        - tcpdump
  Debian: []
```


## Example how to used forced installation of excluded packages inside role

vars/main.yml defined above needs to be enhance with role specific variable which contains 
list of excluded packages to be installed

E.g.:
```
install_kernel_dependency_yum:
  - kernel-devel
```

Then install_dependencies role needs to be included like this:

```
- name: install dependencies
  include_role:
    name: infrastructure/install_dependencies
  vars:
    install_excluded_packages: "{{ install_kernel_dependency_yum }}"
```
