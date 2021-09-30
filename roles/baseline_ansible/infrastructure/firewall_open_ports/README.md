```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

## firewall

---

1. Role `firewall_prepare` must be included before any port openings in a playbook.
The `use_firewall=true` variable needs to be specified to include firewall usage. By default firewall will **not** be used.

2. If the firewall is in use, roles should not open ports directly. The `firewall_open_ports` role should be called instead.
Ports that need to be open must be declared as list of ports and named `fw_open_ports`.

Examples:

```yaml
file_path: role_name/vars/main.yml

---
fw_open_ports:
  - 10250/tcp
  - 30000:32767/tcp # open range of ports
  - 8285/udp
  - 8472/udp # open single port
```

or

```yaml
file_path: role_name/vars/main.yml

---
list_of_ports:
  node_selector:
    - PORT:PORT/PROTOCOL  # open range of ports
    - PORT/PROTOCOL  # open single port
```

```yaml
- name: open required ports
  include_role:
    name: infrastructure/firewall_open_ports
  when: use_firewall | default(false)
  vars:
    fw_open_ports: "{{ list_of_ports['node_selector'] }}"
```
