```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# configure_cpu_isolation

Configure thread affinity for IRQ and kthread processing and removes specified CPUs from the kernel scheduler.
Configuration is applied via kernel command line arguments.
The input is validated.

For more information, visit https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.htm

Example usage:
```yaml
# isolcpus_enabled controls the CPU isolation mechanisms configured via grub command line.
isolcpus_enabled: true
# isolcpus is parameter for isolcpus, rcu_nocbs, nohz_full kernel command line arguments.
# For more information visit https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.htm
# This variable is required.
isolcpus: 4-48

# os_cpu_affinity_cpus pins the kthread and irq processing to selected cores using kthread_cpus and irqaffinity
# kernel command line arguments.
# For more information visit https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.htm
# Does nothing when empty.
os_cpu_affinity_cpus: "0-3"

# Autogenerate isolated cores based on `cmk_exclusive_num_cores` when `cmk_enabled=true`.
autogenerate_isolcpus: false
```
