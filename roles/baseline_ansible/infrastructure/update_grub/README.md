```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# update_grub

Reconfigures kernel command line arguments based on /etc/default/grub.

Requires defined `restart` handler, e.g.:

```yaml
  handlers:
    - name: reboot server
      reboot: { reboot_timeout: 1200 }
      become: yes
```

Example usage:
```yaml
additional_grub_parameters_enabled: true
additional_grub_parameters: "mce=off"
```
