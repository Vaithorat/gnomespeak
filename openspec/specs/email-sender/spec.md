# Email Sender

## Purpose
Send emails via SMTP using voice commands, with encrypted credential storage.

## Requirements

### Requirement: SMTP Configuration
The system SHALL support configurable SMTP server settings stored in encrypted config.
#### Scenario: Configure Email
- GIVEN the user opts to configure email during server setup
- WHEN the setup prompts for credentials
- THEN the system SHALL accept SMTP server host, port, username, and password
- AND SHALL encrypt and store them alongside the OpenAI API key

#### Scenario: Use Defaults
- GIVEN the user does not specify an SMTP server
- WHEN the setup saves email config
- THEN the SMTP server SHALL default to `smtp.gmail.com`
- AND the port SHALL default to `587`

### Requirement: Email Sending
The system SHALL send emails via the configured SMTP server with TLS.
#### Scenario: Successful Send
- GIVEN valid SMTP credentials and network connectivity
- WHEN a `send_email` command is executed
- THEN the system SHALL construct a MIME multipart message with From, To, Subject, and body
- AND SHALL connect to the SMTP server on the configured port
- AND SHALL upgrade to TLS via `starttls`
- AND SHALL authenticate with the stored credentials
- AND SHALL send the message
- AND SHALL return success with "Email sent to {to}"

#### Scenario: No Configuration
- GIVEN email credentials have not been configured
- WHEN a `send_email` command is executed
- THEN the system SHALL return failure with "Email not configured"
- AND SHALL NOT attempt to send

### Requirement: Error Handling
The system SHALL handle SMTP errors gracefully.
#### Scenario: Authentication Failure
- GIVEN the SMTP credentials are invalid
- WHEN the server attempts to authenticate
- THEN the SMTPAuthenticationError SHALL be caught
- AND the system SHALL return failure with "Email authentication failed"

#### Scenario: Network Error
- GIVEN the SMTP server is unreachable
- WHEN the server attempts to connect
- THEN any connection error SHALL be caught
- AND the system SHALL return failure with a descriptive error message
