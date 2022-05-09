#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

"Convenience script to display and modify some BIOS settings via Redfish API"

import os
import sys
import logging
import argparse
import time

import redfish_api # pylint: disable=import-error

# create root logger for this script
logger = logging.getLogger()


def parse_args():
    "Parse command-line arguments"

    parser = argparse.ArgumentParser(
        description="Convenience script to display and modify "
                    "some BIOS settings via Redfish API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n"
            "  ./%(prog)s --ip 10.22.22.139 -u root -p rootpass "
            "--sb on --tpm off\n\n")
    parser.add_argument("-v", "--verbose",
                        help="Extended verbosity",
                        required=False,
                        action="store_true",
                        default=False)
    parser.add_argument("--ip", help="MGMT IP address", required=True)
    parser.add_argument("--user", "-u", help="MGMT username", required=True)
    parser.add_argument("--password", "-p", help="MGMT password", required=True)
    parser.add_argument("--proxy",
        help="Proxy server for traffic redirection. "
        "This can be HTTP/HTTPS or SOCK5 proxy. "
        "If omitted, https_proxy environment var will be used.",
        required=False)
    parser.add_argument("--sb",
                        help="Configure Secure Boot",
                        choices=["on", "off"],
                        required=False)
    parser.add_argument("--tpm",
                        help="Configure Trusted Platform Module",
                        choices=["on", "off"],
                        required=False)
    parser.add_argument("--sgx",
                        help="Configure Intel Software Guard Extensions",
                        choices=["on", "off"],
                        required=False)
    parser.add_argument("--boot-method",
                        help="Configure boot method",
                        choices=["legacy", "uefi"],
                        required=False)

    return parser.parse_args()


def main():
    "Main execution function"

    args = parse_args()

    redfish_api.configure_logger(debug=False, logfile=os.path.splitext(os.path.basename(__file__))[0] + '.log')

    # try to access Redfish management API with proxy, if passed by user
    proxies = None
    if args.proxy:
        logger.info("Connecting to %s using passed proxy %s ...", args.ip, args.proxy)
        proxies = {"https" : args.proxy}

    elif "https_proxy" in os.environ:
        logger.info("Connecting to %s using environment var https_proxy %s ...", args.ip, os.environ["https_proxy"])

    else:
        logger.info("Connecting to %s without proxy ...", args.ip)

    rapi = redfish_api.RedfishAPI(args.ip, args.user, args.password, proxy=proxies, verbose=args.verbose)
    if not rapi.check_connectivity():
        logger.error("Redfish API is inaccessible. Please ensure IP address is correct, and correct proxy is passed.")
        sys.exit(1)

    rapi.print_system_info()

    # human readable states
    hr_status = {True: "enabled", False: "disabled"}

    # print current state of BIOS attributes
    boot_method = rapi.system_info["Boot"]["BootSourceOverrideMode"]
    logger.info("--------")
    logger.info("Current state of configuration:")
    logger.info("  Boot method: %s", boot_method)
    logger.info("  SecureBoot: %s", hr_status[rapi.get_secure_boot()])
    logger.info("  TPM: %s", hr_status[rapi.get_tpm()])
    logger.info("  IntelSgx: %s", hr_status[rapi.get_sgx()])

    # if no action passed, just print status and quit
    if not args.tpm and not args.sb and not args.sgx and not args.boot_method:
        sys.exit(0)

    calls = {"tpm": {"on": rapi.enable_tpm,
                     "off": rapi.disable_tpm,
                     "get": rapi.get_tpm},
             "sb": {"on": rapi.enable_secure_boot,
                    "off": rapi.disable_secure_boot,
                    "get": rapi.get_secure_boot},
             "sgx": {"on": rapi.enable_sgx,
                     "off": rapi.disable_sgx,
                     "get": rapi.get_sgx}}

    # change attributes
    for command, methods in calls.items():
        option = getattr(args, command)
        current = methods['get']()
        # don't enable options if already enabled (and don't disable them if already disabled)
        if option == 'on' and not current or \
           option == 'off' and current:
            # call corresponding function to enable or disable given option
            methods[option]()

    # if user passed boot method, and it differs from current boot method, convert it to proper value
    changed_boot_method = None
    if args.boot_method:
        new_boot_method = "UEFI"  if args.boot_method == 'uefi'  else "Legacy"
        if boot_method != new_boot_method:
            changed_boot_method = new_boot_method

    # print attributes pending changes
    logger.info("--------")
    pending_attrs, pending_stages = rapi.get_pending_bios_attributes_stages()
    num_reboots = len(pending_stages)
    if pending_attrs or changed_boot_method:
        logger.info("Following configuration will be changed:")
        if changed_boot_method:
            logger.info("  Boot method: %s", changed_boot_method)
            num_reboots += 1
        for k,v in sorted(pending_attrs.items()):
            logger.info("  %s: %s", k, v)

        try:
            x = None
            while x not in ['y', 'n']:
                x = input("Applying BIOS attributes require %s reboot(s) of remote machine. "
                            "OK to proceed? [y/n]: " % num_reboots)
                if x == 'n':
                    sys.exit(0)
                elif x == 'y':
                    break
        except (EOFError, KeyboardInterrupt):
            # in case of Ctrl+C/Ctrl+D, print missing new line and quit, as if user would choose 'n'
            print('\n')
            sys.exit(0)
    else:
        logger.info("No BIOS attributes will be changed - they are already in desired value.")
        sys.exit(0)

    # apply changes

    logger.info("--------")
    stage_idx = 1
    if changed_boot_method:
        logger.info("Applying stage %s/%s, boot method change: %s", stage_idx, num_reboots, changed_boot_method)
        rapi.set_boot_method(changed_boot_method)

        # reboot and wait till changes are applied
        rapi.perform_reboot()
        job_id = rapi.get_pending_config_jobs()[0]["Id"]
        rapi.wait_for_job_finished(job_id)

        stage_idx += 1

    for stage in pending_stages:
        logger.info("Applying stage %s/%s, attributes: %s", stage_idx, num_reboots, stage)
        rapi.set_bios_attributes(stage)
        rapi.finalize_bios_settings()

        if rapi.reboot_required:
            # reboot and wait till changes are applied
            rapi.perform_reboot()
            job_id = rapi.get_pending_config_jobs()[0]["Id"]
            rapi.wait_for_job_finished(job_id)
            rapi.reboot_required = False

        # This fixed sleep is a workaround. If we perform stages too quickly then
        # PATCH /redfish/v1/Systems/System.Embedded.1/Bios/Settings fails with 503 code.
        # Message: "Unable to apply the configuration changes because an
        # import or export operation is currently in progress."
        # and "Resolution": "Wait for the current import or export
        # operation to complete and retry the operation.
        # If the issue persists, contact your service provider."
        time.sleep(15)

        stage_idx += 1

    # quit script
    logger.info("--------")
    logger.info("All actions finished successfully")
    sys.exit(0)


if __name__ == '__main__':
    main()
