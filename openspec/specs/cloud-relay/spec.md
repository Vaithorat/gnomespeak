# Cloud Relay — Planned

## Purpose
Enable WebSocket communication over the internet by tunneling the local server through a cloud relay service, eliminating the need for both devices to be on the same local network.

## Requirements

### Requirement: Relay Service Integration
The system SHALL support tunneling the local WebSocket server through a cloud relay.
#### Scenario: Service Options
- GIVEN the user wants internet-based access
- WHEN configuring the relay
- THEN the system SHALL support at least one of:
  - ngrok (free tier, TCP tunnel)
  - Cloudflare Tunnel (free, `cloudflared`)
  - Custom relay server (self-hosted)

#### Scenario: One-Time URL
- GIVEN the relay service is started
- WHEN the tunnel establishes
- THEN the system SHALL generate a public URL (e.g., `wss://<random>.ngrok.io`)
- AND SHALL display it for the user to enter in the Android app

#### Scenario: Client Configuration
- GIVEN a relay URL is available
- WHEN the user enters it in the Android app settings
- THEN the client SHALL connect via `wss://` (secure WebSocket) instead of `ws://`

### Requirement: Automatic Tunnel Management
The server SHALL optionally manage the tunnel lifecycle.
#### Scenario: Start Tunnel
- GIVEN the user enables cloud mode in server config
- WHEN the server starts
- THEN the system SHALL spawn the tunnel process (e.g., `ngrok http 8765`)
- AND SHALL pass the generated URL to the connection status display

#### Scenario: Tunnel Health Check
- GIVEN the tunnel is active
- WHEN the tunnel process exits unexpectedly
- THEN the system SHALL detect the failure
- AND SHALL attempt to restart the tunnel

### Requirement: Security Considerations
The relay SHALL not compromise credential security.
#### Scenario: End-to-End Encryption
- GIVEN commands are sent over the relay
- WHEN the tunnel uses `wss://`
- THEN the traffic SHALL be encrypted between client and relay
- AND SHALL be encrypted between relay and server
- AND the API key SHALL still be validated server-side

### Non-Goals
- The system will NOT provide its own relay infrastructure
- The system will NOT handle relay authentication or access control
