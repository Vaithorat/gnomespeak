# Command Executor

## Purpose
Route tool calls from the AI agent to the appropriate handler and return results. Each handler is a named tool the agent can invoke.

## Requirements

### Requirement: Dynamic Tool Dispatch (Server)
The system SHALL dispatch tool calls from the agent to the correct handler.
#### Scenario: Execute Named Tool
- GIVEN the agent returns a tool_call with name and arguments
- WHEN the system processes the tool call
- THEN it SHALL look up the handler by tool name
- AND SHALL parse and pass the arguments
- AND SHALL return the handler's result as a JSON string

#### Scenario: Tool Dispatch Table
- GIVEN a tool call is received
- WHEN the executor routes it
- THEN it SHALL dispatch as follows:
  - `navigate` → `FileOps.navigate(path)`
  - `list_dir` → `FileOps.list_dir(path)`
  - `open_app` → `AppLauncher.launch(name)`
  - `create_file` → `FileOps.create_file(path, content)`
  - `create_folder` → `FileOps.create_folder(path)`
  - `delete` → `FileOps.delete(path)`
  - `copy` → `FileOps.copy(source, destination)`
  - `move` → `FileOps.move(source, destination)`
  - `send_email` → `EmailSender.send(to, subject, body)`
  - `control_bluetooth` → `BluetoothControl.execute(action, device?)`
  - `play_media` → `MediaPlayer.play(query)`
  - `open_url` → browser launch with URL
  - `search_web` → browser launch with search URL
  - `get_system_info` → system capability report
  - `ask_user` → question/answer protocol (special handler)

### Requirement: Tool Registration (Server)
The system SHALL register handlers as discoverable tools.
#### Scenario: Registration
- GIVEN a new handler is added
- WHEN the system initializes
- THEN each handler SHALL be registered with a unique tool name
- AND SHALL be available to the agent via the tool definitions array

### Requirement: ask_user Handler (Server)
The system SHALL support the agent asking the user for clarification.
#### Scenario: Send Question
- GIVEN the agent calls `ask_user` with a question and optional options
- WHEN the handler executes
- THEN the system SHALL serialize the agent loop state
- AND SHALL send a `question` message to the client
- AND SHALL wait for the answer (async, correlation ID)
- AND SHALL return the user's answer as the tool result

### Requirement: Error Handling (Server)
The system SHALL catch and return errors without crashing.
#### Scenario: Handler Error
- GIVEN a handler raises an exception
- WHEN the tool executes
- THEN the system SHALL catch the exception
- AND SHALL return `{"error": "message"}` as the tool result
- AND SHALL NOT terminate the agent loop

### Requirement: Result Format (Server)
The system SHALL return results in a consistent format.
#### Scenario: Success Result
- GIVEN a command executed without errors
- WHEN the handler returns
- THEN the result SHALL be `{"success": true, "message": "<description>"}`

#### Scenario: Failure Result
- GIVEN a command encountered an error
- WHEN the handler returns
- THEN the result SHALL be `{"success": false, "message": "<error description>"}`
