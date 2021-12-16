```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# configure_cpu_idle_driver

Confiure cpu idle driver via kernel command line argument.
The input is validated.

For more information, visit https://www.kernel.org/doc/html/v5.0/admin-guide/pm/cpuidle.html#idle-states-control-via-kernel-command-line

Example usage:
```yaml
cpu_idle_driver_setup_enabled: true
cpu_idle_driver: poll
```
