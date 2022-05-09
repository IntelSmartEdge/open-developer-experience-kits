```text
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2021 Intel Corporation
```

<!-- omit in toc -->
# Guidelines

- [General guidelines](#general-guidelines)
  - [Keep output files in one place](#keep-output-files-in-one-place)
  - [“block” usage](#block-usage)
  - [Use command's 'creates' param when possible](#use-commands-creates-param-when-possible)
  - [Ansible module instead of command](#ansible-module-instead-of-command)
  - [Look for role in baseline-ansible](#look-for-role-in-baseline-ansible)
  - ["become: yes" usage](#become-yes-usage)
  - [Check error (failed_when) instead of using ignore_error](#check-error-failed_when-instead-of-using-ignore_error)
  - [Helm values](#helm-values)
  - [External sources](#external-sources)
  - [File/dir permissions](#filedir-permissions)
  - [Don't remove temporary files if possible](#dont-remove-temporary-files-if-possible)
  - [Data manipulation](#data-manipulation)
  - [/tmp/ directory usage](#tmp-directory-usage)
  - [Set defaults for variables](#set-defaults-for-variables)
  - [Handle network reliability](#handle-network-reliability)
  - [Block/rescue for better debugging](#blockrescue-for-better-debugging)
  - [Task names](#task-names)
- [Role guidelines](#role-guidelines)
  - [Role should be independent from target host](#role-should-be-independent-from-target-host)
  - [Role configurability](#role-configurability)
  - [Splitting files](#splitting-files)
    - [Tasks file should have single responsibility](#tasks-file-should-have-single-responsibility)
    - [Role files size](#role-files-size)
    - [Check host state before execution](#check-host-state-before-execution)
    - [Advised structure](#advised-structure)
  - [Multinode support](#multinode-support)
  - [Variable definition](#variable-definition)
  - [Declare all variables as public](#declare-all-variables-as-public)
- [Multi OS guidelines](#multi-os-guidelines)
  - [Main task should be OS agnostic](#main-task-should-be-os-agnostic)
  - [OS abstraction](#os-abstraction)
  - [Preferrer usage of ansible_os_family](#preferrer-usage-of-ansible_os_family)
  - [Package management](#package-management)
- [Playbook organization](#playbook-organization)
- [Redeployment](#redeployment)
  - [Reduced development time](#reduced-development-time)
  - [Forces good structure](#forces-good-structure)
  - [Future use](#future-use)

# General guidelines

## Keep output files in one place

Tasks should keep its files in a well-known directory tree.
It is recommended to use:
1. *project_dir* - General location in which role/component should create directory and use that directory to store files
    ```yaml
    _git_repo_dest_harbor: "{{ project_dir }}/harbor"
    ```
2. *ne_helm_charts_default_dir* - For all Helm charts
    ```yaml
    _pcss_chart_dir: "{{ ne_helm_charts_default_dir }}/pccs"
    ```

    ```yaml
    - name: copy helm chart files
      copy:
        src: "{{ item }}"
        dest: "{{ _pcss_chart_dir }}"
        directory_mode: u+rwx
        mode: u+rw
      loop:
        - Chart.yaml
        - templates
    ```

Thanks to that it is easier to control what was changed in the system.

## “block” usage

"block" should be used if it improves readability and removes code duplication.
Blocks can help to group tasks that are executed under a single condition.
When there is too many blocks in single file, consider splitting the blocks into separate files.

```yaml
- name: update if rule changed
  block:
  - name: Reload udev rules
    command: udevadm control --reload-rules
    changed_when: true

  - name: Retrigger udev
    command: udevadm trigger
    changed_when: true

  become: yes
  when:
    - add_kvm_rule.changed
```

## Use command's 'creates' param when possible

If a file specified by 'creates' already exists, this step will not be run.

```yaml
- name: setup bash completion
  shell:
    cmd: cmctl completion bash > /etc/bash_completion.d/cmctl
    creates: /etc/bash_completion.d/cmctl
  become: yes
```

## Ansible module instead of command

For almost every command there is an Ansible module which can perform this command.
Only modules which don't require additional installation are allowed to be used.
Don't use command and shell when Ansible module is **available**
*Example*:
Instead of:

```yml
command: service auditd restart
```

Use:

```yml
service:
    name: auditd
    state: restarted
```

Instead of

```yml
command:
  cmd: make -j modules_install
  chdir: "{{ tmp_dir.path }}/quickassist/qat"
```

Use:

```yml
make:
  chdir: "{{ tmp_dir.path }}/quickassist/qat"
  target: modules_install
environment:
  "MAKEFLAGS": "-j{{ nproc_out.stdout|int + 1 }}"
become: yes
```

## Look for role in baseline-ansible

Before writing your own role check if such role doesn't already exist in baseline-ansible

## "become: yes" usage

“**become: yes**” should be only used when *absolutely necessary*.
It should also be set on smallest element possible. This can be whole role, if “**become**: yes” is needed for all tasks in role.

## Check error (failed_when) instead of using ignore_error

We sometimes check if a feature is already installed by calling a command that can result in an error. We should narrow the accepted error down and fail in other cases.

```yaml
failed_when: kernel_version.stdout is version('5.11', '<')
```

## Helm values

It is advised to use values file as a template with ansible variables and then use ansible.builtin.template to copy it to helm charts.

```yaml
- name: template and copy values.yaml
  template:
    src: "values.yaml.j2"
    dest: "{{ ne_helm_charts_default_dir }}/telegraf/values.yaml"
    mode: preserve
```

## External sources

It is prohibited to push external sources to repositories.
**It is mandatory to use commit/tag/specific release version of external source.**
If 3rdparty components with source code are needed, files should be downloaded, git cloned etc. to *project_dir* and customization should be applied.
To customize downloaded code it is suggested to use:
 - *patch*
 - *kustomize*

 Example of kustomize:

```yaml
- op: add
  path: /spec/containers/0/volumeMounts/-
  value:
    mountPath: {{ isecl_k8s_extensions }}
    name: extendedsched
    readOnly: true

- op: add
  path: /spec/containers/0/command/-
  value: --policy-config-file={{ isecl_k8s_extensions }}/scheduler-policy.json

- op: add
  path: /spec/volumes/-
  value:
    hostPath:
      path: {{ isecl_k8s_extensions }}
      type:
    name: extendedsched
```

## File/dir permissions

When setting mode for files, symbolic notation should be used.
There are 4 types of owner symbols
 - a - all
 - u - user
 - g - group
 - o - other

NOTE: Remember to set mode for all owners!
Either use *a* and then owner type

```yaml
mode: a=rx,u+w
```

Or explicitly state all

```yaml
mode: u=rw,g=r,o=
```

## Don't remove temporary files if possible

The temporary files make debugging a lot **easier**

## Data manipulation

Instead of using *sed*, *awk*, *grep* etc. try using what ansible provides.
Ansible provides Jinja2 templating which is very powerful in terms of manipulating data.

See following links for more info
 - https://docs.ansible.com/ansible/latest/user_guide/playbooks_filters.html
 - https://docs.ansible.com/ansible/latest/user_guide/complex_data_manipulation.html
 - https://jinja.palletsprojects.com/en/3.0.x/templates/

Example of complex variable manipulation

```yaml
- name: Build full packages list
  set_fact:
    install_dependencies_full_list:
      "{{
        install_dependencies[ansible_os_family] | default([]) | select('string') | list +
        install_dependencies | json_query(distribution_query) | default([]) +
        install_dependencies | json_query(distribution_major_version_query) | default([]) +
        install_dependencies | json_query(distribution_version_query) | default([])
      }}"
  vars:
    distribution_query: "{{ ansible_os_family }}[*].{{ ansible_distribution }}[][]"
    distribution_major_version_query: "{{ ansible_os_family }}[*].{{ ansible_distribution }}_{{ ansible_distribution_major_version }}[][]"
    distribution_version_query: "{{ ansible_os_family }}[*].{{ ansible_distribution }}_{{ ansible_distribution_version | replace('.','_') }}[][]"
```

Example of string manipulation

```yaml
dest: "{{ tmp_dir.path }}/{{ item | basename | regex_replace('\\.j2$', '') }}"
```

## /tmp/ directory usage

Do not explicitly use /tmp/ directory.
Either create directory in *project_dir* or use ansible.builtin.tempfile

```yaml
- name: create temp directory for pip2 installation
  tempfile:
    state: directory
    prefix: pip2-
  register: pip2_temp_dir
```

## Set defaults for variables

When reading variable which is not set by role, always add `| default()`.

```yaml
- role: infrastructure/git_repo_tool
  when: "platform_attestation_controller | default(False) or platform_attestation_node | default(False)"
```

## Handle network reliability

Often there can be network issue during some operations.
To handle such cases use *retries* and *delay*.

```yaml
- name: setup repository for kernel | get repository file
  get_url:
    url: "{{ kernel_repo_url }}"
    dest: "{{ _kernel_repo_dest }}"
    mode: a=r,u+w
  register: result
  retries: "{{ number_of_retries }}"
  until: result is succeeded
  delay: "{{ retry_delay }}"
```

NOTE: Remember to register variable and add *until* or in other case Ansible will silently switch *retries* to 1.

## Block/rescue for better debugging

For cases when something fails, but command which fails might not provide enough information, block/rescue can be used to provide more information.

```yaml
- name: ensure that main, restricted, universe and multiverse repositories are enabled
  block:
  - name: add repository
    become: yes
    apt_repository:
      repo: "{{ item }}"
    loop:
      - "deb http://archive.ubuntu.com/ubuntu {{ ansible_distribution_release }} main universe"

  rescue:
  - name: run apt update
    apt:
      update_cache: yes
    register: error_output
    become: yes

  - name: fail run apt update
    fail:
      msg: "{{ error_output }}"
```

## Task names

Task names should start with lowercase letter.

```yaml
- name: open port for Grafana
```

# Role guidelines

## Role should be independent from target host

Roles should not have any checks against which host runs it. Playbook should be the place where role is mapped to host.
NOTE: In synchronization cases delegate_to is acceptable, but if possible synchronization should be done in playbooks.

## Role configurability

Role written for one scenario can be used in multiple scenarios with some tuning.
In such case role should have a parameter passed to it during include_role or role usage.
These variables should tune, enable or disable parts of role.

```yaml
- name: open port for Grafana
  include_role:
    name: infrastructure/firewall_open_ports
  vars:
    fw_open_ports: "{{ grafana_open_ports }}"
```

## Splitting files

### Tasks file should have single responsibility

Tasks in one file should have clear and single responsibility. In other case, tasks in such file should be split based on their responsibility.

### Role files size

If file contains more than 8 tasks, consider splitting it to separate files.

### Check host state before execution

Check if host state which tasks are trying to set isn’t already active.
*Example*:
When tasks are building library/application firstly it should be checked if such library/application isn’t already installed/build with intended version before installation/building.

```yaml
- name: Check current git version
  command: git --version
  register: git_version_command
  changed_when: false

- name: Set current_git_version
  set_fact: current_git_version="{{ git_version_command.stdout.split()[-1] }}"

- name: install git from source
  include_tasks: install.yml
  when: current_git_version < git_version
```

### Advised structure

There should be one main file which controls the flow of role.
In this file there should be a check if component in desired version isn't already installed.
All other elements in main should only include sub tasks with particular stages of component deployment.
This is also a good place to consider support for multi OSes.

## Multinode support

Roles should be written in a way that it will work in multinode case.

## Variable definition

There are couple of places where variables are defined:
1. inventory/default/group_vars/(all,controller_group,edgenode_group)/10-default.yml - Variables that enable end user option to enable and configure some feature (targeted for end user)
2. inventory/default/host_vars/(host name)/10-default.yml - Variables for specific host. Used in very specific cases.
3. role/vars - Variables that will likely not change (only changed by DEK developer)
4. role/defaults - Variables that might change for example in case of version change (only changed by DEK developer)

## Declare all variables as public

All variables should be declared without any prefix which would suggest that the variable is private.

Use:

```yml
public_path: '/foo/bar'
```

instead of:

```yml
_private_path: '/foo/bar'
```

# Multi OS guidelines

DEK does support only limited set of operating systems, but all roles should be written with MultiOS support in mind.

## Main task should be OS agnostic

Main tasks should be generic and if needed it should include specialized tasks for a given OS.

## OS abstraction

Following options are possible:

1. In case there are very few OS dependencies: Use when ansible_os_family for specific **tasks**
    ```yaml
    - name: allow traffic from Kubernetes subnets in ufw
      ufw:
        rule: allow
        from: "{{ item }}"
      with_items: "{{ fw_open_subnets }}"
      when: ansible_os_family == "Debian"
    ```
2. In case there are many OS dependencies: Create an OS specific file and use include_tasks
    ```yaml
    - name: prepare {{ ansible_os_family }}-based distro
      include_tasks: "{{ ansible_os_family | lower }}.yml"
    ```
3. Create variables set dependent on OS
    ```yaml
    - name: unmask, enable and start firewall service
      systemd:
        name: "{{ firewall_service[ansible_os_family] }}"
        masked: false
        enabled: true
        state: started
    ```
4. With more variables move varibales to files and include files with vars using include_vars with with_first_found
    ```yaml
    - name: load OS specific vars
      include_vars: "{{ item }}"
      with_first_found:
      - files:
          - "{{ ansible_distribution|lower }}{{ ansible_distribution_major_version|lower }}.yml"
          - "{{ ansible_os_family|lower }}.yml"
    ```

Each option should be revised individually.

## Preferred usage of ansible_os_family

OS abstraction should be as general as possible.
In corner cases it is possible to *ansible_distribution* and *ansible_distribution_major_version*.

## Package management

Roles should install needed packages using *install_dependencies* role (check role [README](https://github.com/smart-edge-open/baseline-ansible/blob/main/infrastructure/install_dependencies/README.md) for details).

*install_dependencies* allows specifying packages for specific distributions and version.

```yaml
install_dependencies:
  RedHat:
    - package_for_all_redhat_os
    - CentOS:
      - packet_for_all_versions_of_centos
    - CentOS_7:
      - packet_for_centos_version_7
  Debian: []
```

# Playbook organization

There are sub-playbooks in dek.
Playbooks organize roles by their functionality.
There is still problematic single node and multi node deployment issue and our end goal should be to get rid of this separation with proper organization in playbooks.

Playbooks should be the source which defines where particular role should be run.
Also playbooks should be used to synchronize execution of tasks.

# Redeployment

DEK does not officially support redeployment.
But there are certain gains when roles and tasks are written with consideration of possible redeployment.

## Reduced development time

When developing new features redeployments happen a lot.
If roles were not written with support for redeployment, each time clean system would be required which would add a lot of time overhead.

## Forces good structure

When writing a role which will support redeployment there is an automatic tendency to correctly organize roles code.

## Future use

This product changes a lot and there might be cases in future where redeployment will be needed.
