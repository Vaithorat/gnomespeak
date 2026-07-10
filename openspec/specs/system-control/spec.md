# System Control — Planned

## Purpose
Execute Windows system-level commands via voice, including volume control, display brightness, shutdown, sleep, and lock.

## Requirements

### Requirement: Volume Control
The system SHALL adjust system audio volume.
#### Scenario: Set Volume
- GIVEN the user says "set volume to 50%" or "volume up" / "volume down"
- WHEN the command is parsed
- THEN the system SHALL use Windows Core Audio API or `nircmd` to set the master volume level

### Requirement: Display Brightness
The system SHALL adjust display brightness.
#### Scenario: Set Brightness
- GIVEN the user says "brightness 75%" or "brightness up"
- WHEN the command is parsed
- THEN the system SHALL use WMI or `powershell` to adjust the monitor brightness

### Requirement: Power Management
The system SHALL execute power commands.
#### Scenario: Shutdown
- GIVEN the user says "shutdown computer" or "turn off PC"
- WHEN the command is parsed
- THEN the system SHALL confirm with the user
- AND SHALL execute `shutdown /s /t 30` upon confirmation

#### Scenario: Restart
- GIVEN the user says "restart computer"
- WHEN the command is parsed
- THEN the system SHALL confirm with the user
- AND SHALL execute `shutdown /r /t 30`

#### Scenario: Sleep
- GIVEN the user says "sleep" or "put computer to sleep"
- WHEN the command is parsed
- THEN the system SHALL execute `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`

#### Scenario: Lock
- GIVEN the user says "lock computer" or "lock my PC"
- WHEN the command is parsed
- THEN the system SHALL execute `rundll32.exe user32.dll,LockWorkStation`

### Requirement: Confirmation for Destructive Actions
The system SHALL require user confirmation before executing shutdown or restart.
#### Scenario: Confirm Dialog
- GIVEN a shutdown or restart command is received
- WHEN the server processes it
- THEN the system SHALL send a confirmation request to the client
- AND SHALL wait for the user to confirm before executing

### Non-Goals
- The system will NOT support hardware-level brightness control (requires monitor DDC/CI)
- The system will NOT support per-application volume control
