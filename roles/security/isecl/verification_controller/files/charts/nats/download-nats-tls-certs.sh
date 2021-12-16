#!/bin/bash

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

while getopts :d:n::s:u:t:h opt; do
  case "$opt" in
  u) CMS_URL="${OPTARG}" ;;
  n) CERT_CN="${OPTARG}" ;;
  s) SAN_LIST="${OPTARG}" ;;
  d) CERTS_DIR="${OPTARG}" ;;
  t) BEARER_TOKEN="${OPTARG}" ;;
  h) echo "Usage: $0 [-d /working/directory] [-n CommonName] -s \"hostname1.mydomain.net,hostname2,hostname3.yourdomain.com\" -u \"CMS URL\" -t \"BEARER_TOKEN\"" ; exit ;;
  *) echo "Unknown option";;
  esac
done

if [ -z "$CERT_CN" ]; then
  echo "Error: missing cert common name. Aborting..."
  exit 1
fi

if [ -z "$SAN_LIST" ]; then
  echo "Error: Subject Alternative Names for the cert have not been provided. Aborting..."
  exit 1
fi

if [ -z "$CMS_URL" ]; then
  echo "Error: CMS_UR has not been provided. Aborting..."
  exit 1
fi

if [ -z "$BEARER_TOKEN" ]; then
  echo "Error: BEARER_TOKEN has not been provided. Aborting..."
  exit 1
fi

if [ ! -w "$CERTS_DIR" ]; then
  echo "Error: No write permissions for workdir. Aborting..."
  exit 1
fi

cd "$CERTS_DIR" || { echo "Failed to cd"; exit 1; }

echo "Creating certificate request..."

# create a csr conf for openssl to use
cat <<EOF >csr.conf
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no
[req_distinguished_name]
CN = $CERT_CN
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
EOF

# split up the CSV entries in SAN_LIST
IFS=','; san_list=("$SAN_LIST"); unset IFS

# openssl requires each SAN entry to be appended separately as either IP or DNS
export dnscounter=1
export ipcounter=1
for san in "${san_list[@]}";
do
# check if the san is an IP or an DNS
if [[ $san =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]];
then
echo "IP.${ipcounter} = $san" >> csr.conf
ipcounter=$((ipcounter+1))
else
echo "DNS.${dnscounter} = $san" >> csr.conf
dnscounter=$((dnscounter+1))
fi
done

CSR_FILE=sslcert

# generate CSR
if ! openssl req -new -newkey rsa:3072 -sha384 -nodes -keyout sslcert.key -out ${CSR_FILE}.csr -subj "/CN=$CERT_CN" -config csr.conf; then
  echo "Error generating CSR. Aborting..."
  exit 1
fi

echo "Downloading TLS Cert from CMS...."
curl --noproxy "*" -k -X POST "${CMS_URL}"/certificates?certType=TLS -H 'Accept: application/x-pem-file' -H "Authorization: Bearer $BEARER_TOKEN" -H 'Content-Type: application/x-pem-file' --data-binary "@$CSR_FILE.csr" > server.pem
