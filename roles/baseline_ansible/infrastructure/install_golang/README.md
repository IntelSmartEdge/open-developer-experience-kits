```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# Used global variables

Role requires following variables to be set:

- number_of_retries
- retry_delay
- project_dir
- project_user
- project_group

# Configurability

## Installing additional packages

```
  roles:
    - role: install_golang
      golang_packages: 
        - { url: 'golang.org/x/tools/cmd/godoc', min_golang_version: '1.13' }
        - { url: 'github.com/cloudflare/cfssl/cmd/cfssl' }
        - { url: 'github.com/cloudflare/cfssl/cmd/cfssljson' }
```

## Offline installation

```
  roles:
    - role: install_golang
      offline_role: "{{ offline_enable | default(False) and ('controller_group' in group_names or single_node_deployment) }}"
      offline_golang_url: "https://{{ hostvars[groups['controller_group'][0]]['ansible_host'] }}"
      offline_gomod_url: https://{{ hostvars[groups['controller_group'][0]]['ansible_host'] }}"
```

## Additional exports

```
  roles:
    - role: install_golang
      golang_additional_exports:
        - "export GOPRIVATE=github.com/smart-edge-open"
```