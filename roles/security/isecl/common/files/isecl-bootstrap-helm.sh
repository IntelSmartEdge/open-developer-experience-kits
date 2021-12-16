#!/bin/bash

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

# shellcheck disable=SC1091
if ! source isecl-k8s.env; then
  echo "failed to source isecl-k8s.env"
fi

K8S_DEPLOY_TOOL=helm # Use kubectl or helm

CMS_TLS_CERT_SHA384=${CMS_TLS_CERT_SHA384:-}
AAS_BOOTSTRAP_TOKEN=""
BEARER_TOKEN=${BEARER_TOKEN:-}
ISECL_K8S_EXTENSIONS=${ISECL_K8S_EXTENSIONS:-}
CC_TA_TOKEN=${CC_TA_TOKEN:-}
HTTP_PROXY=${http_proxy:-}
HTTPS_PROXY=${https_proxy:-}
NO_PROXY=${no_proxy:-}
ALL_PROXY=${all_proxy:-}

HOME_DIR=$(pwd)

AAS="aas"
IHUB="ihub"
TAGENT="tagent"
ISECL_SCHEDULER="isecl-k8s-scheduler"

check_k8s_distribution() {
  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    KUBECTL=microk8s.kubectl
  elif [ "$K8S_DISTRIBUTION" == "kubeadm" ]; then
    KUBECTL=kubectl
  else
    echo "K8s Distribution \"$K8S_DISTRIBUTION\" not supported"
  fi
}

check_mandatory_variables() {
  IFS=',' read -ra ADDR <<<"$2"
  for env_var in "${ADDR[@]}"; do
    if [[ ! -v "${env_var}" ]]; then
      echo "$env_var is not set for service: $1"
      exit 1
    fi
  done
}

deploy_cms() {

  echo "----------------------------------------------------"
  echo "|      DEPLOY: CERTIFICATE-MANAGEMENT-SERVICE      |"
  echo "----------------------------------------------------"

  cd "$HOME_DIR/cms/templates/" || { echo "Failed to cd"; exit 1; }

  # update configMap
  sed -i "s/SAN_LIST:.*/SAN_LIST: $CMS_SAN_LIST/g" configMap.yml
  sed -i "s/AAS_TLS_SAN:.*/AAS_TLS_SAN: $AAS_SAN_LIST/g" configMap.yml

  cd ../.. || { echo "Failed to cd"; exit 1; }
  # deploy
  $K8S_DEPLOY_TOOL install cms-dep cms --timeout 30s --wait
  

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=cms -n isecl -o name)
  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "CERTIFICATE-MANAGEMENT-SERVICE DEPLOYED SUCCESSFULLY"
  else
    echo "ERROR: Failed to deploy CMS"
    echo "Exiting with error..."
    exit 1
  fi
  echo "Waiting for CMS to bootstrap itself..."
  sleep 20
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

get_cms_tls_cert_sha384() {
  cms_pod=$($KUBECTL get pod -n isecl -l app=cms -o jsonpath="{.items[0].metadata.name}")
  CMS_TLS_CERT_SHA384=$($KUBECTL exec -n isecl --stdin "$cms_pod" -- cms tlscertsha384)
}

get_aas_bootstrap_token() {
  cms_pod=$($KUBECTL get pod -n isecl -l app=cms -o jsonpath="{.items[0].metadata.name}")
  AAS_BOOTSTRAP_TOKEN=$($KUBECTL exec -n isecl --stdin "$cms_pod" -- cms setup cms-auth-token --force | grep "JWT Token:" | awk '{print $3}')
  $KUBECTL create secret generic aas-bootstrap-token -n isecl --from-literal=BEARER_TOKEN="$AAS_BOOTSTRAP_TOKEN" --save-config --dry-run=client -o yaml | $KUBECTL apply -f -
}

deploy_authservice() {

  get_cms_tls_cert_sha384
  get_aas_bootstrap_token
  echo "----------------------------------------------------"
  echo "|    DEPLOY: AUTHENTICATION-AUTHORIZATION-SERVICE  |"
  echo "----------------------------------------------------"

  required_variables="AAS_ADMIN_USERNAME,AAS_ADMIN_PASSWORD,AAS_DB_HOSTNAME,AAS_DB_NAME,AAS_DB_PORT,AAS_DB_SSLMODE,AAS_DB_SSLCERT,AAS_BOOTSTRAP_TOKEN,AAS_SAN_LIST"
  check_mandatory_variables $AAS $required_variables

  cd "$HOME_DIR/aas/templates/" || { echo "Failed to cd"; exit 1; }

  # update configMap and secrets
  sed -i "s/CMS_TLS_CERT_SHA384:.*/CMS_TLS_CERT_SHA384: $CMS_TLS_CERT_SHA384/g" configMap.yml
  sed -i "s#CMS_BASE_URL:.*#CMS_BASE_URL: $CMS_BASE_URL#g" configMap.yml
  sed -i "s/SAN_LIST:.*/SAN_LIST: $AAS_SAN_LIST/g" configMap.yml
  sed -i "s/AAS_DB_HOSTNAME:.*/AAS_DB_HOSTNAME: $AAS_DB_HOSTNAME/g" configMap.yml
  sed -i "s/AAS_DB_NAME:.*/AAS_DB_NAME: $AAS_DB_NAME/g" configMap.yml
  sed -i "s/AAS_DB_PORT:.*/AAS_DB_PORT: \"$AAS_DB_PORT\"/g" configMap.yml
  sed -i "s/AAS_DB_SSLMODE:.*/AAS_DB_SSLMODE: $AAS_DB_SSLMODE/g" configMap.yml
  sed -i "s#AAS_DB_SSLCERT:.*#AAS_DB_SSLCERT: $AAS_DB_SSLCERT#g" configMap.yml
  nats_account_name_exists=$(grep "NATS_ACCOUNT_NAME" configMap.yml)
  if [ -n "${NATS_ACCOUNT_NAME}" ] && [ -z "$nats_account_name_exists" ]; then
    echo "  NATS_ACCOUNT_NAME: $NATS_ACCOUNT_NAME" >>configMap.yml
    echo "hi"
  fi

  echo "$AAS_DB_USERNAME"
  sed -i "s/AAS_DB_USERNAME:.*/AAS_DB_USERNAME: $AAS_DB_USERNAME/g" secrets.yml
  sed -i "s/AAS_DB_PASSWORD:.*/AAS_DB_PASSWORD: $AAS_DB_PASSWORD/g" secrets.yml
  sed -i "s/AAS_ADMIN_USERNAME:.*/AAS_ADMIN_USERNAME: $AAS_ADMIN_USERNAME/g" secrets.yml
  sed -i "s/AAS_ADMIN_PASSWORD:.*/AAS_ADMIN_PASSWORD: $AAS_ADMIN_PASSWORD/g" secrets.yml

  # deploy
  cd ../.. || { echo "Failed to cd"; exit 1; }
  $K8S_DEPLOY_TOOL install aas-dep aas --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=aas -n isecl -o name)

  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "AUTHENTICATION-AUTHORIZATION-SERVICE DEPLOYED SUCCESSFULLY"
  else
    echo "ERROR: Failed to deploy AAS"
    echo "Exiting with error..."
    exit 1
  fi

  echo "Waiting for AAS to bootstrap itself..."
  sleep 60
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

get_bearer_token() {

  aas_scripts_dir=$HOME_DIR/scripts
  echo "Running populate-users script"
  sed -i "s/ISECL_INSTALL_COMPONENTS=.*/ISECL_INSTALL_COMPONENTS=$ISECL_INSTALL_COMPONENTS/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s#CMS_BASE_URL=.*#CMS_BASE_URL=$CMS_BASE_URL#g" "$aas_scripts_dir/populate-users.env"
  sed -i "s#AAS_API_URL=.*#AAS_API_URL=$AAS_API_CLUSTER_ENDPOINT_URL#g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/HVS_CERT_SAN_LIST=.*/HVS_CERT_SAN_LIST=$HVS_CERT_SAN_LIST/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/IH_CERT_SAN_LIST=.*/IH_CERT_SAN_LIST=$IH_CERT_SAN_LIST/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/KBS_CERT_SAN_LIST=.*/KBS_CERT_SAN_LIST=$KBS_CERT_SAN_LIST/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/WLS_CERT_SAN_LIST=.*/WLS_CERT_SAN_LIST=$WLS_CERT_SAN_LIST/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s#TA_CERT_SAN_LIST=.*#TA_CERT_SAN_LIST=$TA_CERT_SAN_LIST#g" "$aas_scripts_dir/populate-users.env"
  sed -i "s#NATS_CERT_SAN_LIST=.*#NATS_CERT_SAN_LIST=$NATS_CERT_SAN_LIST#g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/AAS_ADMIN_USERNAME=.*/AAS_ADMIN_USERNAME=$AAS_ADMIN_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/AAS_ADMIN_PASSWORD=.*/AAS_ADMIN_PASSWORD=$AAS_ADMIN_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/IHUB_SERVICE_USERNAME=.*/IHUB_SERVICE_USERNAME=$IHUB_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/IHUB_SERVICE_PASSWORD=.*/IHUB_SERVICE_PASSWORD=$IHUB_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/WLS_SERVICE_USERNAME=.*/WLS_SERVICE_USERNAME=$WLS_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/WLS_SERVICE_PASSWORD=.*/WLS_SERVICE_PASSWORD=$WLS_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/WLA_SERVICE_USERNAME=.*/WLA_SERVICE_USERNAME=$WLA_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/WLA_SERVICE_PASSWORD=.*/WLA_SERVICE_PASSWORD=$WLA_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/WPM_SERVICE_USERNAME=.*/WPM_SERVICE_USERNAME=$WPM_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/WPM_SERVICE_PASSWORD=.*/WPM_SERVICE_PASSWORD=$WPM_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/HVS_SERVICE_USERNAME=.*/HVS_SERVICE_USERNAME=$HVS_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/HVS_SERVICE_PASSWORD=.*/HVS_SERVICE_PASSWORD=$HVS_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/KBS_SERVICE_USERNAME=.*/KBS_SERVICE_USERNAME=$KBS_SERVICE_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/KBS_SERVICE_PASSWORD=.*/KBS_SERVICE_PASSWORD=$KBS_SERVICE_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/INSTALL_ADMIN_USERNAME=.*/INSTALL_ADMIN_USERNAME=$INSTALL_ADMIN_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/INSTALL_ADMIN_PASSWORD=.*/INSTALL_ADMIN_PASSWORD=$INSTALL_ADMIN_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/GLOBAL_ADMIN_USERNAME=.*/GLOBAL_ADMIN_USERNAME=$GLOBAL_ADMIN_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/GLOBAL_ADMIN_PASSWORD=.*/GLOBAL_ADMIN_PASSWORD=$GLOBAL_ADMIN_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/CCC_ADMIN_USERNAME=.*/CCC_ADMIN_USERNAME=$CCC_ADMIN_USERNAME/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/CCC_ADMIN_PASSWORD=.*/CCC_ADMIN_PASSWORD=$CCC_ADMIN_PASSWORD/g" "$aas_scripts_dir/populate-users.env"

  sed -i "s/CUSTOM_CLAIMS_COMPONENTS=.*/CUSTOM_CLAIMS_COMPONENTS=$CUSTOM_CLAIMS_COMPONENTS/g" "$aas_scripts_dir/populate-users.env"
  sed -i "s/CUSTOM_CLAIMS_TOKEN_VALIDITY_SECS=.*/CUSTOM_CLAIMS_TOKEN_VALIDITY_SECS=$CUSTOM_CLAIMS_TOKEN_VALIDITY_SECS/g" "$aas_scripts_dir/populate-users.env"

  # TODO: need to check if this can be fetched from builds instead of bundling the script here
  chmod +x "$aas_scripts_dir/populate-users"
  "$aas_scripts_dir/populate-users" --answerfile "$aas_scripts_dir/populate-users.env" > "$aas_scripts_dir/populate-users.log"

  BEARER_TOKEN=$(grep "Token for User: $INSTALL_ADMIN_USERNAME" "$aas_scripts_dir/populate-users.log" -A 2 | grep BEARER_TOKEN | cut -d '=' -f2)
  echo "Install token: $BEARER_TOKEN"
  $KUBECTL create secret generic bearer-token -n isecl --from-literal=BEARER_TOKEN="$BEARER_TOKEN" --save-config --dry-run=client -o yaml | $KUBECTL apply -f -

  if [ -n "$NATS_SERVERS" ]; then
    CC_TA_TOKEN=$(grep "Custom Claims Token For TA" "$aas_scripts_dir/populate-users.log" -A 2 | grep BEARER_TOKEN | cut -d '=' -f2)
  fi
}

deploy_hvs() {

  cd "$HOME_DIR/hvs/" || { echo "Failed to cd"; exit 1; }

  echo "-------------------------------------------------------------"
  echo "|            DEPLOY: HOST-VERIFICATION-SERVICE              |"
  echo "-------------------------------------------------------------"

  # The variables BEARER_TOKEN and CMS_TLS_CERT_SHA384 get loaded with below functions, this required if we want to deploy individual hvs service
  get_bearer_token
  get_cms_tls_cert_sha384

  required_variables="BEARER_TOKEN,CMS_TLS_CERT_SHA384,HVS_SERVICE_USERNAME,HVS_SERVICE_PASSWORD,HVS_CERT_SAN_LIST,AAS_API_URL,CMS_BASE_URL,HVS_DB_HOSTNAME,HVS_DB_SSLCERTSRC,HVS_DB_PORT,HVS_DB_NAME"
  check_mandatory_variables "$SHVS" "$required_variables"

  # update hvs configMap & secrets
  if [[ -z "${NATS_SERVERS}" ]]; then
    sed -i "s/NATS_SERVERS:.*//g" values.yaml
  else
    sed -i "s#NATS_SERVERS:.*#NATS_SERVERS: ${NATS_SERVERS}#g" values.yaml
  fi

  sed -i "s/HVS_SERVICE_USERNAME:.*/HVS_SERVICE_USERNAME: ${HVS_SERVICE_USERNAME}/g" templates/secrets.yml
  sed -i "s/HVS_SERVICE_PASSWORD:.*/HVS_SERVICE_PASSWORD: ${HVS_SERVICE_PASSWORD}/g" templates/secrets.yml
  sed -i "s/HVS_DB_USERNAME:.*/HVS_DB_USERNAME: ${HVS_DB_USERNAME}/g" templates/secrets.yml
  sed -i "s/HVS_DB_PASSWORD:.*/HVS_DB_PASSWORD: ${HVS_DB_PASSWORD}/g" templates/secrets.yml

  sed -i "s/SAN_LIST:.*/SAN_LIST: ${HVS_CERT_SAN_LIST}/g" values.yaml
  sed -i "s/HVS_DB_HOSTNAME:.*/HVS_DB_HOSTNAME: ${HVS_DB_HOSTNAME}/g" values.yaml
  sed -i "s/HVS_DB_NAME:.*/HVS_DB_NAME: ${HVS_DB_NAME}/g" values.yaml
  sed -i "s/HVS_DB_PORT:.*/HVS_DB_PORT: \"$HVS_DB_PORT\"/g" values.yaml

  sed -i "s/CMS_TLS_CERT_SHA384:.*/CMS_TLS_CERT_SHA384: ${CMS_TLS_CERT_SHA384}/g" values.yaml
  sed -i "s#AAS_API_URL:.*#AAS_API_URL: ${AAS_API_URL}#g" values.yaml
  sed -i "s#CMS_BASE_URL:.*#CMS_BASE_URL: ${CMS_BASE_URL}#g" values.yaml
  sed -i "s/HVS_DB_HOSTNAME:.*/HVS_DB_HOSTNAME: ${HVS_DB_HOSTNAME}/g" values.yaml
  sed -i "s#HVS_DB_SSLCERTSRC:.*#HVS_DB_SSLCERTSRC: ${HVS_DB_SSLCERTSRC}#g" values.yaml

  cd ../ || { echo "Failed to cd"; exit 1; }
  # deploy
  $K8S_DEPLOY_TOOL install hvs-dep hvs --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=hvs -n isecl -o name)

  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "HOST-VERIFICATION-SERVICE DEPLOYED SUCCESSFULLY"
  else
    echo "Error: Deploying HVS"
    echo "Exiting with error..."
    exit 1
  fi
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

deploy_custom_controller() {

  echo "----------------------------------------------------"
  echo "|            DEPLOY: ISECL-K8S-CONTROLLER          |"
  echo "----------------------------------------------------"

  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
  $KUBECTL create clusterrolebinding isecl-clusterrole --clusterrole=system:node --user=system:serviceaccount:isecl:isecl

  # deploy
  $K8S_DEPLOY_TOOL install isecl-controller-dep k8s-extensions-controller --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=isecl-controller -n isecl -o name)

  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "K8S-CONTROLLER DEPLOYED SUCCESSFULLY"
  else
    echo "Error: Deploying K8S-CONTROLLER"
    echo "Exiting with error..."
    exit 1
  fi

  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

deploy_ihub() {

  echo "----------------------------------------------------"
  echo "|             DEPLOY: INTEGRATION-HUB              |"
  echo "----------------------------------------------------"

  required_variables="IHUB_SERVICE_USERNAME,IHUB_SERVICE_PASSWORD,K8S_API_SERVER_CERT,HVS_BASE_URL,BEARER_TOKEN,CMS_TLS_CERT_SHA384"
  check_mandatory_variables $IHUB $required_variables

  cd "$HOME_DIR/ihub" || { echo "Failed to cd"; exit 1; }

  kubernetes_token=$($KUBECTL get secrets -o jsonpath="{.items[?(@.metadata.annotations['kubernetes\.io/service-account\.name']=='default')].data.token}" -n isecl | base64 --decode)

  mkdir -p secrets
  mkdir -p /etc/ihub/

  if [ "$K8S_DISTRIBUTION" == "kubeadm" ]; then
    API_SERVER_PORT=6443
  elif [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    API_SERVER_PORT=16443
  else
    echo "K8s Distribution $K8S_DISTRIBUTION not supported"
    exit 1
  fi

  cp "$K8S_API_SERVER_CERT" secrets/apiserver.crt

  #update configMap & secrets
  sed -i "s/CMS_TLS_CERT_SHA384:.*/CMS_TLS_CERT_SHA384: $CMS_TLS_CERT_SHA384/g" values.yaml
  sed -i "s/TLS_SAN_LIST:.*/TLS_SAN_LIST: $IH_CERT_SAN_LIST/g" values.yaml
  sed -i "s/KUBERNETES_TOKEN:.*/KUBERNETES_TOKEN: $kubernetes_token/g" values.yaml
  sed -i "s/KUBERNETES_URL:.*/KUBERNETES_URL: https:\/\/$K8S_CONTROL_PLANE_IP:$API_SERVER_PORT\//g" values.yaml
  sed -i "s/IHUB_SERVICE_USERNAME:.*/IHUB_SERVICE_USERNAME: $IHUB_SERVICE_USERNAME/g" templates/secrets.yml
  sed -i "s/IHUB_SERVICE_PASSWORD:.*/IHUB_SERVICE_PASSWORD: $IHUB_SERVICE_PASSWORD/g" templates/secrets.yml
  sed -i "s#CMS_BASE_URL:.*#CMS_BASE_URL: ${CMS_BASE_URL}#g" values.yaml
  sed -i "s#AAS_API_URL:.*#AAS_API_URL: ${AAS_API_URL}#g" values.yaml
  sed -i "s#HVS_BASE_URL:.*#HVS_BASE_URL: ${HVS_BASE_URL}#g" values.yaml
  sed -i "s/SHVS_BASE_URL:.*//g" values.yaml

  #Add proxy settings
  sed -i "s#<http_proxy>.*#$HTTP_PROXY#g" values.yaml
  sed -i "s#<https_proxy>.*#$HTTPS_PROXY#g" values.yaml
  sed -i "s#<all_proxy>.*#$ALL_PROXY#g" values.yaml
  sed -i "s#<no_proxy>.*#$NO_PROXY#g" values.yaml

  $KUBECTL create secret generic bearer-token -n isecl --from-literal=BEARER_TOKEN="$BEARER_TOKEN" --save-config --dry-run=client -o yaml | $KUBECTL apply -f -

  $KUBECTL create secret generic ihub-k8s-certs --from-file=secrets/apiserver.crt --namespace=isecl
  cd ../ || { echo "Failed to cd"; exit 1; }

  # deploy
  $K8S_DEPLOY_TOOL install ihub-dep ihub --timeout 30s --wait

  # wait to get ready
  echo "Wait for pods to initialize..."
  POD_NAME=$($KUBECTL get pod -l app=ihub -n isecl -o name)

  if $KUBECTL wait --for=condition=Ready "$POD_NAME" -n isecl --timeout=300s; then
    echo "INTEGRATION-HUB DEPLOYED SUCCESSFULLY"
  else
    echo "Error: Deploying HUB"
    echo "Exiting with error..."
    exit 1
  fi

  echo "Waiting for IHub to bootstrap itself..."
  sleep 20
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }

}

deploy_extended_scheduler() {

  #K8s SCHEDULER
  echo "----------------------------------------------------"
  echo "|            DEPLOY: ISECL-K8S-SCHEDULER            |"
  echo "----------------------------------------------------"

  required_variables="K8S_CA_CERT,K8S_CA_KEY"
  check_mandatory_variables "$ISECL_SCHEDULER" $required_variables

  cd "$HOME_DIR/k8s-extensions-scheduler/" || { echo "Failed to cd"; exit 1; }

  echo "Installing Pre-requisites"

  sed -i "s#{HVS_IHUB_PUBLIC_KEY_PATH_VALUE}#\"/opt/isecl-k8s-extensions/hvs_ihub_public_key.pem\"#g" templates/isecl-scheduler.yml
  sed -i "s#{SGX_IHUB_PUBLIC_KEY_PATH_VALUE}#\"\"#g" values.yaml

  # create certs
  chmod +x scripts/create_k8s_extsched_certs.sh
  cd scripts && echo ./create_k8s_extsched_certs.sh -n "K8S Extended Scheduler" -s "$K8S_CONTROL_PLANE_IP","$K8S_CONTROL_PLANE_HOSTNAME" -c "$K8S_CA_CERT" -k "$K8S_CA_KEY"
  if ! ./create_k8s_extsched_certs.sh -n "K8S Extended Scheduler" -s "$K8S_CONTROL_PLANE_IP","$K8S_CONTROL_PLANE_HOSTNAME" -c "$K8S_CA_CERT" -k "$K8S_CA_KEY"; then
    echo "Error while creating certificates for extended scheduler"
    exit 1
  fi

  cd .. || { echo "Failed to cd"; exit 1; }
  mkdir -p secrets
  cp scripts/server.key secrets/
  cp scripts/server.crt secrets/

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    cp /etc/ihub/ihub_public_key.pem secrets/hvs_ihub_public_key.pem
  elif [ "$K8S_DISTRIBUTION" == "kubeadm" ]; then
    cp "$IHUB_PUB_KEY_PATH" secrets/hvs_ihub_public_key.pem
  else
    echo "K8s Distribution $K8S_DISTRIBUTION not supported"
    exit 1
  fi

  # Create kubernetes secrets scheduler-secret for isecl-scheduler.
  $KUBECTL create secret generic scheduler-certs --namespace isecl --from-file=secrets

  # deploy
  cd .. || { echo "Failed to cd"; exit 1; }
  $K8S_DEPLOY_TOOL install isecl-scheduler-dep k8s-extensions-scheduler --timeout 30s --wait

  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

deploy_tagent() {

  echo "----------------------------------------------"
  echo "|            DEPLOY: TRUST-AGENT             |"
  echo "----------------------------------------------"

  # Create bearer_token secret
  $KUBECTL create secret generic bearer-token -n isecl --from-literal=BEARER_TOKEN="$BEARER_TOKEN" --save-config --dry-run=client -o yaml | $KUBECTL apply -f -

  required_variables="TA_CERT_SAN_LIST,AAS_API_URL,HVS_URL,CMS_BASE_URL,BEARER_TOKEN,CMS_TLS_CERT_SHA384"
  check_mandatory_variables $TAGENT $required_variables

  cd "$HOME_DIR/trust-agent/" || { echo "Failed to cd"; exit 1; }
  # update trustagent configMap.yml
  sed -i "s#AAS_API_URL:.*#AAS_API_URL: $AAS_API_URL#g" values.yaml
  sed -i "s#HVS_URL:.*#HVS_URL: $HVS_URL#g" values.yaml
  sed -i "s#CMS_BASE_URL:.*#CMS_BASE_URL: $CMS_BASE_URL#g" values.yaml
  sed -i "s#CMS_TLS_CERT_SHA384:.*#CMS_TLS_CERT_SHA384: $CMS_TLS_CERT_SHA384#g" values.yaml
  #Add proxy settings
  sed -i "s#<http_proxy>.*#$HTTP_PROXY#g" values.yaml
  sed -i "s#<https_proxy>.*#$HTTPS_PROXY#g" values.yaml
  sed -i "s#<all_proxy>.*#$ALL_PROXY#g" values.yaml
  sed -i "s#<no_proxy>.*#$NO_PROXY#g" values.yaml
  if [ -n "$TPM_OWNER_SECRET" ]; then
    sed -i "s/TPM_OWNER_SECRET:.*/TPM_OWNER_SECRET: $TPM_OWNER_SECRET/g" templates/secrets.yml
  else
    sed -i "s/TPM_OWNER_SECRET=.*//g" templates/secrets.yml
  fi
  if [ "$TA_SERVICE_MODE" == "outbound" ]; then
    echo "TA_SERVICE_MODE: Outbound"
    sed -i "s/TA_SERVICE_MODE:.*/TA_SERVICE_MODE: $TA_SERVICE_MODE/g" values.yaml
    sed -i "s#NATS_SERVERS:.*#NATS_SERVERS: $NATS_SERVERS#g" values.yaml
  else
    echo "TA_SERVICE_MODE: Standard"
    sed -i "s/TA_SERVICE_MODE:.*//g" values.yaml
    sed -i "s/NATS_SERVERS:.*//g" values.yaml
  fi

  cd ../ || { echo "Failed to cd"; exit 1; }
  $K8S_DEPLOY_TOOL install ta-dep trust-agent --timeout 30s --wait
  # wait to get ready
  echo "Wait for ta daemonsets to initialize..."
  sleep 20
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }

}

deploy_nats() {

  echo "-------------------------------------------------"
  echo "|            DEPLOY: NATS-SERVICE               |"
  echo "-------------------------------------------------"

  cd "$HOME_DIR/nats/" || { echo "Failed to cd"; exit 1; }
  get_bearer_token

  mkdir -p secrets

  if ! ./download-nats-tls-certs.sh -d secrets -n "$NATS_CERT_COMMON_NAME" -u "$CMS_K8S_ENDPOINT_URL" -s "$NATS_CERT_SAN_LIST" -t "$BEARER_TOKEN"; then
    echo "Error while downloading tls certs for nats server"
    exit 1
  fi

  # get operator and resolver preload from aas logs
  aas_pod=$($KUBECTL get pod -n isecl -l app=aas -o jsonpath="{.items[0].metadata.name}")
  credentials=$($KUBECTL exec -n isecl --stdin "$aas_pod" -- authservice setup create-credentials --force)
  nats_operator=$(echo "$credentials" | grep operator: | awk '{print $2}')
  resolver_preload=$(echo "$credentials" | grep "Account $NATS_ACCOUNT_NAME" -A 1)
  resolver_jwt=$(echo "$resolver_preload" | cut -d$'\n' -f2)

  sed -i "s#operator:.*#operator: $nats_operator#g" values.yaml
  sed -i "s#resolver_preload:.*#resolver_preload: { $resolver_jwt }#g" values.yaml

  $KUBECTL create secret generic nats-certs --from-file=secrets --namespace=isecl

  cd .. || { echo "Failed to cd"; exit 1; }

  $K8S_DEPLOY_TOOL install nats-dep nats --timeout 30s --wait
  # wait to get ready
  echo "Wait for nats to initialize..."
  sleep 20

  if $KUBECTL get pod -n isecl -l app=nats | grep Running; then
    echo "NATS STATEFULSET DEPLOYED SUCCESSFULLY"
  else
    echo "Error: Deploying NATS"
    echo "Exiting with error..."
    exit 1
  fi
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }

}

cleanup_tagent() {
  echo "Cleaning up TRUST-AGENT..."

  cleanup_bearer_token
  $K8S_DEPLOY_TOOL uninstall ta-dep
  
  echo "Wait for ta daemonsets to be cleaned up..."
  sleep 10
}

cleanup_nats() {
  echo "Cleaning up NATS-SERVICE"
  $KUBECTL delete secret nats-certs -n isecl
  cleanup_bearer_token
  $K8S_DEPLOY_TOOL uninstall nats-dep

  echo "Wait for nats components to be cleaned up..."
  sleep 10
}

cleanup_ihub() {
  echo "Cleaning up INTEGRATION-HUB..."

  $KUBECTL delete secret ihub-credentials --namespace isecl
  $KUBECTL delete secret ihub-k8s-certs --namespace isecl
  cleanup_bearer_token

  $K8S_DEPLOY_TOOL uninstall ihub-dep
  rm -rf "$HOME_DIR"/ihub/secrets
}

cleanup_isecl_controller() {

  echo "Cleaning up ISECL-K8S-CONTROLLER..."
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }

  $K8S_DEPLOY_TOOL uninstall isecl-controller-dep
}

cleanup_isecl_scheduler() {

  echo "Cleaning up ISECL-K8S-SCHEDULER..."
  cd "$HOME_DIR/k8s-extensions-scheduler/" || { echo "Failed to cd"; exit 1; }

  $KUBECTL delete secret scheduler-certs --namespace isecl
  rm -rf secrets
  $K8S_DEPLOY_TOOL uninstall isecl-scheduler-dep
  cd "$HOME_DIR" || { echo "Failed to cd"; exit 1; }
}

cleanup_hvs() {

  echo "Cleaning up HOST-VERIFICATION-SERVICE..."

  $KUBECTL delete secret hvs-credentials --namespace isecl
  cleanup_bearer_token

  $K8S_DEPLOY_TOOL uninstall hvs-dep
  
  echo "Wait for hvs to be cleaned up..."
  sleep 10 

  pwd
}

cleanup_authservice() {

  echo "Cleaning up AUTHENTICATION-AUTHORIZATION-SERVICE..."

  $KUBECTL delete secret aas-credentials --namespace isecl
  $K8S_DEPLOY_TOOL uninstall aas-dep
  
  echo "Wait for aas to be cleaned up..."
  sleep 10
  pwd
}

cleanup_cms() {

  echo "Cleaning up CERTIFICATE-MANAGEMENT-SERVICE..."

  $K8S_DEPLOY_TOOL uninstall cms-dep
  echo "Wait for cms to be cleaned up..."
  sleep 10
  pwd
}

bootstrap() {

  echo "----------------------------------------------------"
  echo "|        BOOTSTRAPPING ISECL SERVICES               |"
  echo "----------------------------------------------------"

  echo "----------------------------------------------------"
  echo "|                    PRECHECKS                     |"
  echo "----------------------------------------------------"
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

  echo "ipAddress: $K8S_CONTROL_PLANE_IP"
  echo "hostName: $K8S_CONTROL_PLANE_HOSTNAME"

  echo "----------------------------------------------------"
  echo "|     DEPLOY: ISECL SERVICES                        |"
  echo "----------------------------------------------------"
  echo ""

  deploy_common_components
  deploy_custom_controller
  deploy_ihub

  if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
    deploy_extended_scheduler
  fi

  cd ../ || { echo "Failed to cd"; exit 1; }

}

cleanup_bearer_token() {
  $KUBECTL delete secret bearer-token -n isecl
}

# #Function to cleanup Intel Micro SecL on Micro K8s
cleanup() {

  echo "----------------------------------------------------"
  echo "|                    CLEANUP                       |"
  echo "----------------------------------------------------"

  cleanup_ihub
  cleanup_isecl_scheduler
  cleanup_isecl_controller
  cleanup_common_components
  cleanup_bearer_token
  if cleanup_bearer_token; then
    echo "Wait for pods to terminate..."
    sleep 30
  fi

}

purge() {
  echo "Cleaning up logs from /var/log/"
  rm -rf /var/log/cms/ /var/log/authservice /var/log/workload-service /var/log/hvs /var/log/ihub /var/log/trustagent /var/log/workload-agent /var/log/kbs
  echo "Cleaning up config from /etc/"
  rm -rf /etc/cms /etc/authservice /etc/workload-service /etc/hvs /etc/ihub /opt/trustagent /etc/workload-agent /etc/kbs
}

#Help section
print_help() {
  echo "Usage: $0 [-help/up/down/purge]"
  echo "    -help                                     Print help and exit"
  echo "    up   [all/<agent>/<service>/<usecase>]    Bootstrap ISecL K8s environment for specified agent/service/usecase"
  echo "    down [all/<agent>/<service>/<usecase>]    Delete ISecL K8s environment for specified agent/service/usecase [will not delete data, config, logs]"
  echo "    purge                                     Delete ISecL K8s environment with data, config, logs [only supported for single node deployments]"
  echo ""
  echo "    Available Options for up/down command:"
  echo "        agent      Can be one of tagent, wlagent"
  echo "        service    Can be one of cms, authservice, hvs, ihub, wls, kbs, isecl-controller, isecl-scheduler"
  echo "        usecase    Can be one of foundational-security, workload-security, isecl-orchestration-k8s, csp, enterprise, foundational-security-control-plane"
}

deploy_common_components() {
  deploy_cms
  deploy_authservice
  if [[ -n "${NATS_SERVERS}" ]]; then
    deploy_nats
  fi
  deploy_hvs
  deploy_tagent
  cleanup_bearer_token
}

cleanup_common_components() {
  cleanup_cms
  cleanup_authservice
  cleanup_hvs
  if [[ -n "${NATS_SERVERS}" ]]; then
    cleanup_nats
  fi
  cleanup_tagent
  cleanup_bearer_token
}

#Dispatch works based on args to script
dispatch_works() {

  case $1 in
  "up")
    check_k8s_distribution
    case $2 in
    "cms")
      deploy_cms
      ;;
    "authservice")
      deploy_authservice
      ;;
    "hvs")
      deploy_hvs
      ;;
    "ihub")
      deploy_ihub
      ;;
    "tagent")
      deploy_tagent
      ;;
    "nats")
      deploy_nats
      ;;
    "isecl-controller")
      deploy_custom_controller
      ;;
    "isecl-scheduler")
      deploy_extended_scheduler
      ;;
    "foundational-security-control-plane")
      deploy_cms
      deploy_authservice
      if [[ -n "${NATS_SERVERS}" ]]; then
        deploy_nats
      fi
      deploy_hvs
      ;;
    "foundational-security")
      deploy_common_components
      ;;
    "isecl-orchestration-k8s")
      deploy_common_components
      deploy_custom_controller
      deploy_ihub
      if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
        deploy_extended_scheduler
      fi
      ;;
    "csp")
      deploy_common_components
      deploy_custom_controller
      deploy_ihub
      if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
        deploy_extended_scheduler
      fi
      deploy_wls
      deploy_wlagent
      ;;
    "enterprise")
      deploy_cms
      deploy_authservice
      deploy_kbs
      ;;
    "all")
      bootstrap
      ;;
    *)
      print_help
      exit 1
      ;;
    esac
    ;;

  "down")
    check_k8s_distribution
    case $2 in
    "cms")
      cleanup_cms
      ;;
    "authservice")
      cleanup_authservice
      ;;
    "hvs")
      cleanup_hvs
      ;;
    "ihub")
      cleanup_ihub
      ;;
    "isecl-controller")
      cleanup_isecl_controller
      ;;
    "isecl-scheduler")
      cleanup_isecl_scheduler
      ;;
    "tagent")
      cleanup_tagent
      ;;
    "nats")
      cleanup_nats
      ;;
    "foundational-security")
      cleanup_common_components
      ;;
    "foundational-security-control-plane")
      cleanup_cms
      cleanup_authservice
      cleanup_hvs
      if [[ -n "${NATS_SERVERS}" ]]; then
        cleanup_nats
      fi
      ;;
    "isecl-orchestration-k8s")
      cleanup_common_components
      cleanup_ihub
      cleanup_isecl_controller
      cleanup_isecl_scheduler
      ;;
    "csp")
      cleanup_common_components
      cleanup_isecl_controller
      cleanup_ihub
      if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
        cleanup_isecl_scheduler
      fi
      ;;
    "enterprise")
      cleanup_cms
      ;;
    "all")
      cleanup
      ;;

    *)
      print_help
      exit 1
      ;;
    esac
    ;;
  "purge")
    if [ "$K8S_DISTRIBUTION" == "microk8s" ]; then
      KUBECTL=microk8s.kubectl
      cleanup
      if  ! purge; then exit 1; fi
    else
      echo "purge command not supported for this K8s distribution"
      exit 1
    fi
    ;;
  "-help")
    print_help
    ;;
  *)
    echo "Invalid Command"
    print_help
    exit 1
    ;;
  esac
}

if [ $# -eq 0 ]; then
  print_help
  exit 1
fi

# run commands
# shellcheck disable=SC2048,SC2086
dispatch_works $*
