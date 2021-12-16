#!/bin/bash

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

# shellcheck disable=SC1091
if ! source isecl-k8s.env; then
  echo "failed to source isecl-k8s.env"
fi

K8S_DEPLOY_TOOL=helm

check_k8s_distribution() {
  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    KUBECTL=microk8s.kubectl
  elif [ "$K8S_DISTRIBUTION" == "kubeadm" ]; then
    KUBECTL=kubectl
  else
    echo "K8s Distribution $K8S_DISTRIBUTION not supported"
  fi
}

check_k8s_deploy_tool() {
  if [ "$K8S_DEPLOY_TOOL" == "kubectl" ]; then
    K8S_DEPLOY=kubectl
  elif [ "$K8S_DEPLOY_TOOL" == "helm" ]; then
    K8S_DEPLOY=helm
  else
    echo "K8s deployment tool" $K8S_DEPLOY_TOOL "not supported"
  fi
}
HOME_DIR=$(pwd)

K8S_DISTRIBUTION=${K8S_DISTRIBUTION:-"microk8s"}
# Setting default KUBECTl command as kubectl
KUBECTL=${KUBECTL:-"microk8s.kubectl"}

deploy_authservice_db() {

  echo "-----------------------------------------------------------------------"
  echo "|    DEPLOY: AUTHENTICATION-AUTHORIZATION-SERVICE DATABASE INSTANCE   |"
  echo "-----------------------------------------------------------------------"

  $KUBECTL create namespace isecl
  cd "$HOME_DIR/aas-db/" || { echo "Failed to cd"; exit 1; }
  mkdir -p secrets

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    # set user:group for pgdata directory
    mkdir -p /usr/local/kube/data/authservice/pgdata
    chmod 700 /usr/local/kube/data/authservice/pgdata
    chown -R 2000:2000 /usr/local/kube/data/authservice/pgdata
  fi

  # generate server.crt,server.key
  openssl req -new -x509 -days 365 -newkey rsa:4096 -addext "subjectAltName = DNS:$AAS_DB_HOSTNAME" -nodes -text -out secrets/server.crt -keyout secrets/server.key -sha384 -subj "/CN=ISecl Self Sign Cert"

  $KUBECTL create secret generic aas-db-certs -n isecl --from-file=server.crt=secrets/server.crt --from-file=server.key=secrets/server.key
  cd .. || { echo "Failed to cd"; exit 1; }
  # deploy
  $K8S_DEPLOY install aas-db-dep aas-db --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=aasdb -n isecl -o name)
  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "AUTHENTICATION-AUTHORIZATION-SERVICE DATABASE DEPLOYED SUCCESSFULLY"
  else
    echo "ERROR: Failed to deploy AAS Database Pod"
    echo "Exiting with error..."
    exit 1
  fi

  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

deploy_hvs_db() {

  echo "--------------------------------------------------------------------"
  echo "|            DEPLOY: HOST-VERIFICATION-SERVICE DATABASE            |"
  echo "--------------------------------------------------------------------"

  cd "$HOME_DIR/hvs-db/" || { echo "Failed to cd"; exit 1; }
  mkdir -p secrets

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    # set user:group for pgdata directory
    mkdir -p /usr/local/kube/data/host-verification-service/pgdata/
    chmod 700 /usr/local/kube/data/host-verification-service/pgdata
    chown -R 2000:2000 /usr/local/kube/data/host-verification-service/pgdata
  fi

  # generate server.crt,server.key
  openssl req -new -x509 -days 365 -newkey rsa:4096 -addext "subjectAltName = DNS:$HVS_DB_HOSTNAME" -nodes -text -out secrets/server.crt -keyout secrets/server.key -sha384 -subj "/CN=ISecl Self Sign Cert"
  $KUBECTL create secret generic hvs-db-certs -n isecl --from-file=server.crt=secrets/server.crt --from-file=server.key=secrets/server.key
  cd .. || { echo "Failed to cd"; exit 1; }
  # deploy
  $K8S_DEPLOY install hvs-db hvs-db --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=hvsdb -n isecl -o name)
  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "HOST-VERIFICATION-SERVICE DATABASE DEPLOYED SUCCESSFULLY"
  else
    echo "Error: Deploying HVS Database Pod"
    echo "Exiting with error..."
    exit 1
  fi
  cd ../ || { echo "Failed to cd"; exit 1; }
}

cleanup_hvs_db() {

  echo "Cleaning up HOST-VERIFICATION-SERVICE Database"

  cd "$HOME_DIR/hvs-db/" || { echo "Failed to cd"; exit 1; }

  $KUBECTL delete secret hvs-db-credentials hvs-db-certs --namespace isecl
  rm -rf secrets/server.crt
  rm -rf secrets/server.key

  cd .. || { echo "Failed to cd"; exit 1; }
  $K8S_DEPLOY uninstall hvs-db


  cd .. || { echo "Failed to cd"; exit 1; }

  pwd
}

cleanup_authservice_db() {

  echo "Cleaning up AUTHENTICATION-AUTHORIZATION-SERVICE Database"

  cd "$HOME_DIR/aas-db/" || { echo "Failed to cd"; exit 1; }

  $KUBECTL delete secret aas-db-credentials aas-db-certs --namespace isecl
  rm -rf secrets/server.crt
  rm -rf secrets/server.key
  cd .. || { echo "Failed to cd"; exit 1; }
  $K8S_DEPLOY uninstall aas-db-dep


  cd .. || { echo "Failed to cd"; exit 1; }

}

bootstrap() {

  echo "Kubenertes-> "

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    if ! $KUBECTL version --short; then
      echo "microk8s not installed. Cannot bootstrap ISecL Services"
      echo "Exiting with Error.."
      exit 1
    fi
  elif [ "$K8S_DISTRIBUTION" == "kubeadm" ]; then
    if ! kubeadm version; then
      echo "kubeadm not installed. Cannot bootstrap ISecL Services"
      echo "Exiting with Error.."
      exit 1
    fi
  else
    echo "K8s Distribution $K8S_DISTRIBUTION not supported"
  fi

  echo "OpenSSL->"
  if ! openssl version; then
    echo "OpenSSL is not installed. Cannot create certificates needed for SSL connection to DB"
    echo "Exiting with Error.."
    exit 1
  fi

  echo "-------------------------------------------------------------------------------------------------------------"
  echo "|     DEPLOY: Database SERVICES For Authservice, Workload Service and Host Verification Services     |"
  echo "-------------------------------------------------------------------------------------------------------------"
  echo ""

  deploy_authservice_db
  deploy_hvs_db

  cd ../ || { echo "Failed to cd"; exit 1; }

}

# #Function to cleanup Intel Micro SecL on Micro K8s
cleanup() {

  echo "----------------------------------------------------"
  echo "|                    CLEANUP                       |"
  echo "----------------------------------------------------"

  cleanup_hvs_db
  cleanup_authservice_db

  echo "Wait for pods to terminate..."
  sleep 30

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    purge
  fi

}

purge() {
  echo "Cleaning up data from /usr/local/kube/data/"
  rm -rf /usr/local/kube/data/authservice /usr/local/kube/data/host-verification-service /usr/local/kube/data/workload-service
}

#Help section
print_help() {
  echo "Usage: $0 [-help/up/purge]"
  echo "    -help          print help and exit"
  echo "    up       [all/foundational-security]     Bootstrap Database Services for specified use case"
  echo "    purge    [all/foundational-security]     Delete Database Services for specified use case"
  echo ""
  echo "    Available Options for up/purge command:"
  echo "    usecase    Can be one of foundational-security, all"

}

#Dispatch works based on args to script
dispatch_works() {

  case $1 in
  "up")
    check_k8s_distribution
    check_k8s_deploy_tool
    if [[ $2 == "foundational-security" ]]; then
      deploy_authservice_db
      deploy_hvs_db
    else
      bootstrap
    fi
    ;;
  "purge")
    check_k8s_distribution
    check_k8s_deploy_tool
    if [[ $2 == "foundational-security" ]]; then
      cleanup_authservice_db
      cleanup_hvs_db
    else
      cleanup
    fi
    ;;
  *)
    print_help
    exit 1
    ;;

  esac
}

if [ $# -eq 0 ]; then
  print_help
  exit 1
fi

work_list=""
while getopts h:u:d:p opt; do
  case ${opt} in
  h)
    print_help
    exit 0
    ;;
  u) work_list+="up" ;;
  d) work_list+="purge" ;;
  *)
    print_help
    exit 1
    ;;
  esac
done

# run commands
# shellcheck disable=SC2048,SC2086
dispatch_works $*
