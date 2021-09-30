```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# build nic drivers

---

This role builds from sources the following drivers:

- `i40e`
- `ice`
- `iavf`

The role requires the following variables to be defined:

- driver_name
- driver_version
- driver_url
- driver_checksum
- current_mgmt_driver

The requirements could be satisfied like:

```yaml
# put the ice_* vars to defaults/main.yml for ease of maintenance
- name: build and load ice driver
  block:
    - name: set facts
      set_fact:
        driver_name: "{{ ice_driver_name }}"
        driver_version: "{{ ice_driver_version }}"
        driver_url: "{{ ice_driver_url }}"
        driver_checksum: "{{ ice_driver_checksum }}"
        current_mgmt_driver: "{{ mgmt_interface_driver }}"

    - name: build ice driver
      include_role:
        name: build_nic_drivers
  when: requested_drivers.ice
```
