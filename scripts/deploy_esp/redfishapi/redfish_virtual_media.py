#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

"""Convenience script to provision remote host via Redfish API,
   using Virtual Media image hosted on HTTP/HTTPS/NFS/SMB share"""

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
        description="Convenience script to provision remote host via Redfish API, "
                    "using Virtual Media image hosted on HTTP/HTTPS/NFS/SMB share",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n"
            "  ./%(prog)s --ip 10.22.22.139 -u root -p rootpass "
            "--image-url http://10.102.102.192/usb/SEO_DEK_UBUNTU/uos-efi.img\n\n")
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
    parser.add_argument("--image-url",
                        help="Image URL to be mounted at remote host as Virtual Media. "
                        "This should be EFI image, with .img extension",
                        required=True)

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

    boot_method = rapi.system_info["Boot"]["BootSourceOverrideMode"]
    if boot_method != "UEFI":
        logger.error("Only boot method 'UEFI' is supported. Change your BIOS settings.")
        sys.exit(1)

    # check prerequisites and print current media info
    if rapi.check_virtual_media_support() is False:
        logger.error("This iDRAC version does not support Virtual Media")
        sys.exit(1)

    # print some debug info
    logger.info("--------")
    rapi.get_virtual_media_info()

    status = rapi.get_secure_boot()
    if status:
        logger.info('Secure Boot is enabled. Disabling it first to allow ESP provisioning ...')
        rapi.disable_secure_boot()
        rapi.finalize_bios_settings()

        # TODO: is this reboot needed? because we will after mounting image reboot anyway!
        if rapi.reboot_required:
            # reboot and wait till changes are applied
            rapi.perform_reboot()
            job_id = rapi.get_pending_config_jobs()[0]["Id"]
            rapi.wait_for_job_finished(job_id)
            rapi.reboot_required = False

    logger.info("Starting remote provisioning of host %s with image %s", args.ip, args.image_url)

    # make sure image is ejected first, otherwise inserting will fail
    try:
        rapi.validate_media_status(expect_inserted=False)
    except Exception:
        rapi.eject_virtual_media()
        rapi.validate_media_status(expect_inserted=False)

    # insert remote image
    rapi.insert_virtual_media(args.image_url)
    rapi.validate_media_status(expect_inserted=True)

    # reboot into inserted image
    rapi.set_next_onetime_boot_device_virtual_media()
    rapi.perform_reboot()

    # provisioning will start here (phase 1 - uOS), which will finish with reboot if successful

    # 25min of wait time should be enough (usually it takes around 15-20min)
    # TODO: this unfortunately does not catch Off event currently!
    # so for now we just hardcoded to 25min wait, after which we eject!
    # logger.info("Waiting for PowerState: Off (to finish uOS provisioning phase) ...")
    # if not rapi.wait_for_power_state("Off", timeout=25*60, check_every=5):
    #     raise Exception("System did not shutdown within time limit.")

    # logger.info("Waiting for PowerState: On ...")
    # if not rapi.wait_for_power_state("On"):
    #     raise Exception("System did not started within time limit.")
    logger.info("Waiting for provisioning (phase 1 - uOS) to finish ...")
    time.sleep(25*60)

    # we no longer need to keep image mounted for provisioning phase 2
    rapi.eject_virtual_media()
    rapi.validate_media_status(expect_inserted=False)

    # provisioning continues here (phase 2 - EK deployment) but we currently have no way
    # to wait for finish and check status of deployment (few reboots will occur until
    # deployment is successful or not).
    # TODO: wait until bare os boots up

    # quit script
    logger.info("--------")
    logger.info("All actions finished successfully")
    sys.exit(0)


if __name__ == '__main__':
    main()
