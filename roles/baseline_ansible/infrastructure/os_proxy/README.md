```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

# os_proxy

os_proxy is an OS agnostic role that configures system proxy (other components should set their proxy if needed).

## configuration

Proxy settings are stored in */etc/environment* and *~/.bashrc* and are provided in the variable:
```python
proxy_env:
  http_proxy: str
  https_proxy: str
  ftp_proxy: str
  no_proxy: str
```
