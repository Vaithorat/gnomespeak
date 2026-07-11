# Passwordless Configuration

## Purpose
Eliminate the master password requirement from the Windows server application, allowing automatic startup without user intervention.

## Requirements

### Requirement: Auto-Unlock on Startup (Server)
The system SHALL automatically unlock the configuration without prompting for a password.
#### Scenario: Server Starts Without Password Prompt
- GIVEN the server application starts
- WHEN initialization occurs
- THEN the system SHALL call `config.auto_unlock()` with the default password
- AND SHALL NOT display a password dialog
- AND SHALL proceed directly to server startup

#### Scenario: Default Password Used
- GIVEN the system needs to unlock the config
- WHEN `auto_unlock()` is called
- THEN the system SHALL use the default password "voicetalk"
- AND SHALL unlock the Fernet-encrypted config automatically

### Requirement: No Password Field in Settings (Client)
The settings UI SHALL NOT display a master password field.
#### Scenario: Settings Dialog Opens
- GIVEN the user opens the Settings dialog
- WHEN the dialog renders
- THEN there SHALL be no password input field
- AND the save button SHALL only persist API keys and server URL

### Requirement: Direct Server Setup (Server)
The server SHALL initialize with a hardcoded default password.
#### Scenario: Server main() Execution
- GIVEN the server runs via `python server.py`
- WHEN `main()` is called
- THEN it SHALL call `server.setup("voicetalk")` directly
- AND SHALL NOT call `prompt_setup()` for interactive configuration
- AND SHALL start the WebSocket server immediately

### Non-Goals
- The system will NOT implement password change functionality
- The system will NOT support multiple user accounts
- The system will NOT encrypt API keys at rest beyond the existing Fernet encryption
- The system will NOT implement role-based access control
