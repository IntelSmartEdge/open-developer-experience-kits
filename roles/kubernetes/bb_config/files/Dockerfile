# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2020 Intel Corporation

FROM centos:7.9.2009 AS builder

ENV http_proxy=$http_proxy
ENV https_proxy=$https_proxy
ENV INIH_PATH=/root/inih/extra

RUN yum install -y git-1.8.3.1 cmake-2.8.12.2 gcc-c++-4.8.5 make-3.82; yum clean all

WORKDIR /root

RUN git clone https://github.com/intel/pf-bb-config.git

RUN git clone -b r47 https://github.com/benhoyt/inih

WORKDIR /root/inih/extra
RUN make -f Makefile.static && cp ../ini.h /root/pf-bb-config

WORKDIR /root/pf-bb-config
RUN  make

FROM centos:7.9.2009

RUN yum install -y sudo-1.8.23; yum clean all

ARG username=bb_config
ARG user_dir=/home/$username

RUN useradd -d $user_dir -m -s /bin/bash $username
RUN groupadd sudo
RUN usermod -aG sudo $username
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER $username
WORKDIR $user_dir

COPY --from=builder /root/pf-bb-config/pf_bb_config .
