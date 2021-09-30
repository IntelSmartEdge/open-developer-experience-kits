```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# os_requirements

os_requirements is a set of roles that configure Operating System requirements.

```bash
.
└── os_requirements
    ├── enable_iptables_bridging
    │   └── tasks
    │       └── main.yml
    ├── disable_swap
    │   └── tasks
    │       └── main.yml
    ├── dns_stub_listener
    │   ├── defaults
    │   │   └── main.yml
    │   └── tasks
    │       └── main.yml
    ├── enable_ipv4_forwarding
    │   └── tasks
    │       └── main.yml
    └── README.md
```

---

## roles in os_requirements

1. enable_iptables_bridging - loads br_netfilter module and configure ip(6)tables rules
2. disable_swap - disables swap permanently
3. dns_stub_listener - applies DNS settings on Ubuntu OSes
4. enable_ipv4_forwarding