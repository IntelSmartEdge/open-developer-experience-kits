#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

"Provides configuration possibilities via Redfish API"

import json
import os
import warnings
import logging
import time
import requests # pylint: disable=import-error

# use root logger, the same one that calling script is using
logger = logging.getLogger()


class NoTpmModuleException(Exception):
    "Exception for missing TPM module in the system"
    def __str__(self):
        return "No 'TpmSecurity' found in system bios attributes. " \
               "Please ensure TPM module is installed in the system."


def configure_logger(debug: bool, logfile: str):
    "Configure logger"

    if debug:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logger.setLevel(level)

    # stdout handler
    handler = logging.StreamHandler()
    if debug:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s | %(name)s | %(message)s",
            "%H:%M:%S"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s | %(message)s",
            "%H:%M:%S"))
    handler.setLevel(level)
    logger.addHandler(handler)

    # log file handler (always remove previous logs of this script)
    if os.path.exists(logfile):
        os.remove(logfile)
    handler = logging.FileHandler(logfile)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s | %(name)s | %(message)s",
        "%H:%M:%S"))
    handler.setLevel(level)
    logger.addHandler(handler)

    # configure underlying loggers
    if debug:
        logging.getLogger("requests").setLevel(level)
        logging.getLogger("urllib3").setLevel(level)

    # ignore warnings coming from underlying modules
    warnings.filterwarnings("ignore")


class RedfishAPI:
    "Redfish management REST API wrapper"

    # pylint: disable=too-many-instance-attributes, too-many-public-methods
    # The current number is reasonable

    # How many seconds to wait for the server to send data before giving up
    HTTP_RESPONSE_TIMEOUT = 10

    def __init__(self, address, username, password, proxy=None, verbose=False):
        self.address = address
        self.username = username
        self.password = password
        # Note: when proxy is None, env variable https_proxy is read by 'requests' module
        self.proxy = proxy
        self.verbose = verbose
        # System ID and Manager ID acquired, vary depending on platform
        self._system_id = None
        self._manager_id = None
        # BIOS attributes to be applied
        self._pending_bios_attributes = {}
        # For enabling SGX a number of BIOS attributes must be applied in given sequence
        self._pending_bios_attributes_stages = []
        # Current acquired BIOS attributes
        self._bios_attributes = {}
        # Hint that reboot is needed in order for config job to complete
        self.reboot_required = False
        # All REST calls use single session object
        self._session = requests.Session()
        self._session.auth = (username, password)

    def _request(self, method: str, endpoint: str, check=True, timeout=HTTP_RESPONSE_TIMEOUT, **kwargs):
        """Generic HTTP request.

        Args:
            method: name of REST method available in requests library. Possible values: get, post, put, patch, delete.
            endpoint: path to be appended to URL. If it is missing /redfish/v1 prefix, then prefix will also be added.
            check: to check response and raise exception in case of bad status code.
            kwargs: additional named parameters to pass for HTTP request.
        Returns:
            requests.Response: received Response object.
        """
        def print_extended_info(response):
            # some calls have valid empty responses
            if response.text:
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    logger.error("Malformed JSON received. Data: %s", response.text)
                    return

                try:
                    logger.info("Extended Info Message: %s\n", json.dumps(data, indent=2))
                except Exception as e:
                    logger.error("Can't decode extended info message. Exception: %s", e)

        def check_response(response):
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                logger.error("Request returned incorrect response code: %s", e)
                print_extended_info(response)
                raise e

        # by default we expect json data in POST and PATCH
        if "headers" not in kwargs and method in ("post", "patch"):
            kwargs["headers"] = {"content-type": "application/json"}

        # convert dict to json string
        if "data" in kwargs:
            kwargs["data"] = json.dumps(kwargs["data"])

        # support case where user provided full Redfish path
        if endpoint.startswith('/redfish'):
            url = f"https://{self.address}{endpoint}"
        else:
            url = f"https://{self.address}/redfish/v1{endpoint}"

        # get HTTP method attribute by name and calls it
        response = getattr(self._session, method)(url,
                                             verify=False,  # nosec
                                             proxies=self.proxy,
                                             timeout=timeout,
                                             **kwargs)
        if check:
            check_response(response)

        if self.verbose:
            print_extended_info(response)

        return response

    def check_connectivity(self, endpoint="", error_passthrough=False):
        "Check if base URL is accessible for further operations"
        try:
            self._request("get", endpoint, timeout=10)
        except requests.exceptions.RequestException as e:
            if error_passthrough:
                raise e
            return False
        return True

    ###### BASIC OPERATIONS ######

    @property
    def system_id(self) -> str:
        """Returns id of first system managed by interface.

        Note:
            Assumes there will be only single member.
            Returned system_id can vary depending on platform.
        """
        if not self._system_id:
            response = self._request("get", "/Systems")
            self._system_id = str(response.json()["Members"][0]["@odata.id"]).replace("/redfish/v1/Systems/", "")
        return self._system_id

    @property
    def manager_id(self) -> str:
        """Returns id of first manager.

        Note:
            Assumes there will be only single member.
            Returned manager_id can vary depending on platform.
        """
        if not self._manager_id:
            response = self._request("get", "/Managers")
            self._manager_id = str(response.json()["Members"][0]["@odata.id"]).replace("/redfish/v1/Managers/", "")
        return self._manager_id

    @property
    def system_info(self) -> dict:
        "Returns dictionary with ComputerSystem schema attributes"
        response = self._request("get", f"/Systems/{self.system_id}")
        return response.json()

    @property
    def manager_info(self) -> dict:
        "Returns dictionary with Manager schema attributes"
        response = self._request("get", f"/Managers/{self.manager_id}")
        return response.json()

    @property
    def is_supermicro(self) -> bool:
        "Checks if system is Supermicro"
        return self.system_id == "1"

    @property
    def is_dell(self) -> bool:
        "Checks if system is Dell"
        return self.system_id == "System.Embedded.1"

    @property
    def bios_attributes(self) -> dict:
        """Returns dictionary with current bios attributes.
           To lower redundant GET requests, attributes are cached.
        """
        if not self._bios_attributes:
            self.get_bios_attributes()
        return self._bios_attributes

    def get_bios_attributes(self):
        "Reacquire current bios attributes"
        response = self._request("get", f"/Systems/{self.system_id}/Bios")
        self._bios_attributes = response.json()["Attributes"]

    def set_bios_attributes(self, bios_attributes: dict):
        """Sets pending attributes dictionary.
           For changes to be applied finalize_bios_settings() should be called.
        """
        self._pending_bios_attributes = {}
        self._pending_bios_attributes.update(bios_attributes)

    def print_system_info(self):
        "Print info about remote system"
        boot_method = self.system_info["Boot"]["BootSourceOverrideMode"]
        logger.info("Detected HW system: %s, %s", self.system_info["Model"], self.system_info["Manufacturer"])
        logger.info("Detected iDRAC version: %s", self.manager_info["FirmwareVersion"])
        logger.info("Detected BIOS version: %s", self.system_info["BiosVersion"])
        logger.info("Detected boot method: %s", boot_method)
        logger.info("Retrieved system id: %s", self.system_id)
        logger.info("Retrieved manager id: %s", self.manager_id)

    def enable_secure_boot(self):
        "Enable Secure Boot feature"
        self._pending_bios_attributes["SecureBoot"] = "Enabled"

    def disable_secure_boot(self):
        "Disable Secure Boot feature"
        self._pending_bios_attributes["SecureBoot"] = "Disabled"

    def get_secure_boot(self) -> bool:
        "Returns bool value representing status of Secure Boot feature"
        return self.bios_attributes["SecureBoot"] == "Enabled"

    def enable_tpm(self):
        "Enable TPM feature"
        self._pending_bios_attributes["TpmSecurity"] = "On"

    def disable_tpm(self):
        "Disable TPM feature"
        self._pending_bios_attributes["TpmSecurity"] = "Off"

    def get_tpm(self) -> bool:
        "Returns bool value representing status of TPM feature"

        if "TpmSecurity" not in self.bios_attributes:
            raise NoTpmModuleException
        return self.bios_attributes["TpmSecurity"] == "On"

    def enable_sgx(self):
        "Enable Intel SGX feature"
        self._pending_bios_attributes_stages = \
            [{"MemOpMode": "OptimizerMode", "NodeInterleave": "Disabled"},
             {"MemoryEncryption": "SingleKey"},
             {"IntelSgx": "On", "SgxFactoryReset": "On"},
             {"PrmrrSize": "64G"}]

    def disable_sgx(self):
        "Disable Intel SGX feature"
        self._pending_bios_attributes["IntelSgx"] = "Off"

    def get_sgx(self) -> bool:
        "Returns bool value representing status of Intel SGX feature"
        return self.bios_attributes["IntelSgx"] == "On"

    ###### CONFIG JOBS ######

    def create_config_job(self) -> requests.Response:
        "Creates bios config job for Dell iDRAC (for applying changes added to /Bios/Settings endpoint)"

        logger.info("Creating config job.")

        payload = {"TargetSettingsURI": "/redfish/v1/Systems/System.Embedded.1/Bios/Settings"}
        return self._request("post",
                             "/Managers/iDRAC.Embedded.1/Jobs",
                             data=payload)

    def get_pending_config_jobs(self, job_type="BIOSConfiguration") -> list:
        "Returns list of jobs of given type that are marked as 'Scheduled'"
        response = self._request("get", "/Managers/iDRAC.Embedded.1/Jobs?$expand=*($levels=1)")
        return [job  for job in response.json()["Members"]
                if job["JobState"] == "Scheduled" and job["JobType"] == job_type]

    def delete_pending_config_jobs(self):
        "Deletes pending config jobs"
        for job in self.get_pending_config_jobs():
            logger.info("Deleting job: %s", job['Id'])
            self._request("delete", f"/Managers/iDRAC.Embedded.1/Jobs/{job['Id']}")

    def get_job_info(self, job_id: str) -> dict:
        "Returns job data"
        response = self._request("get", f"/Managers/iDRAC.Embedded.1/Jobs/{job_id}")
        return response.json()

    def wait_for_job_finished(self, job_id: str, timeout=1800, check_every=12):
        """Waits for job with specific id to be finished.

        Args:
            job_id: Job ID
            timeout: Total time to wait until system is in desired power state (in seconds).
            check_every: Time between checks (in seconds).
        """

        logger.info("Waiting for job %s to finish ...", job_id)

        prev_percentage = None
        for _ in range(timeout//check_every):
            job_data = self.get_job_info(job_id)

            if "PercentComplete" in job_data and job_data["PercentComplete"] != prev_percentage:
                prev_percentage = job_data["PercentComplete"]
                logger.info("Job %s completion is %s percent.", job_id, prev_percentage)

            time.sleep(check_every)

            job_state = job_data["JobState"]
            if job_state in ["Scheduled", "Running",
                            "New", "Scheduling",
                            "ReadyForExecution", "Waiting"]:
                continue

            if job_state in ["Failed", "CompletedWithErrors", "RebootFailed"]:
                msg = ["Job did not succeeded.",
                       "Job details:"] + [f"{k}: {v}" for k, v in job_data.items()]
                raise Exception("\n\t".join(msg))

            if job_state == "Completed":
                logger.info("Job %s completed.", job_id)
                break
        else:
            msg = ["Job did not succeeded within given interval.",
                   f"JobState {job_state}",
                   "Job details:"] + [f"{k}: {v}" for k, v in job_data.items()]
            raise Exception("\n\t".join(msg))

    ###### CHANGING BIOS ATTRIBUTES ######

    def apply_pending_bios_attributes(self):
        "From pending changes BIOS attributes, remove those that are already applied"

        # check if configuration is not already satisfied
        current = self.bios_attributes
        for key, val in self._pending_bios_attributes.copy().items():
            if key in current and current[key] == val:
                del self._pending_bios_attributes[key]

    def get_pending_bios_attributes_stages(self):
        "Get pending BIOS attributes and stages"

        # if SGX stages are necessary, merge them with rest of BIOS attributes,
        # so they are all applied with minimum number of reboots
        if self._pending_bios_attributes_stages:
            stages = self._pending_bios_attributes_stages.copy()
            stages[0].update(self._pending_bios_attributes)
        else:
            stages = [self._pending_bios_attributes]

        pending_attrs = {}
        pending_stages = []

        # filter out attributes and stages that are already applied
        current = self.bios_attributes
        for stage in stages:
            s = {}
            for key, val in stage.items():
                if key not in current or current[key] != val:
                    pending_attrs[key] = val
                    s[key] = val
            if s:
                pending_stages.append(s)

        return pending_attrs, pending_stages

    def patch_bios_settings(self, payload_data: dict):
        """Sends PATCH REST request to /Bios/Settings endpoint.

        Args:
            payload_data: data to be send as json.
        Returns:
            requests.Response: received Response object.
        """

        logger.debug("Patching bios attributes: %s", payload_data["Attributes"])

        return self._request("patch",
                             f"/Systems/{self.system_id}/Bios/Settings",
                             data=payload_data)

    def finalize_bios_settings(self):
        """Finalizes changes to BIOS configuration
           (on Dell machines changing BIOS settings require creation of config job to take effect)
        """

        # Filter out settings that are already satisfied
        self.apply_pending_bios_attributes()

        # Return if no change in settings
        if not self._pending_bios_attributes:
            return

        # Delete pending config jobs as there can be only single config job
        self.delete_pending_config_jobs()

        # Update only differing settings
        self.patch_bios_settings({"Attributes": self._pending_bios_attributes})

        # Create config job
        self.create_config_job()
        # Clear pending attributes and hint that reboot is needed in order for config job to complete
        self._pending_bios_attributes = {}
        self.reboot_required = True

    ###### POWER CYCLING ######

    def system_reset_action(self, reset_type: str):
        """Resets system.

        Args:
            reset_type: one of [On, ForceOff, ForceRestart, GracefulShutdown, PushPowerButton, Nmi]
        """
        endpoint = f"/Systems/{self.system_id}/Actions/ComputerSystem.Reset"
        payload = {"ResetType": reset_type}
        return self._request("post", endpoint, data=payload)

    def wait_for_power_state(self, power_state: str, timeout=60, check_every=2):
        """Waits for system power state change.

        Args:
            power_state: Desired power state - string, one of [On, Off]
            timeout: Total time to wait until system is in desired power state (in seconds).
            check_every: Time between checks (in seconds).
        """
        for _ in range(timeout//check_every):
            # sometimes call may fail with status code 500, so must catch the exception and continue
            try:
                if self.system_info["PowerState"] == power_state:
                    return True
            except Exception as e:
                logger.error ("Error while waiting for power state change: %s", e)
            time.sleep(check_every)
        return False

    def system_shutdown(self):
        "Shutdown system"

        logger.info("Setting PowerState: GracefulShutdown")
        self.system_reset_action("GracefulShutdown")

        logger.info("Waiting for PowerState: Off ...")
        if not self.wait_for_power_state("Off"):
            logger.warning("System did not gracefully shutdown within time limit. Trying with PowerState: ForceOff ...")
            self.system_reset_action("ForceOff")

            logger.info("Waiting for PowerState: Off ...")
            if not self.wait_for_power_state("Off"):
                raise Exception("System did not forcefully shutdown within time limit")

        logger.info("System is PowerState: Off")

    def system_start(self):
        "Start system"

        logger.info("Setting PowerState: On")
        self.system_reset_action("On")

        logger.info("Waiting for PowerState: On ...")
        if not self.wait_for_power_state("On"):
            raise Exception("System did not started within time limit")

    def perform_shutdown(self):
        "Shutdown system"

        power_state = self.system_info["PowerState"]
        logger.info("Current PowerState is: %s", power_state)

        if power_state == "Off":
            logger.info("System is already shutdown")
        else:
            logger.info("Shutting down ...")
            self.system_shutdown()

    def perform_reboot(self):
        "Reboots system"

        power_state = self.system_info["PowerState"]
        logger.info("Current PowerState is: %s", power_state)
        logger.info("Rebooting ...")

        if power_state == "On":
            self.system_shutdown()

        self.system_start()

        logger.info("Rebooting completed.")

    ###### VIRTUAL MEDIA ######

    def check_virtual_media_support(self):
        "Checks if Virtual Media is supported on this iDRAC version"
        endpoint = "/Managers/iDRAC.Embedded.1/VirtualMedia/CD"
        response = self._request("get", endpoint)
        data = response.json()

        if 'Actions' in data:
            for i in data['Actions']:
                if i in ("#VirtualMedia.InsertMedia", "#VirtualMedia.EjectMedia"):
                    return True
        return False

    def get_virtual_media_info(self):
        "Prints info about Virtual Media"
        endpoint = "/Managers/iDRAC.Embedded.1/VirtualMedia"
        response = self._request("get", endpoint)
        data = response.json()

        virtual_media_uris = [media_uri  for i in data['Members']  for media_uri in i.values()]

        for uri in virtual_media_uris:
            logger.debug("Detailed information for detected Virtual Media URI %s:", uri)
            response = self._request("get", uri)
            logger.debug(json.dumps(response.json(), indent=2))

    def insert_virtual_media(self, image_url):
        "Attaches given image at iDRAC"
        endpoint = "/Managers/iDRAC.Embedded.1/VirtualMedia/RemovableDisk/Actions/VirtualMedia.InsertMedia"
        payload = {'Image': image_url, 'Inserted': True, 'WriteProtected': True}
        self._request("post", endpoint, data=payload)

    def eject_virtual_media(self):
        "Detaches currently attached image at iDRAC"
        endpoint = "/Managers/iDRAC.Embedded.1/VirtualMedia/RemovableDisk/Actions/VirtualMedia.EjectMedia"
        # empty payload is required
        payload = {}
        self._request("post", endpoint, data=payload)
        # some delay is needed after eject, because if next operation
        # right after this one will be inserting, it will fail!
        time.sleep(5)

    def validate_media_status(self, expect_inserted: bool):
        """Checks if image is attached or detached as expected

        Args:
            expect_inserted: True if we expect that image is inserted, False if we expect that image is ejected
        """
        endpoint = "/Managers/iDRAC.Embedded.1/VirtualMedia/RemovableDisk"
        response = self._request("get", endpoint)
        data = response.json()

        logger.info("Virtual Media for RemovableDisk attach status: %s",
            "Inserted" if data["Inserted"] else "Ejected")

        if expect_inserted and not data["Inserted"]:
            raise Exception("Media not attached")
        if not expect_inserted and data["Inserted"]:
            raise Exception("Media not ejected")

    def set_next_onetime_boot_device_virtual_media(self):
        """Sets next one-time boot to Virtual Media.
           Note: This uses Dell-specific Redfish protocol extension.
        """

        endpoint = "/Managers/iDRAC.Embedded.1/Attributes"
        # possible boot devices: vFDD, VCD-DVD
        payload = {"Attributes": {
            "ServerBoot.1.FirstBootDevice": "vFDD",
            "ServerBoot.1.BootOnce": "Enabled"
        }}
        self._request("patch", endpoint, data=payload)

    ###### BOOT OPTIONS ######

    def set_next_boot_device(self, boot_device: str, onetime: bool):
        """Sets next boot to devices other than Virtual Media

        Args:
            boot_device: possible boot devices: None, Pxe, Floppy, Cd, Usb, Hdd, SDCard,
                         BiosSetup, Diags, Utilities, UefiTarget, UefiHttp
            onetime: True to boot selected device only once, False to boot persistently
        """

        endpoint = f"/Systems/{self.system_id}"
        if boot_device == 'None':
            payload = {'Boot': {'BootSourceOverrideEnabled': 'Disabled'}}
        else:
            payload = {'Boot': {
                'BootSourceOverrideEnabled': 'Continuous' if not onetime
                                             else 'Once',
                'BootSourceOverrideTarget': boot_device
            }}

        # those targets require changing from Legacy to UEFI boot mode
        if boot_device in ('UefiTarget', 'UefiHttp'):
            payload['Boot']['BootSourceOverrideMode'] = 'UEFI'

        self._request("patch", endpoint, data=payload)

    def set_boot_method(self, boot_method: str):
        """Change boot method

        Args:
            boot_method: possible boot methods: Legacy, UEFI
        """

        endpoint = f"/Systems/{self.system_id}"
        payload = {'Boot': {'BootSourceOverrideMode': boot_method}}
        self._request("patch", endpoint, data=payload)
