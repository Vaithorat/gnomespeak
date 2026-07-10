# Bluetooth Control

## Purpose
Enable voice control of Bluetooth on Windows — detect hardware, power radio on/off, scan for devices, and connect/disconnect. The AI agent orchestrates the sequence as needed.

## Requirements

### Requirement: Hardware Detection (Server)
The system SHALL detect Bluetooth hardware presence and status.
#### Scenario: Detect Bluetooth Radio
- GIVEN the control_bluetooth tool is called with action="status"
- WHEN the handler executes
- THEN the system SHALL run PowerShell `Get-BluetoothRadio`
- AND SHALL return: whether BT hardware exists, radio enabled state, radio name

#### Scenario: No Bluetooth Hardware
- GIVEN the PC has no Bluetooth adapter
- WHEN the handler checks status
- THEN the system SHALL return `{"available": false}`
- AND the agent SHALL inform the user via the result message

### Requirement: Radio Power Control (Server)
The system SHALL turn Bluetooth on and off.
#### Scenario: Turn On
- GIVEN action="on"
- WHEN the handler executes
- THEN the system SHALL run `Get-BluetoothRadio | Set-BluetoothRadio -Enabled $true`
- AND SHALL return the new status

#### Scenario: Turn Off
- GIVEN action="off"
- WHEN the handler executes
- THEN the system SHALL run `Get-BluetoothRadio | Set-BluetoothRadio -Enabled $false`
- AND SHALL return success

### Requirement: Device Scanning (Server)
The system SHALL scan for nearby Bluetooth devices.
#### Scenario: List Devices
- GIVEN action="scan"
- WHEN the handler executes
- THEN the system SHALL enumerate paired and available Bluetooth devices
- AND SHALL return device names, MAC addresses, and connection status

#### Scenario: Empty Results
- GIVEN no Bluetooth devices are found
- WHEN the handler executes
- THEN the system SHALL return an empty device list
- AND the agent SHALL inform the user

### Requirement: Device Connection (Server)
The system SHALL connect to a specified Bluetooth device by name.
#### Scenario: Connect
- GIVEN action="connect" and a device_name
- WHEN the handler executes
- THEN the system SHALL find the device by name from the device list
- AND SHALL attempt to pair/connect using Windows Bluetooth API via `winrt`
- AND SHALL return success with the device name

#### Scenario: Disconnect
- GIVEN action="disconnect" and a device_name
- WHEN the handler executes
- THEN the system SHALL disconnect the specified device
- AND SHALL return success

#### Scenario: Device Not Found
- GIVEN action="connect" with a device_name not in the device list
- WHEN the handler executes
- THEN the system SHALL return failure with "Device not found"
- AND the agent SHALL ask the user for the correct name

### Requirement: Auto-Resolution via Agent (Integration)
The system SHALL let the AI agent orchestrate Bluetooth actions automatically.
#### Scenario: Agent Decides Sequence
- GIVEN the user says "connect my speaker"
- WHEN the agent receives this
- THEN it SHALL call get_system_info to check BT hardware
- AND if BT is off, SHALL turn it on first
- AND SHALL scan for devices
- AND if multiple found, SHALL call ask_user to pick one
- AND SHALL connect to the chosen device
- AND SHALL return "Connected to {device}"

### Requirement: No Client-Side Changes (Client)
The system SHALL handle Bluetooth entirely on the server side.
#### Scenario: Client Receives Result Only
- GIVEN the server is executing Bluetooth commands
- WHEN the tool completes
- THEN the client SHALL only see result or question messages
- AND SHALL NOT need any Bluetooth-specific UI
