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

## Additional exports

```
  roles:
    - role: install_golang
      golang_additional_exports:
        - "export GOPRIVATE=github.com/smart-edge-open"
```