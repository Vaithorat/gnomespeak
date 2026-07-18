# VoiceTalk Production Implementation Plan

## Goal and release boundary

Ship VoiceTalk as a dependable **trusted-LAN Windows companion** with a signed Android release, a packaged Windows server, reproducible builds, operational documentation, and tests covering the execution paths that can damage user data.

This is not safe for public networks today. The current protocol sends provider API keys over `ws://`; do not expose the server through port forwarding, public Wi-Fi, VPN sharing, or the Internet. A public-network edition requires authenticated `wss://`, device pairing, and removal of client-supplied provider keys before release.

## Current assessment

`PRODUCTION_PLAN.md` is a useful historical audit, but it is not a release plan: several listed P1 actions were only partially implemented. Treat this document as the source of truth for the next implementation cycle.

- The server test suite currently passes: `125 passed`.
- There is no client test suite, lint configuration, TypeScript quality gate, or CI workflow.
- The GUI server does not implement the request-ID streaming protocol used by `server.py`.
- The client still supports one pending request and silently drops commands/answers while disconnected.
- `Config` resolves a relative path before checking whether it is absolute, so the intended `%APPDATA%/VoiceTalk` default is unreachable.
- Android release builds are debug-signed, unminified, and include Flipper.
- Sensitive action coverage is incomplete: browser navigation and local media play are not confirmed, and SMTP input/error handling is unsafe.

## Release gates

Do not label a build production-ready until every gate below passes.

1. Server unit and integration tests pass on supported Windows and Python versions.
2. Client TypeScript check, lint, unit tests, and release Android build pass in CI.
3. A signed release APK connects to a packaged Windows server on a real LAN and completes voice, chat, streaming, clarification, file, browser, media, and email smoke tests.
4. Destructive commands remain denied if the phone disconnects or cannot answer a confirmation.
5. The README, install guide, recovery guide, and LAN security warning match the shipped behavior.
6. The release artifact has a version, changelog entry, checksum, rollback instructions, and known-issues list.

## Phase 1: Correct remaining correctness and safety defects

Complete this phase before changing UX, packaging, or provider architecture.

### 1.1 Make both server entries use one protocol [completed]

**Files:** `server/server.py`, `server/windows_gui.py`, `server/windows_app.py`

1. Choose `windows_gui.py` as the only supported desktop entry point, or extract a shared WebSocket server class used by both entry points. Do not maintain two independently evolving handlers.
2. Give the GUI handler the same request-ID behavior as `server.py`: extract incoming `request_id`, echo it on `result`, `stream_chunk`, `stream_result`, and `question`, and include it on answer routing.
3. Use `parse_stream` in both paths and forward chunks rather than only logging the final response.
4. Remove `windows_app.py` if it is not a supported entry point; otherwise make tray shutdown signal the actual running event loop and add a smoke test.

**Acceptance:** two clients can issue overlapping commands and answer clarification prompts without receiving one another's chunks, results, or questions.

### 1.2 Finish session and browser concurrency protection [completed]

**Files:** `server/intent_parser.py`, `server/server.py`, `server/handlers/browser_control.py`

1. Preserve server-issued session IDs by returning one in the first result and storing it client-side. Do not rely on a client-provided ID as the sole identity.
2. Replace the single global session lock with one lock per session, plus a short lock for the session-lock map and LRU mutation. Never hold a lock across a provider request or user confirmation.
3. Serialize every browser page operation, not only browser creation. Cover navigation, search, YouTube playback, and result extraction with the same lock.
4. Detect a disconnected browser, reset stale Playwright handles, and bound browser launch/navigation with deadlines.

**Acceptance:** concurrent requests on different sessions progress independently; same-session turns retain order; simultaneous browser commands do not race or create multiple Chromium instances.

### 1.3 Close the remaining safety gaps

**Files:** `server/safety.py`, `server/command_executor.py`, `server/handlers/file_ops.py`, `server/handlers/app_launcher.py`, `server/handlers/email_sender.py`

1. Enforce confirmation for first navigation to an untrusted domain and for media files outside configured safe roots. Keep the per-session domain allowlist server-side.
2. Resolve app targets before deciding whether `open_app` is dangerous; prompt for shell tools and executable targets, not only literal command names.
3. Confirm a move when the destination exists and show both resolved paths in every destructive prompt.
4. Reject `\r` and `\n` in email addresses and subjects; validate recipient syntax before constructing email headers.
5. Add SMTP connection timeout, port-465 `SMTP_SSL`, generic client errors, and server-side exception logging.
6. Change port handling to report an occupied port by default. Only stop a process after proving it is this VoiceTalk instance, preferably by retaining a PID/lock file rather than matching any `python` process.

**Acceptance:** no unchecked sensitive tool remains; malicious SMTP header input is rejected; an unrelated Python server on the configured port is never killed.

### 1.4 Correct configuration durability and recovery [completed]

**Files:** `server/config.py`, `server/windows_gui.py`, tests

1. Select the config path before resolving it: explicit absolute paths remain absolute; the default relative filename maps to `%APPDATA%/VoiceTalk/config.json`.
2. Preserve the previous `.master` as `.master.bak` before replacement. Never silently reset encrypted configuration after an unlock failure, because that makes existing credentials unrecoverable.
3. Show a clear GUI recovery choice: retry, restore backup, or explicitly reset configuration. The CLI must fail with equivalent actionable instructions.
4. Keep atomic config writes and add a process-level lock for concurrent GUI/server writes.

**Acceptance:** launch location cannot change configuration location; interrupted saves leave either the old or complete new config; corrupt/missing master-key recovery cannot silently destroy encrypted data.

### 1.5 Make advertised capabilities truthful [completed]

**Files:** `server/handlers/bluetooth_control.py`, `server/handlers/browser_control.py`, `server/handlers/media_player.py`, `README.md`

1. Remove Bluetooth connect/disconnect from tools until implemented, or implement and test them with a supported Windows API. Detect unavailable radio-control support and return a clear unsupported message.
2. Make YouTube playback report actual playback state; await the browser-side play attempt and use a documented fallback when autoplay is blocked.
3. Prefer cached app inventory for launches and keep synchronous fallback discovery off the event loop.

**Acceptance:** every UI/agent-advertised command either works on stock supported Windows or clearly reports unsupported before execution.

## Phase 2: Client reliability and accessibility

### 2.1 Make WebSocket delivery explicit [completed]

**Files:** `client/src/services/websocket.ts`, `client/src/types/index.ts`, `client/src/screens/HomeScreen.tsx`, `client/src/hooks/useConversationMode.ts`

1. Replace single callback fields with subscribe/unsubscribe listeners so screens and conversation mode cannot overwrite one another.
2. Replace single pending request refs with a `Map<request_id, message state>` and keep multiple in-flight commands separate.
3. Make `send` and `sendAnswer` return success/failure. Queue only commands that are safe to replay before socket open; never silently replay destructive actions or clarification answers without explicit UX.
4. Validate WebSocket URLs before connecting and stop reconnecting after an invalid local setting until it changes.
5. Include `request_id` on answer messages and match questions to their request.

**Acceptance:** disconnect during send produces visible recoverable state; overlapping streams update their own rows; malformed server messages cannot append undefined content or crash the app.

### 2.2 Stabilize speech lifecycle [completed]

**Files:** `RecordButton.tsx`, `useConversationMode.ts`, `HomeScreen.tsx`

1. Guarantee `Voice.destroy()` and handler cleanup on unmount, disabled state, mode switch, backgrounding, and error paths.
2. Serialize start/stop transitions with explicit in-flight guards; cover rapid taps, re-recording, and toggling modes while recording.
3. Re-check microphone permission when the app returns active.
4. Display partial transcription in conversation mode and ensure silence/finalization timers are cancelled before state changes.

**Acceptance:** rapid record actions, background/foreground, and mode changes never leave the recognizer running or strand the UI in processing/waiting.

### 2.3 Apply baseline mobile usability [completed]

1. Add accessible labels, roles, busy/live state, and 44pt touch targets to every interactive control.
2. Add onboarding for missing provider configuration, retry for offline state, safe new-chat confirmation/undo, and non-blocking save feedback.
3. Cap visible command history and throttle stream updates/scrolling to avoid rendering once per token.

**Acceptance:** TalkBack identifies all controls; the critical screens are usable at font scaling; a 500-chunk response does not visibly stall the device.

## Phase 3: Test and quality system

### 3.1 Server tests

**Files:** `server/tests/`, new integration test helpers as needed

1. Add provider-mocked tests for streaming delta accumulation, tool calls, timeouts, content filtering, iteration limits, partial output, tool-result truncation, and system-prompt persistence.
2. Add async WebSocket integration tests for two-client request IDs, confirmation routing, disconnect cancellation, and blocked-handler responsiveness.
3. Add tests for real safety branches: path traversal, symlink escapes, confirmation denial, executable launch, SMTP injection, safe port handling, and config recovery/atomic write.
4. Add tests for browser locking with a fake page/Playwright fixture; do not require installed Chromium for unit tests.

### 3.2 Client tests and static checks

**Files:** `client/package.json`, ESLint config, test setup, CI workflow

1. Add a working ESLint configuration and `typecheck` script using `tsc --noEmit`.
2. Add Jest/React Native Testing Library only for the state machines that need it: WebSocket message routing, queued/failed send UI, request maps, and speech cleanup.
3. Correct existing TypeScript errors before enforcing the gate.

### 3.3 CI

**Files:** `.github/workflows/ci.yml`, dependency configuration

1. Run server tests on Windows with the supported Python version.
2. Run client install, typecheck, lint, and tests on a pinned Node version.
3. Build an unsigned release APK on protected release branches; signing stays in a separate secret-backed release workflow.
4. Add dependency scanning and pinned dependency policy. Split runtime and development Python requirements and pin compatible major/minor versions.

**Acceptance:** a pull request cannot merge when server tests, client typecheck/lint/tests, or Android release compilation fail.

## Phase 4: Release engineering and operations

### 4.1 Android release [completed]

**Files:** `client/android/app/build.gradle`, `MainApplication.kt`, release documentation

1. Move release signing to environment/CI secrets and fail release builds when signing values are absent. Never use the debug key for release artifacts.
2. Enable and validate R8/ProGuard for release; add necessary keep rules from a tested release build.
3. Move Flipper to debug-only dependencies and guard initialization with `BuildConfig.DEBUG`.
4. Produce an AAB for distribution and an APK only for documented sideloading. Increment versionCode/versionName through the release process.

### 4.2 Windows packaging and lifecycle [completed]

1. Choose one packaged entry point and validate its PyInstaller spec from a clean Windows machine.
2. Include or bootstrap Playwright Chromium deterministically; never claim it is bundled until the artifact test proves it.
3. Add Windows Defender/SmartScreen and firewall guidance. Use a user-level startup/service installation option only after clean shutdown and upgrade behavior are tested.
4. Write rotating local logs with timestamps, request IDs, and redacted errors. Add a GUI log export action.

### 4.3 Runbooks and supportability [completed]

1. Document supported OS/Python/Node/Android versions, setup, configuration location, recovery, firewall, updates, backup, and rollback.
2. Add explicit LAN-risk language: traffic is unencrypted and client API keys traverse the LAN. State that public exposure is unsupported.
3. Add a minimal diagnostics bundle: app/server version, config schema version, sanitized logs, dependency versions, and connectivity test output.

**Acceptance:** a new machine can install, connect, update, and recover using only the published documentation.

## Phase 5: Public-network edition (separate project)

Do not fold this into the LAN release. Begin only if remote access is a product requirement.

1. Replace cleartext WebSocket with TLS using a managed certificate or local pairing certificate.
2. Add device pairing, per-device authentication, command authorization, rate limits, and replay protection.
3. Stop transmitting raw provider API keys from Android; store server-side credentials with OS-backed protection or use a delegated token model.
4. Restrict browser/file/app permissions per paired device and add audit logs.
5. Threat-model and penetration-test the protocol before public beta.

## Implementation sequence

1. Phase 1.1 through 1.4, with tests added alongside every fix.
2. Phase 3.1 before Phase 2 so client/server protocol changes have regression coverage.
3. Phase 2.1 and 2.2, then Phase 3.2/3.3.
4. Phase 4 only after CI is green and a real-LAN integration checklist is repeatable.
5. Tag a release only after every release gate passes.

## Definition of done

The product is production-ready for its declared trusted-LAN scope when all release gates pass, no known destructive path bypasses confirmation, both client and GUI server use the same verified request protocol, releases are signed/reproducible, and support documentation accurately states the security boundary.
