# Passwordless Configuration

## Purpose
Eliminate the master password requirement from the Windows server application, allowing automatic startup without user intervention. The master password is generated randomly on first run and stored locally — never hardcoded in source.

## Requirements

### Requirement: Random Password on First Run
The system SHALL generate a random master password on first startup.
#### Scenario: First Launch
- GIVEN the server has never been started (no `.master` file exists)
- WHEN initialization occurs
- THEN the system SHALL generate a 32-character password via `secrets.token_urlsafe(24)`
- AND SHALL store it in a `.master` file next to `config.json`
- AND SHALL use it to encrypt the Fernet-encrypted config

### Requirement: Auto-Unlock on Subsequent Starts
The system SHALL automatically unlock the configuration without prompting for a password.
#### Scenario: Server Starts
- GIVEN the server application starts and `.master` file exists
- WHEN initialization occurs
- THEN the system SHALL read the password from `.master`
- AND SHALL call `config.unlock(password)` automatically
- AND SHALL NOT display a password dialog
- AND SHALL proceed directly to server startup

### Requirement: No Hardcoded Passwords
The system SHALL NOT contain any hardcoded password strings in source code.
#### Scenario: Source Code Audit
- GIVEN the codebase is searched for password constants
- WHEN any `.py` file is inspected
- THEN there SHALL be no hardcoded string used as a master password
- AND the `DEFAULT_MASTER_PASSWORD` constant SHALL NOT exist

### Requirement: No Password Field in Settings (Client)
The settings UI SHALL NOT display a master password field.
#### Scenario: Settings Dialog Opens
- GIVEN the user opens the Settings dialog
- WHEN the dialog renders
- THEN there SHALL be no password input field
- AND the save button SHALL only persist API keys and server URL

### Requirement: Direct Server Setup (Server)
The server SHALL initialize without requiring a password argument.
#### Scenario: Server main() Execution
- GIVEN the server runs via `python server.py`
- WHEN `main()` is called
- THEN it SHALL call `server.setup()` with no arguments
- AND SHALL NOT call `prompt_setup()` for interactive configuration
- AND SHALL start the WebSocket server immediately

### Non-Goals
- The system will NOT implement password change functionality
- The system will NOT support multiple user accounts
- The system will NOT encrypt API keys at rest beyond the existing Fernet encryption
- The system will NOT implement role-based access control
