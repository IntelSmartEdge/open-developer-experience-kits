#!/bin/bash
#SPDX-License-Identifier: Apache-2.0
#Copyright (c) 2021 Intel Corporation

#This script installs all dependencies needed to run the Smart Edge deploy on dev machine.

SCRIPT_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" || exit ; pwd -P )
cd "$SCRIPT_PATH" || exit

if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_NAME=$ID
fi

if [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "centos" ] || [ "$OS_NAME" = "rhel" ]; then
    echo -e "\e[32m[Detected OS: $OS_NAME]\e[0m"

    if [ "$OS_NAME" = "ubuntu" ]; then
        echo -e "\e[32m[apt update]\e[0m"
        sudo apt update
        echo -e "\e[32m[apt install python3-pip]\e[0m"
        sudo apt install python3-pip
    fi
    
    if [ "$OS_NAME" = "centos" ] || [ "$OS_NAME" = "rhel" ]; then
        echo -e "\e[32m[yum install python3-pip]\e[0m"
        yum install -y python3-pip
    fi

    echo -e "\e[32m[pip3 install pipenv]\e[0m"
    pip3 install pipenv

    if [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "centos" ]; then
        if [ "$USER" = "root" ]; then
            export PATH=$PATH:/root/.local/bin
        else
            export PATH=$PATH:/home/$USER/.local/bin
        fi
    fi

    echo -e "\e[32m[pipenv install]\e[0m"
    pipenv install

    echo -e "\e[32m[pipenv run ./deploy.py]\e[0m"
    pipenv run ./deploy.py "$@"
else
    echo -e "\e[31m[Unrecognized OS: $OS_NAME]\e[0m"
    exit 1
fi
