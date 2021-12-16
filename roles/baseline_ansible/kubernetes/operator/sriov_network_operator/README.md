```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# Generic role for installing SR-IOV Network Operator

The SR-IOV Network Operator handles provisioning and configuring SR-IOV CNI plugin and Device plugin. It is capable to create VFs from specific PF name or PCI address and resource for kubernetes by `SriovNetworkNodePolicy`, and Network Attachment Definition by `SriovNetwork`.

The SR-IOV Network Operator role is divided to several sub-roles:
- `prepare_node` - node(worker) preparation for Operator
- `install` - for installing Operator via Helm chart
- `configure` - parametrized sub-role for applying `SriovNetworkNodePolicy` and `SriovNetwork` via variables.

# Role specific variables

## Role requires following variables to be set:

### Global variables:
- `project_dir` - stores main project directory

### prepare_node sub-role:
- `reference_host` - host which is kubernetes controller

### install sub-role:
There are not required variables to be set.

### configure sub-role:

Below lists of dictionaries can be defined in global vars file e.g. in `group_vars` of specific flavor.

**SriovNetworkNodePolicies:**

Variable `sriov_network_node_policies` is a list of dictionaries which contains fields for CR `SriovNetworkNodePolicy` to be applied.
Mandatory keys which should be defined:

```yaml
sriov_network_node_policies:
  - name: # SriovNetworkNodePolicy identify name
    resource_name: # resource name for sriov device plugin mapped from given pf_name
    num_vfs: # number VFs to be crated from given PF name
## Optional keys:
    hostname: # hostname on which creates VFs from given parameters
    priority: # set priority for VFS
    mtu: # set mtu for VFS
    ## values which applies for created resource
    vendor: # Vendor id -for default "8086" for Intel is set
    device_id: # device id e.g. "154c"
    pf_names: # list of PF name/s from which creates VFs and maps the resource
    root_devices: # list with PCI address of device/s
    device_type: # two values are supported `netdevice` for default VFs driver and `vfio-pci` for VF to be bound - default value if not defined is "netdevice"
    is_rdma: # Whether to enable remote direct memory access (RDMA) mode
    link_type: # The link type for the VFs
```
> **NOTE:** Keys `pf_names` and `root_devices` are defined as optional but for proper VFs configuration at least one of keys should be created. For minimum defined sample `SriovNetworkNodePolicy` please refer to role defaults - `./configure/defaults/main.yml`.

> **NOTE:** more details about these parameters [link](https://docs.openshift.com/container-platform/4.7/networking/hardware_networks/configuring-sriov-device.html#configuring-sriov-device)


**SriovNetwork:**

Variable `sriov_networks` is a list of dictionaries which contains fields for CR `SriovNetwork` to be applied.
Mandatory keys which should be defined:

```yaml
sriov_networks:
  - name: # SriovNetwork identify name
    resource_name: # sriov device plugin resource name for which Network Attachment Definition maps
    network_namespace: # namespace for Network Attachment Definition
## Optional keys:
    vlan: # set vlan
    ipam: # set ipam
    link_state: # set linke_state
    max_tx_rate: # set max TX rate
    min_tx_rate: # set min TX rate
    vlan_qos: # set vlan QOS
    trust_vf: # set trust VF
    capabilities: # set capabilities
```

> **NOTE:** For minimum defined sample `SriovNetwork` please refer to role defaults - `./configure/defaults/main.yml`.

> **NOTE:** more details about these parameters [link](https://docs.openshift.com/container-platform/4.7/networking/hardware_networks/configuring-sriov-net-attach.html)

If `SriovNetwork` is applied to some custom non existing namespace/s, this role is capable to create required namespace/s based on unique list of all `network_namespace` values.
