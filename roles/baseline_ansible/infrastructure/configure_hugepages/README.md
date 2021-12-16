```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# configure_hugepages

Configures hugepages in linux kernel.
Configuration is applied via kernel command line arguments.
The input is validated, only one size of hugepages can be applied.
The role checks if `mem_reserved` megabytes of free memory will available on the host with hugepages applied,
and fails if otherwise.

For more information, visit https://www.kernel.org/doc/Documentation/vm/hugetlbpage.txt

Example usage:
```yaml
hugepages_enabled: true
default_hugepage_size: 1G
hugepages_1G: 72
hugepages_2M: 0

# amount of memory "protected" from hugepages allocation in MB
mem_reserved: 1024

```
