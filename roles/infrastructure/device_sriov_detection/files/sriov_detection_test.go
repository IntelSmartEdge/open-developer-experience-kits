/**
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

 * Unit tests for the SR-IOV Detection Application using the testing
 * Capabilities of Go Lang.
 * The SR-IOV Detection Application detects the NIC's with specific capabilities on the
 * Linux that it runs on. So in order to test more than 90% of the code functionality
 * we needed to input in some tests hard coded data from a specific Linux:
 * Ubuntu 20.04 , host name: silpixa00401146
 * Since, at each Linux the detection will have different results - some of the tests will fail
 * in Linux machine that is not the machine above.
 * There are 4 sections of unit tests:
 * 1) TestMain Function - initializes pointers to prerequisites packages.
 * 2) Test functions that suppose to pass successfully in every Linux.
 * 3) Test functions that will pass succesfully ONLY in the Linux machine above.
 * 4) Test of the main function of the application.
 *
 *  @author Eyal Belkin
 *  @version 1.1 01/13/2022
 *
*/

package main

import (
	"flag"
	"fmt"
	"net"
	"os"
	"testing"

	"github.com/google/go-cmp/cmp"
	"github.com/jaypipes/ghw"
	"github.com/safchain/ethtool"
)

/*****************************************************************************************
 *                   Global Variables
 ****************************************************************************************/
var NETWORK_INTERFACE_PROPER_TO_SRIOV string = "eth0"        //From Ubuntu 20.04, host name: silpixa00401146
var NIC_BUS_INFO string = "0000:cc:00.1"                     //Bus info of the NIC eth0 from Ubuntu 20.04, host name: silpixa00401146
const NETWORK_INTERFACE_WITH_VALID_IPV4 string = "eno8303"   //From Ubuntu 20.04, host name: silpixa00401146
const NETWORK_INTERFACE_NOT_SUPPORTING_SRIOV string = "eth1" //Has VF's = 0 in Ubuntu 20.04, host name: silpixa00401146
const NETWORK_BUS_INFO_OF_NON_INTEL_NIC string = "e3:00.0"   //From Ubuntu 20.04, host name: silpixa00401146

var ptrEthToolHandle *ethtool.Ethtool = nil
var ptrPci *ghw.PCIInfo = nil
var networkInterfaces []net.Interface = nil

/*****************************************************************************************
 *                       TestMain  Function
 ****************************************************************************************/
//The TestMain Function will initialize pointers to 3 prerequisites packages:
// 1)net
// 2)Ethtool
// 3)GHW - PCI
// Those pointers are a MUST for the tests. So in case of failure we will not recover from panics
// like the application behaves.
func TestMain(m *testing.M) {
	fmt.Println("Initialize pointers to packages: EthTool, PCI and net")
	ptrEthToolHandle, ptrPci, networkInterfaces = InitializePackagesPointers()
	defer ptrEthToolHandle.Close()
	exitVal := m.Run()
	os.Exit(exitVal)
}

/*****************************************************************************************
 *                        TEST Functions
 ****************************************************************************************/
func Test_CreateCriteriaList(t *testing.T) {
	//Testing the creation of criteria list to the DEK product.
	criteriaList := CreateCriteriaList("dek")
	expected := SupDevice{"", "", []string{"158a", "0d58", "1593"}, nil, 0, 64, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE,
		nil, false, false, "", 0, ""}
	if diff := cmp.Diff(expected, criteriaList); diff != "" {
		t.Error(diff)
	}
}

/******************************************************************************************************************/
func Test_UpdateOutputString(t *testing.T) {
	//Using table tests pattern
	data := []struct {
		interfaceIndexToAdd  uint8
		deviceInterfaceToAdd string
		outputStringPtr      string
		expected             string
	}{
		{1, "eth0", "", "eth0\n"},
		{2, "eth1", "eth0\n", "eth0\neth1\n"},
		{3, "eth2", "eth0\neth1\n", "eth0\neth1\neth2\n"},
		{4, "eth3", "eth0\neth1\neth2\n", "eth0\neth1\neth2\neth3\n"},
		{5, "eth4", "eth0\neth1\neth2\neth3\n", ""},
	}
	for _, testLine := range data {
		t.Run(string(testLine.interfaceIndexToAdd), func(t *testing.T) {
			UpdateOutputString(testLine.interfaceIndexToAdd,
				testLine.deviceInterfaceToAdd,
				&testLine.outputStringPtr)
			if testLine.outputStringPtr != testLine.expected {
				t.Errorf("Expected %s, got %s", testLine.expected, testLine.outputStringPtr)
			}
		})
	}
}

/******************************************************************************************************************/
func Test_CheckDevicesAgainstCriteria(t *testing.T) {
	//Input NIC's slice for the CheckDevicesAgainstCriteria function:
	//In order to test every capability check against the criteria:
	//This slice contains NIC's with capabilities that match / does not match the criteria in a way that force the
	// function to check all the NIC's and all the capabilities.
	devicesInfoSlice := []SupDevice{
		{"eth0", "", []string{"1593"}, nil, 0, 64, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth1", "", []string{"eyal"}, []string{"driver2"}, 0, 64, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth2", "", []string{"0d58"}, []string{"driver1"}, 0, 128, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth3", "", []string{"158a"}, []string{"driver2"}, 40000, 256, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth4", "", []string{"158a"}, []string{"driver2"}, 40000, 60, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth5", "", []string{"0d58"}, []string{"driver2"}, 20000, 64, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth6", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, INVALID_VALUE_FOR_LINK_STATE, INVALID_VALUE_FOR_NUMA_NODE, nil, false, false, "", 0, ""},
		{"eth7", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 7, nil, false, false, "", 0, ""},
		{"eth8", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"Eyal"}, false, false, "", 0, ""},
		{"eth9", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, false, false, "", 0, ""},
		{"eth10", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, true, false, "", 0, ""},
		{"eth11", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, true, true, "", 0, ""},
		{"eth12", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, true, true, "RRU", 0, ""},
		{"eth13", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, true, true, "RRU", 8888, ""},
		{"eth14", "", []string{"0d58"}, []string{"driver2"}, 40000, 64, 1, 0, []string{"SATA"}, true, true, "RRU", 8888, "0000:cc:00.x"},
	}
	//Testing success of the function
	criteriaList := CreateCriteriaList("dek")
	outputResult := CheckDevicesAgainstCriteria(&criteriaList, devicesInfoSlice)
	expectedOutputString := "eth0\neth2\neth3\neth5\n"
	if outputResult != expectedOutputString {
		t.Errorf("Expected output string: `%s`, got `%s`", expectedOutputString, outputResult)
	}
	//Testing failure of the function
	devicesInfoSlice[5].NumVFSupp = 4
	criteriaList.Driver = append(criteriaList.Driver, "driver2")
	criteriaList.LinkSpeed = 40000
	criteriaList.LinkState = 1
	criteriaList.NUMALocation = 0
	criteriaList.ConnectorType = append(criteriaList.ConnectorType, "SATA")
	criteriaList.PTPSupport = true
	criteriaList.DDPSupport = true
	criteriaList.ProtocolOfIncomingPackets = "RRU"
	criteriaList.SpecificPortNumber = 8888
	criteriaList.CardAffinity = "0000:cc:00.x"
	outputResult = CheckDevicesAgainstCriteria(&criteriaList, devicesInfoSlice)
	expectedOutputString = "" //Since the tested function failed
	if outputResult != expectedOutputString {
		t.Errorf("Expected failure with EMPTY output string, got `%s`", outputResult)
	}
}

/******************************************************************************************************************/
func Test_DetectDevices(t *testing.T) {
	//Testing success of DetectDevices function
	supDevices := DetectDevices(ptrEthToolHandle, ptrPci, networkInterfaces)
	if supDevices == nil || len(supDevices) == 0 {
		fmt.Println("DetectDevices function failed to find proper intefaces slice in the Unit test!")
	} else {
		fmt.Printf("DetectDevices function found valid intefaces slice: %v\n", supDevices)
		//In case of finding proper devices in this Linux we will use the first NIC as input to capabilities
		//detection functions
		NETWORK_INTERFACE_PROPER_TO_SRIOV = supDevices[0].InterfaceName
		NIC_BUS_INFO = supDevices[0].PciBus
	}
	//Testing failure of DetectDevices function
	supDevices = DetectDevices(ptrEthToolHandle, nil, networkInterfaces)
	if len(supDevices) > 0 {
		t.Errorf("Expected failure with nil output from function DetectDevices with input ptrPci = nil, got `%v`", supDevices)
	}
}

/*****************************************************************************************
 *                       Detect TEST Functions with hard coded NIC's
 * (Tests that will pass successfully ONLY in: Ubuntu 20.04 , host name: silpixa00401146)
 ****************************************************************************************/
func Test_CheckIfDeviceCurrentlyUsed(t *testing.T) {
	nicWithValidIpv4Found := false
	nicProperToSriovFound := false
	//We will need to find the entire struct of the network inetrface (from net package)
	//from the network interfaces slice
	for _, networkDevice := range networkInterfaces {
		if networkDevice.Name == NETWORK_INTERFACE_WITH_VALID_IPV4 && nicWithValidIpv4Found == false {
			nicWithValidIpv4Found = true
			//Here we have the data to test the function
			if CheckIfDeviceCurrentlyUsed(networkDevice) == false {
				t.Errorf("Expected success to find the network interface '%s' as a Device Currently Used - But it failed!",
					NETWORK_INTERFACE_WITH_VALID_IPV4)
			}
		} else if networkDevice.Name == NETWORK_INTERFACE_PROPER_TO_SRIOV && nicProperToSriovFound == false {
			nicProperToSriovFound = true
			//Here we have the data to test the function
			if CheckIfDeviceCurrentlyUsed(networkDevice) == true {
				t.Errorf("Expected failure to find the network interface '%s' as a Device Currently Used - But it succeeded!",
					NETWORK_INTERFACE_PROPER_TO_SRIOV)
			}
		}
		if nicWithValidIpv4Found && nicProperToSriovFound {
			break
		}
	}
}

/******************************************************************************************************************/
func Test_CheckVendorNameAndProductId(t *testing.T) {
	//Testing success of CheckVendorNameAndProductId function
	result, deviceId := CheckVendorNameAndProductId(ptrPci, NIC_BUS_INFO)
	if result == false || deviceId == "" {
		t.Errorf("Expected success to run CheckVendorNameAndProductId function with bus info '%s' - But it failed!",
			NIC_BUS_INFO)
	}
	//Testing failures of CheckVendorNameAndProductId function
	invalidBusInfo := "invalid_Bus_Info"
	result, _ = CheckVendorNameAndProductId(ptrPci, invalidBusInfo)
	if result == true {
		t.Errorf("Expected failure to run CheckVendorNameAndProductId function with INVALID bus info - But it succeeded!")
	}
	result, _ = CheckVendorNameAndProductId(ptrPci, NETWORK_BUS_INFO_OF_NON_INTEL_NIC)
	if result == true {
		t.Errorf("Expected failure to run CheckVendorNameAndProductId function with bus info of NON INTEL NIC : %s - But it succeeded!",
			NETWORK_BUS_INFO_OF_NON_INTEL_NIC)
	}
}

/******************************************************************************************************************/
func Test_DetectNumberVFs(t *testing.T) {
	//Testing success of DetectNumberVFs function
	numberVfs := DetectNumberVFs(NETWORK_INTERFACE_PROPER_TO_SRIOV)
	if numberVfs == 0 {
		t.Errorf("Expected to find 64 or more VF's in the NIC '%s' - But it found 0 VF's!",
			NETWORK_INTERFACE_PROPER_TO_SRIOV)
	}
	//Testing failure of DetectNumberVFs function
	numberVfs = DetectNumberVFs(NETWORK_INTERFACE_NOT_SUPPORTING_SRIOV)
	if numberVfs != 0 {
		t.Errorf("Expected to find 0 VF's in the NIC '%s' - But it found %d VF's!",
			NETWORK_INTERFACE_NOT_SUPPORTING_SRIOV, numberVfs)
	}
}

/******************************************************************************************************************/
func Test_GetDeviceDriver(t *testing.T) {
	//Testing success of GetDeviceDriver function
	driverList := GetDeviceDriver(ptrEthToolHandle, NETWORK_INTERFACE_PROPER_TO_SRIOV)
	if driverList[0] == "" {
		t.Errorf("Expected to find valid driver in the NIC '%s' - But it found empty string!",
			NETWORK_INTERFACE_PROPER_TO_SRIOV)
	}
	//Testing failure of GetDeviceDriver function
	driverList = GetDeviceDriver(ptrEthToolHandle, "Eyal")
	if driverList[0] != "" {
		t.Errorf("Expected to find empty string for driver with NO VALID network interface - But it found valid driver!")
	}
}

/******************************************************************************************************************/
func Test_GetDeviceLinkSpeed(t *testing.T) {
	//Testing success of GetDeviceLinkSpeed function
	deviceLinkedSpeed := GetDeviceLinkSpeed(ptrEthToolHandle, NETWORK_INTERFACE_PROPER_TO_SRIOV)
	if deviceLinkedSpeed == 0 {
		t.Errorf("Expected to find valid linked speed in the NIC '%s' - But it found 0!",
			NETWORK_INTERFACE_PROPER_TO_SRIOV)
	}
	//Testing failure of GetDeviceLinkSpeed function
	deviceLinkedSpeed = GetDeviceLinkSpeed(ptrEthToolHandle, "Eyal")
	if deviceLinkedSpeed != 0 {
		t.Errorf("Expected to find linked speed = 0 with NO VALID network interface - But it found positive linked speed!")
	}
}

/******************************************************************************************************************/
func Test_GetDeviceLinkState(t *testing.T) {
	//Testing success of GetDeviceLinkState function
	deviceLinkedState := GetDeviceLinkState(ptrEthToolHandle, NETWORK_INTERFACE_PROPER_TO_SRIOV)
	if deviceLinkedState == INVALID_VALUE_FOR_LINK_STATE {
		t.Errorf("Expected to find valid linked state in the NIC '%s' - But it found %d!",
			NETWORK_INTERFACE_PROPER_TO_SRIOV, INVALID_VALUE_FOR_LINK_STATE)
	}
	//Testing failure of GetDeviceLinkState function
	deviceLinkedState = GetDeviceLinkState(ptrEthToolHandle, "Eyal")
	if deviceLinkedState != INVALID_VALUE_FOR_LINK_STATE {
		t.Errorf("Expected to find INVALID VALUE FOR LINK STATE ( %d ) with NO VALID network interface - But it found valid link state!",
			INVALID_VALUE_FOR_LINK_STATE)
	}
}

/*****************************************************************************************
 *                       Testing the main function
 ****************************************************************************************/
// This function tests ONLY the main function response to the input parameters.
func Test_RunMain(t *testing.T) {
	//Turnning off the panic.
	defer func() {
		r := recover()
		if r != nil {
			fmt.Println("RECOVER from panic: ", r)
		}
	}()

	//Using table tests pattern
	testCases := []struct {
		testName string
		args     []string
	}{
		{"flags set with no debug mode", []string{"dek"}},
		{"flags set with debug mode", []string{"dek", "debug_mode"}},
		//Since there is no recover function in main function of the application the recover in the loop
		//of this test will occur ONLY ONCE (character of recover function in GoLang).
		//So currently the failure test contain only 1 example: empty input string
		{"flags set to empty string", []string{""}},
	}
	for mainTestIndex, tc := range testCases {
		// this call is required because otherwise flags panics, if args are set between flag.Parse calls
		flag.CommandLine = flag.NewFlagSet(tc.testName, flag.ExitOnError)
		// we need a value to set args[0] to, cause flag begins parsing at args[1]
		os.Args = append([]string{tc.testName}, tc.args...)
		main()

		if mainTestIndex == 2 {
			// Never reaches here if 'flags set to empty string' case panics.
			t.Errorf("Testing main function with args of empty string did not panic like it should!")
		}
	}
}
