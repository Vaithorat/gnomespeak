# Configuration & Secrets Management

## Purpose
Securely store and manage the user's API key, server URL, and email credentials across both the Android client and the Windows server.

## Requirements

### Requirement: Client Settings Persistence
The Android client SHALL persist user settings across app restarts.
#### Scenario: Save Settings
- GIVEN the user has entered a server URL and API key on the Settings screen
- WHEN the user taps "Save"
- THEN the values SHALL be stored using `@react-native-async-storage/async-storage`
- AND SHALL be available on the next app launch

#### Scenario: Load Settings
- GIVEN the app launches
- WHEN the root component mounts
- THEN the system SHALL load saved settings from AsyncStorage
- AND SHALL apply them to the WebSocket service

#### Scenario: Default Values
- GIVEN no settings have been saved before
- WHEN the settings are loaded
- THEN the server URL SHALL default to `192.168.1.100:8765`
- AND the API key SHALL default to empty string

### Requirement: Server-Side Encrypted Config
The Windows server SHALL encrypt secrets at rest using Fernet symmetric encryption.
#### Scenario: First-Time Setup
- GIVEN the server is started for the first time
- WHEN no config.json exists
- THEN the system SHALL prompt for a master password
- AND SHALL derive a Fernet encryption key using PBKDF2-HMAC-SHA256 with 600,000 iterations
- AND SHALL generate a random 16-byte salt
- AND SHALL prompt for the OpenAI API key

#### Scenario: Unlock Existing Config
- GIVEN a config.json already exists with encrypted data
- WHEN the server starts
- THEN the system SHALL prompt for the master password
- AND SHALL derive the decryption key from the stored salt and provided password
- AND SHALL decrypt the secrets for use

#### Scenario: Wrong Master Password
- GIVEN an existing config.json
- WHEN the wrong master password is provided
- THEN the system SHALL fail to decrypt
- AND SHALL exit with an error message

#### Scenario: Email Configuration
- GIVEN the server setup prompts for configuration
- WHEN the user opts to configure email
- THEN the system SHALL prompt for SMTP server, port, username, and password
- AND SHALL encrypt and store all values alongside the API key

### Requirement: Config Persistence
The server SHALL persist encrypted configuration to disk.
#### Scenario: Save Config
- GIVEN secrets have been set during setup
- WHEN the user completes configuration
- THEN the system SHALL write config.json with the encrypted blob and salt
- AND SHALL not store any secrets in plaintext

### Requirement: API Key Masking
The Android client SHALL obscure the API key in the UI.
#### Scenario: Key Visibility Toggle
- GIVEN the user is on the Settings screen
- WHEN the API key field is displayed
- THEN it SHALL be masked by default (`secureTextEntry=true`)
- AND SHALL have a "Show"/"Hide" toggle button
