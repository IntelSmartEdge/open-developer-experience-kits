/**
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

 * This application will be executed from an Ansible role during the provisioning process
 * in deployment of experiance kit.
 * The goal is to find 4 NIC's in the Linux for configuring and using SR-IOV.
 *
 *  @author Eyal Belkin
 *  @version 1.1 01/13/2022
 *
 * Inputs:
 * 1) EK type
 * 2) Debug mode
 *
 * Output: A print of string with 4 NIC's interfaces
 *
 * A brief:
 * This application will:
 * 1) Create a capabilities criteria list according to the EK input type.
 * 2) Detect available Intels NICs with device id, bus info and suppoert for SR-IOV.
 * 3) Find capabilities for each NIC.
 * 4) Comparing those NIC's capabilities to te capabilities in the criteria.
 * 5) If 4 NIC's will pass this filtering, print their interface.
 * 6) The execution command in the Linux will output the print in 5) into file and will use
 *    it during the provisioning to configure the SR-IOV.
*/

package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"

	"github.com/jaypipes/ghw"
	"github.com/safchain/ethtool" //Package for Linux only
)

/*****************************************************************************************
 *                   Global Variables, Constants and Structs
 ****************************************************************************************/
const NUMBER_OF_DEVICES_REQUIRED = 4
const INVALID_VALUE_FOR_LINK_STATE = 3
const INVALID_VALUE_FOR_NUMA_NODE = -1

var DEBUG_MODE bool = false

type SupDevice struct {
	InterfaceName             string
	PciBus                    string
	DeviceId                  []string //For the devices there will be 1 string only: 1 device id
	Driver                    []string //For the devices there will be 1 string only: 1 driver
	LinkSpeed                 uint64   //Units: Mb/s
	NumVFSupp                 uint32
	LinkState                 uint32
	NUMALocation              int8     //Store the value of the NUMA Node of the device in the Linux
	ConnectorType             []string //For the devices there will be 1 string only: 1 connector module
	DDPSupport                bool
	PTPSupport                bool
	ProtocolOfIncomingPackets string
	SpecificPortNumber        uint64
	CardAffinity              string
}

/*****************************************************************************************
 *                        Functions
 ****************************************************************************************/
/****************************************************************************************************************
    @brief Helper function for print to the stdout in debug mode

    @param stringToPrint - string to print to stdout
    @param args - values of variables to print as part of the string

******************************************************************************************************************/
func PrintStdOut(stringToPrint string, args ...interface{}) {
	if DEBUG_MODE == true {
		log.Printf(stringToPrint, args...)
	}
}

/****************************************************************************************************************
    @brief Hard coded creation of capabilities criteria list based on the EK type input.
           Since this list is hard coded there is no need to validate it before using it.

    @param inputEK - string : the EK input type.
    @return SupDevice struct : A capabilities criteria list.

******************************************************************************************************************/
func CreateCriteriaList(inputEK string) SupDevice {
	criteriaList := SupDevice{"", "", nil, nil, 0, 0, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""}
	switch inputEK {
	case "dek":
		{
			criteriaList.DeviceId = []string{"158a", "0d58", "1593", "159b", "1592", "188a"}
			criteriaList.NumVFSupp = 64
		}
	default:
	}
	return criteriaList
}

/****************************************************************************************************************
    @brief Creates the output string of the application.

    @param [in] InterfaceIndexToAdd - byte : The interface index to add to the output string
    @param [in] deviceInterfaceToAdd - string : The device interface value to add to the output string
    @param [out] outputStringPtr - pointer to string : pointer to the output string of the application.
                                   A pointer to an empty string in case of invalid interface index.

******************************************************************************************************************/
func UpdateOutputString(interfaceIndexToAdd uint8, deviceInterfaceToAdd string, outputStringPtr *string) {
	if interfaceIndexToAdd > 0 && interfaceIndexToAdd < 5 {
		*outputStringPtr += deviceInterfaceToAdd + "\n"
	} else {
		*outputStringPtr = ""
	}
}

/****************************************************************************************************************
    @brief Helper function: Searches for device capability in capabilities criteria list.

    @param Slice of strings: Capabilities Criteria List
    @param String : Device Capability to find in the list
    @param String : The Device Interface - for printings
    @param String : The Capability Type to find - for printings
    @return true in case of finding the capability in the criteria list and false otherwise.

******************************************************************************************************************/
func SearchCapabilityInCriteriaList(capabilityCriteriaList []string, deviceCapability string, deviceInterface string, capabilityType string) bool {
	capabilityFound := false
	//Checking if the device capability is one of the capabilities in the criteria list
	for _, capabilityInCriteriaList := range capabilityCriteriaList {
		if capabilityInCriteriaList == deviceCapability {
			capabilityFound = true
			break
		}
	}
	if capabilityFound == false {
		PrintStdOut("The NIC with interface: %s has %s : %s . So it is not fit for the input EK to use for SR-IOV",
			deviceInterface, capabilityType, deviceCapability)
	}
	return capabilityFound
}

/****************************************************************************************************************
    @brief This function pass through on all the available Intels NICs with device id,
	       bus info and support for SR-IOV. For each one of them the function compares the NIC
		   capabilities against the capabilities in the criteria list.
		   - In case of full match the function will save the device interface in the output string.
		   - In case of finding 4 suitable NIC's the function will stop and finish.
    @param A pointer to a criteria list of capabilities.
    @param A slice of devices structs. Each struct contain the capabilities of the device.
    @return String : the Output string of the application. Empty string in case of failure.

******************************************************************************************************************/
func CheckDevicesAgainstCriteria(criteriaListPtr *SupDevice, devicesInfoSlice []SupDevice) string {
	successfulCheckedDevices := 0
	outputString := ""
	for _, device := range devicesInfoSlice {
		//Device Id check
		if len(criteriaListPtr.DeviceId) > 0 && len(device.DeviceId) > 0 &&
			SearchCapabilityInCriteriaList(criteriaListPtr.DeviceId, device.DeviceId[0], device.InterfaceName, "Device ID") == false {
			continue
		}
		//Driver check
		if len(criteriaListPtr.Driver) > 0 && len(device.Driver) > 0 &&
			SearchCapabilityInCriteriaList(criteriaListPtr.Driver, device.Driver[0], device.InterfaceName, "Driver") == false {
			continue
		}
		//Link Speed check
		if criteriaListPtr.LinkSpeed > 0 && device.LinkSpeed < criteriaListPtr.LinkSpeed {
			PrintStdOut("The NIC with interface: %s support maximum link speed of: %d Mb/s, while the requirment is: %d Mb/s, So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.LinkSpeed, criteriaListPtr.LinkSpeed)
			continue
		}
		//Number of VFs support check
		if criteriaListPtr.NumVFSupp > 0 && device.NumVFSupp < criteriaListPtr.NumVFSupp {
			PrintStdOut("The NIC with interface: %s supports maximum number of VF's: %d, while the requirment is: %d So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.NumVFSupp, criteriaListPtr.NumVFSupp)
			continue
		}
		//Link State check
		if criteriaListPtr.LinkState != INVALID_VALUE_FOR_LINK_STATE && device.LinkState != criteriaListPtr.LinkState {
			PrintStdOut("The NIC with interface: %s supports the link state %d, while the requirment is: %d So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.LinkState, criteriaListPtr.LinkState)
			continue
		}
		//NUMA Location check
		if criteriaListPtr.NUMALocation > INVALID_VALUE_FOR_NUMA_NODE && device.NUMALocation != criteriaListPtr.NUMALocation {
			PrintStdOut("The NIC with interface: %s supports NUMA location of: %d, while the requirment is: %d So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.NUMALocation, criteriaListPtr.NUMALocation)
			continue
		}
		//Connector Type check
		if len(criteriaListPtr.ConnectorType) > 0 && len(device.ConnectorType) > 0 &&
			SearchCapabilityInCriteriaList(criteriaListPtr.ConnectorType, device.ConnectorType[0], device.InterfaceName, "Connector Type") == false {
			continue
		}
		//DDP Support check
		if criteriaListPtr.DDPSupport && device.DDPSupport == false {
			PrintStdOut("The NIC with interface: %s does not support DDP! while the requirment does! So it is not fitting for the input EK to use for SR-IOV",
				device.InterfaceName)
			continue
		}
		//PTP Support check
		if criteriaListPtr.PTPSupport && device.PTPSupport == false {
			PrintStdOut("The NIC with interface: %s does not support PTP! while the requirment does! So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName)
			continue
		}
		//Protocol Of Incoming Packets check
		if criteriaListPtr.ProtocolOfIncomingPackets != "" && device.ProtocolOfIncomingPackets != criteriaListPtr.ProtocolOfIncomingPackets {
			PrintStdOut("The NIC with interface: %s supports a protocol of incoming packets: %s, while the requirment is: %s So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.ProtocolOfIncomingPackets, criteriaListPtr.ProtocolOfIncomingPackets)
			continue
		}
		//Specific Port Number check
		if criteriaListPtr.SpecificPortNumber > 0 && device.SpecificPortNumber != criteriaListPtr.SpecificPortNumber {
			PrintStdOut("The NIC with interface: %s supports a specific port number: %d, while the requirment is: %d So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.SpecificPortNumber, criteriaListPtr.SpecificPortNumber)
			continue
		}
		//Card Affinity check
		if criteriaListPtr.CardAffinity != "" && device.CardAffinity != criteriaListPtr.CardAffinity {
			PrintStdOut("The NIC with interface: %s supports card affinity of: %s, while the requirment is: %s So it is not fit for the input EK to use for SR-IOV",
				device.InterfaceName, device.CardAffinity, criteriaListPtr.CardAffinity)
			continue
		}
		//After finising all the checks against the criteria we will keep this suitable device for SR-IOV in the devices slice
		successfulCheckedDevices++
		UpdateOutputString(uint8(successfulCheckedDevices), device.InterfaceName, &outputString)
		if successfulCheckedDevices == NUMBER_OF_DEVICES_REQUIRED {
			return outputString
		}
	}
	PrintStdOut("Found %d supported NIC's while the requirement is : %d. There are insufficient NIC's that fit for the input EK to use for SR-IOV!",
		successfulCheckedDevices, NUMBER_OF_DEVICES_REQUIRED)
	return ""
}

/****************************************************************************************************************
    @brief Find if network device is UP and have IPV4 address.

    @param Interface struct from net package for a network device in the Linux.
    @return true in case of :
            1) Finding that the device is UP and has valid IPV4 address.
            2) The device is UP but the API has a problem with the IP address.

            false otherwise

******************************************************************************************************************/
func CheckIfDeviceCurrentlyUsed(networkDevice net.Interface) bool {

	if networkDevice.Flags&net.FlagUp > 0 {
		addrs, err := networkDevice.Addrs()
		if err == nil && addrs != nil {
			for _, ipAddres := range addrs {
				PrintStdOut("Device with interface %s has IP address: %v\n", networkDevice.Name, ipAddres)
				ipNet, ok := ipAddres.(*net.IPNet)
				if ok && ipNet.IP.To4() != nil {
					PrintStdOut("Device with interface: %s is UP and have correct IPV4 address. We will not use it for SRIOV\n",
						networkDevice.Name)
					return true
				}
			}
		}
		if err != nil {
			PrintStdOut("Device with interface: %s has error in finding IP address: %v. We will not use it for SRIOV\n", networkDevice.Name, err)
			//The device is UP but the API failed and there is an error - We can't conclude that the device is not currently used.
			return true
		}
	}
	return false
}

/****************************************************************************************************************
    @brief Finds:
	       1) The Device Id of a network device in the Linux
		   2) The vendor name of a network device in the Linux

    @param A pointer to PCIInfo in GHW package
    @param A string : The bus information of the device.
    @return true and the device id in case of finding:
            1) Valid device id
            2) The vendor of the device is Intel only.

            false and empty string otherwise.

******************************************************************************************************************/
func CheckVendorNameAndProductId(ptrPci *ghw.PCIInfo, busInfo string) (bool, string) {
	deviceInfo := ptrPci.GetDevice(busInfo)
	if deviceInfo == nil {
		PrintStdOut("could not retrieve PCI device information for bus info: %s\n", busInfo)
		return false, ""
	}
	//PCI products are often referred to by their "device ID".
	//We use the term "product ID" in ghw because it more accurately reflects what the identifier is for
	//a specific product line produced by the vendor.
	product := deviceInfo.Product
	if len(product.ID) == 0 {
		PrintStdOut("Device with bus info: %s has not Product Id! We will not use it for SR-IOV!\n",
			busInfo)
		return false, ""
	}
	vendor := deviceInfo.Vendor
	if vendor.Name != "Intel Corporation" {
		PrintStdOut("Device with bus info: %s has vendor: %s which is not Intel! We will not use it for SR-IOV!\n",
			busInfo, vendor.Name)
		return false, ""
	}
	return true, product.ID
}

/****************************************************************************************************************
    @brief Finds the maximum number of VF's that a device can support.
           It uses the cat command on the file in Linux:
           /sys/class/net/[Device Interface]/device/sriov_totalvfs.
           In case that this file is empty or has 0 value we conclude that this device does not suppoet
           SR-IOV.
    THIS FUNCTION CAN RUN ONLY IN LINUX OS
    @param String: The Device Interface
    @return Integer : The number of VF's - the result of the Linux cat command.
                      0 in case of failure.

******************************************************************************************************************/
func DetectNumberVFs(deviceInterface string) uint32 {
	catCmd := "cat /sys/class/net/" + deviceInterface + "/device/sriov_totalvfs"
	maxVfsByte, err := exec.Command("bash", "-c", catCmd).CombinedOutput()
	fileFullPath := "/sys/class/net/" + deviceInterface + "/device/sriov_totalvfs"
	if err != nil {
		PrintStdOut("Device with interface name %s has cat command error : %s on file: %s\n",
			deviceInterface, err, fileFullPath)
		return 0
	}
	PrintStdOut("The cat command result for device interface: %s, on file: %s, is : %s\n",
		deviceInterface, fileFullPath, maxVfsByte)
	//Slicing the '\n' from the result of the Linux cat command with strings library
	maxVfsStr := strings.TrimSpace(string(maxVfsByte))
	maxVfs, err := strconv.Atoi(maxVfsStr)
	if err != nil {
		PrintStdOut("Device with interface name %s has strconv.Atoi command error : %s\n", deviceInterface, err)
		return 0
	}
	return uint32(maxVfs)
}

/****************************************************************************************************************
    @brief Finds the driver name of NIC in Linux

    @param A pointer to handler of Ethtool package
    @param string : Network Device Interface
    @return The driver name as: slice of strings - with only 1 string in it
	        (in order to use it in the detect devices function)
			slice with 1 empty string in case of failure.

******************************************************************************************************************/
func GetDeviceDriver(ptrEthtoolHandle *ethtool.Ethtool, networkDeviceInterface string) []string {
	driver, err := ptrEthtoolHandle.DriverName(networkDeviceInterface)
	if err != nil {
		PrintStdOut("Ethtool package could not find the driver of device with Interface: %s . Error: %v\n",
			networkDeviceInterface, err)
		driver = ""
	}
	return []string{driver}
}

/****************************************************************************************************************
    @brief Finds link speed of NIC in Linux

    @param A pointer to handler of Ethtool package
    @param string : Network Device Interface
    @return The link speed as long long integer
	        0 in case of failure.

******************************************************************************************************************/
func GetDeviceLinkSpeed(ptrEthtoolHandle *ethtool.Ethtool, networkDeviceInterface string) uint64 {
	ethToolMap, err := ptrEthtoolHandle.CmdGetMapped(networkDeviceInterface) // ethToolMap is: map[string]uint64
	var linkSpeed uint64 = 0
	if err != nil || ethToolMap == nil {
		PrintStdOut("Ethtool package could not find the link speed of device with Interface: %s . Error: %v\n",
			networkDeviceInterface, err)
	} else {
		linkSpeed = ethToolMap["Speed"]
	}
	return linkSpeed
}

/****************************************************************************************************************
    @brief Finds link state of NIC in Linux

    @param A pointer to handler of Ethtool package
    @param string : Network Device Interface
    @return The link state as integer
	        3 in case of failure.

******************************************************************************************************************/
func GetDeviceLinkState(ptrEthtoolHandle *ethtool.Ethtool, networkDeviceInterface string) uint32 {
	linkState, err := ptrEthtoolHandle.LinkState(networkDeviceInterface)
	if err != nil {
		PrintStdOut("Ethtool package could not find the link state of device with Interface: %s . Error: %v\n",
			networkDeviceInterface, err)
		linkState = INVALID_VALUE_FOR_LINK_STATE
	}
	return linkState
}

/****************************************************************************************************************
    @brief Detects available Intels NICs with device id, bus info and suppoert for SR-IOV.
	       Find additional capabilities for each NIC that passed the filters above.

    @param A pointer to handler of Ethtool package
    @param A pointer to PCIInfo in GHW package
    @param A Slice of Interface in net package
    @return A slice of NIC's after detection and filtering with additional capabilities.
	        Empty slice in case of failure.

******************************************************************************************************************/
func DetectDevices(ptrEthtoolHandle *ethtool.Ethtool, ptrPci *ghw.PCIInfo, networkInterfaces []net.Interface) []SupDevice {
	supDevices := []SupDevice{}
	if ptrEthtoolHandle == nil || ptrPci == nil || networkInterfaces == nil {
		PrintStdOut("Bad input to function DetectDevices! Some of the input pointers are nil!")
		return supDevices
	}
	for _, networkDevice := range networkInterfaces {
		//First check: Bus info
		deviceBusInfo, err := ptrEthtoolHandle.BusInfo(networkDevice.Name)
		if err != nil || len(deviceBusInfo) == 0 || deviceBusInfo == "N/A" {
			PrintStdOut("Device with interface %s has no valid bus information. Error : %v\n", networkDevice.Name, err)
			continue
		}
		//Second check: If the device currently used - Up with IP address
		if CheckIfDeviceCurrentlyUsed(networkDevice) == true {
			continue
		}
		//Third check: SR-IOV support: Check the sriov_totalvfs from the Linux file system :
		// In case of 0 VF's: We will conclude that this device does not support SR-IOV.
		// Otherwise we will save the number of the max VF's in the devices slice.
		maxVfs := DetectNumberVFs(networkDevice.Name)
		if maxVfs == 0 {
			PrintStdOut("Device with interface: %s has 0 sriov_totalvfs! This device does not support SR-IOV!\n", networkDevice.Name)
			continue
		}
		//Fourth check: Detect Vendor and Device Id
		result, deviceId := CheckVendorNameAndProductId(ptrPci, deviceBusInfo)
		if result == false {
			continue
		}
		deviceIdList := []string{deviceId}
		//Detect additional capabilities of the network device
		driverList := GetDeviceDriver(ptrEthtoolHandle, networkDevice.Name)
		linkSpeed := GetDeviceLinkSpeed(ptrEthtoolHandle, networkDevice.Name)
		linkState := GetDeviceLinkState(ptrEthtoolHandle, networkDevice.Name)
		supDevice := SupDevice{networkDevice.Name, deviceBusInfo, deviceIdList, driverList, linkSpeed, maxVfs, linkState, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""}
		supDevices = append(supDevices, supDevice)
	}
	return supDevices
}

/****************************************************************************************************************
@brief Helper function: Collect initialization of pointers to:
       - Handler of Ethtool package
	   - PCIInfo in GHW package
	   - Slice of Interface in net package

       ** The memory for the Handler of Ethtool package WILL BE FREE IN THE MAIN FUNCTION
@return 2 pointers and 1 slice
        Exit of the enire application in case of failure.

******************************************************************************************************************/
func InitializePackagesPointers() (*ethtool.Ethtool, *ghw.PCIInfo, []net.Interface) {
	//Initialize pointer to EthTool
	ptrEthToolHandle, err := ethtool.NewEthtool()
	if err != nil {
		log.Printf("New Ethtool failed!\n")
		panic("New Ethtool failed!")
	}

	//Initialize pointer to PCI in the GHW package
	ptrPci, err := ghw.PCI()
	if err != nil {
		log.Print(fmt.Errorf("Error getting PCI info: %v", err.Error()))
		panic("Error getting PCI info!")
	}

	//Extracting a slice of all network interfaces from package net
	networkInterfaces, err := net.Interfaces()
	if err != nil {
		log.Print(fmt.Errorf("Network Interfaces not found : %v\n", err.Error()))
		panic("Network Interfaces not found!")
	}
	return ptrEthToolHandle, ptrPci, networkInterfaces
}

/*****************************************************************************************
 *                       Main Function
 ****************************************************************************************/
func main() {
	//Checking input parameter
	if len(os.Args) != 2 && len(os.Args) != 3 {
		panic("Input parameter MUST be: 1 or 2 strings only!")
	}
	if len(os.Args) == 3 && os.Args[2] == "debug_mode" {
		DEBUG_MODE = true
	}
	//Creating the criteria list for the input: A specific experiance kit
	criteriaList := CreateCriteriaList(os.Args[1])
	if criteriaList.DeviceId == nil {
		log.Printf("Invalid input! %s is not a valid experiance kit!", os.Args[1])
		panic("Wrong Experience Kit input! Creating criteria list for the devices in the input EK failed!")
	}
	PrintStdOut("The criteria list of EK from type: %s is: \n%+v\n", os.Args[1], criteriaList)
	//Initialize Packages Pointers and the list of all network interfaces in this Linux
	ptrEthToolHandle, ptrPci, networkInterfaces := InitializePackagesPointers()
	defer ptrEthToolHandle.Close()

	//Detecting all network devices in this Linux
	supDevices := DetectDevices(ptrEthToolHandle, ptrPci, networkInterfaces)
	if supDevices == nil || len(supDevices) == 0 {
		log.Print(fmt.Errorf("Available Network Devices for SR-IOV has not found!\n"))
		panic("Available Network Devices for SR-IOV has not found!")
	}
	if len(supDevices) < NUMBER_OF_DEVICES_REQUIRED {
		log.Printf("For an EK the requirement for SR-IOV is %d NIC's. In this OS there are only %d NIC's available!",
			NUMBER_OF_DEVICES_REQUIRED, len(supDevices))
		panic("Can't find enough Network Devices available for SR-IOV!")
	}

	//Logs in debug mode
	if DEBUG_MODE == true {
		log.Printf("\n")
		log.Printf("DEVICES SLICE BEFORE CHECKING AGAINST CRITERIA: \n")
		for _, networkDevice := range supDevices {
			log.Println(networkDevice)
		}
		log.Printf("\n")
	}

	//Comparing the devices in the slice to the SupDevice criteria
	outputInterfacesString := CheckDevicesAgainstCriteria(&criteriaList, supDevices)
	if outputInterfacesString == "" {
		panic("There are available Intels NICs with device id, bus info and suppoerted SR-IOV. But some / all of them have not met with the input EK criteria!")
	}
	//Output the result of the device detection
	PrintStdOut("OUTPUT STRING : \n")
	//Printing in release mode: the content of the string will output into a file
	fmt.Print(outputInterfacesString)
}
