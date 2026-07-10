# Intent Parsing

## Purpose
Convert voice commands into executable actions using an AI agent loop. The agent reasons about intent, calls tools (handlers), processes results, and asks the user for clarification when needed.

## Requirements

### Requirement: AI Agent Loop
The system SHALL use OpenAI function-calling to determine actions.
#### Scenario: Agent Flow
- GIVEN the server receives a voice transcript
- WHEN the agent processes it
- THEN the system SHALL construct a messages array with system prompt + user input
- AND SHALL call OpenAI Chat Completions with tool definitions
- AND SHALL check if the response contains tool_calls or text

#### Scenario: Tool Execution
- GIVEN the LLM response contains tool_calls
- WHEN each tool call has a name and arguments
- THEN the system SHALL execute the corresponding handler
- AND SHALL append the result to the messages array
- AND SHALL loop back to call OpenAI again with the updated context

#### Scenario: Final Response
- GIVEN the LLM response contains text (no tool_calls)
- WHEN the agent loop reaches this state
- THEN the system SHALL return the text as the final result to the client

### Requirement: Tool Definitions
The system SHALL define each handler as an OpenAI function-calling tool.
#### Scenario: Tool Schema
- GIVEN a handler exists
- WHEN the system starts
- THEN each handler SHALL have a JSON tool definition with name, description, and JSON Schema parameters

#### Scenario: Tool Inventory
The system SHALL provide these tools to the agent:
- `open_app` — Launch app (params: name)
- `navigate` — Open file/folder (params: path)
- `list_dir` — List directory (params: path)
- `create_file` — Create file (params: path, content?)
- `send_email` — Send email (params: to, subject, body)
- `control_bluetooth` — BT radio/device control (params: action, device?)
- `play_media` — Search and play media (params: query)
- `open_url` — Open URL in browser (params: url)
- `search_web` — Web search (params: query)
- `get_system_info` — Get PC capabilities (no params)
- `ask_user` — Ask user a question (params: question, options?)

### Requirement: Clarification via ask_user
The system SHALL ask the user on the phone when it needs more information.
#### Scenario: Agent Asks
- GIVEN the agent encounters ambiguity
- WHEN it calls the `ask_user` tool
- THEN the system SHALL send a `question` message to the client via WebSocket
- AND SHALL pause the agent loop
- AND SHALL resume when an `answer` message is received
- AND SHALL inject the answer into the LLM context

#### Scenario: Resume After Answer
- GIVEN the user answered a question
- WHEN the answer arrives via WebSocket
- THEN the system SHALL append the user's answer as a tool result
- AND SHALL continue the agent loop

### Requirement: System Prompt Design
The system SHALL define the agent's role and behavior.
#### Scenario: Agent Identity
- GIVEN the agent starts processing
- WHEN the system prompt is constructed
- THEN it SHALL define the agent as a "Windows PC assistant controlled by voice from a phone"
- AND SHALL instruct it to use tools to accomplish tasks
- AND SHALL instruct it to ask the user if unsure
- AND SHALL instruct it to chain multiple tool calls when needed

### Requirement: Multi-Step Reasoning
The system SHALL handle commands requiring multiple steps.
#### Scenario: Chained Actions
- GIVEN the user says "turn on bluetooth and play despacito"
- WHEN the agent processes this
- THEN it SHALL call control_bluetooth then play_media
- AND SHALL return a combined result

### Requirement: PC State Context
The system SHALL provide PC state info to the agent.
#### Scenario: System Info Tool
- GIVEN the agent needs to know PC capabilities
- WHEN it calls get_system_info
- THEN it SHALL receive OS version, Bluetooth hardware status, installed apps, audio devices

### Requirement: Rule-Based Fallback
The system SHALL fall back to regex parsing when OpenAI is unavailable.
#### Scenario: Unavailability
- GIVEN the API key is not configured or the call fails
- WHEN the server needs to parse a command
- THEN the system SHALL use regex pattern matching
- AND SHALL NOT crash

#### Scenario: Fallback Patterns
- GIVEN the spoken text starts with "open ", "launch ", "start ", "run "
- WHEN the fallback processes it
- THEN it SHALL return open_app with the rest as name

- GIVEN the spoken text matches `list <path>`, `show <path>`, `what's in <path>`
- WHEN the fallback processes it
- THEN it SHALL return list_dir

- GIVEN the spoken text starts with "go to ", "navigate to ", "open folder ", "open file "
- WHEN the fallback processes it
- THEN it SHALL return navigate

- GIVEN no pattern matches the spoken text
- WHEN the fallback processes it
- THEN it SHALL treat the entire text as an app name

### Requirement: API Key Validation (Server)
The server SHALL validate the API key format before using it.
#### Scenario: Key Format Check
- GIVEN the client sends an API key with a command
- WHEN the server receives the message
- THEN the system SHALL check that the key matches `^sk-[A-Za-z0-9]{20,}$`
- AND SHALL reject with an error if the format is invalid
