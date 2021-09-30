```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2019 Intel Corporation
```

# Troubleshooting

## Couldn't locate the 'docker-compose' command.

The system on which the script was run is missing the docker-compose command. 

See the official Docker documentation for docker compose installation instructions:

https://docs.docker.com/compose/install/

## GitHub token/user not specified

The GitHub token and user name have to be specified in a custom provisioning configuration file or
through the --github-user and --github-token command line options.

The custom provisioning configuration file can be generated using the --init-config option and
later specified to the provisioning script using the --config option.
