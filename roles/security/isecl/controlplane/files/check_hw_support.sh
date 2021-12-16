#!/bin/bash

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021 Intel Corporation

tpm=0
secure_boot=0
if dmesg | grep -i tpm | grep -i -q '2.0 TPM\|tpm2'
then
   tpm=1
   echo "TPM 2.0 available"
else
   tpm=0
   echo "TPM 2.0 missing"
fi;

if mokutil --sb-state | grep -q 'SecureBoot enabled'
then
   secure_boot=1
   echo "SecureBoot enabled"
else
   secure_boot=0
   echo "SecureBoot not enabled"
fi;

if [[ $tpm && $secure_boot == 1 ]]
then
   echo "SUCCESS"
else
   echo "FAILED"
fi;
