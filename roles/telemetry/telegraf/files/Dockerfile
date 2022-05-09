# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

ARG TELEGRAF_TAG
FROM telegraf:$TELEGRAF_TAG AS builder

RUN apk update && \
    apk add --update --no-cache \
    build-base=~0.5 \
    bash=~5.1 \
    sudo=~1.9 \
    git=~2.34 \
    alpine-sdk=~1.0 \
    libffi-dev=~3.4 \
    openssl-dev=~1.1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR "/telegraf_docker/"

COPY ./images/telegraf/script/install_intel_cmt_cat.sh ./

RUN ./install_intel_cmt_cat.sh

# Build final image where telegraf is running.
FROM alpine:3.15.0

RUN export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" && \
    apk update && \
    apk add --update --no-cache \
    util-linux=~2.37 \
    bash=~5.1 \
    sudo=~1.9 \
    smartmontools=~7.2 \
    nvme-cli=~1.16 \
    rasdaemon=~0.6 \
    iptables=~1.8 \
    ipmitool=~1.8 \
    su-exec=~0.2 \
    iputils=~20210722 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR "/telegraf_docker/"

COPY ./images/telegraf/script/sudo_configuration.sh .

# Copy dependecies from previous step called builder, where intel-cmt-cat is installed.
COPY --from=builder /usr/local/lib/libpqos.* /usr/lib/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/share/snmp/mibs/ /usr/share/snmp/mibs/
COPY --from=builder /usr/bin/telegraf /usr/bin/telegraf
COPY --from=builder entrypoint.sh .

# Set sudo config for specific plugins, and just in case update alternatives, because sometimes docker can mess it up.
RUN ./sudo_configuration.sh

# Override entrypoint
ENTRYPOINT ["sh", "-c", "rasdaemon -r && sleep 10s && ./entrypoint.sh telegraf"]
