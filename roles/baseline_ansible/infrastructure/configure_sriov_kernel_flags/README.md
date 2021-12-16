```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# configure_cpu_idle_driver

Configures linux kernel iommu via kernel command line argument.
Adds `intel_iommu=on iommu=pt` to kernel command line.

For more information, visit https://software.intel.com/content/www/us/en/develop/download/intel-virtualization-technology-for-directed-io-architecture-specification.html

Example usage:
```yaml
iommu_enabled: true
```
