# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

'''Shell utilities'''

def create_variables_file(path, variables):
    ''' Serialize provided configuration variables to the shell script format '''
    content = ''

    for name, value in variables.items():

        if isinstance(value, bool): # profile needs 'true' not 'True', it does not check for anything else
            value = str(value).lower()

        content += f'export {name}={value}\n'

    with open(path, "w") as f:
        f.write(content)
