# Intent Parsing

## Purpose
Convert voice and text commands into executable actions using an AI agent loop with multi-provider support. The agent reasons about intent, chains tool calls, processes results, and asks the user for clarification when needed. The system supports OpenAI, Gemini, OpenRouter, and OpenCode providers with automatic fallback.

## Requirements

### Requirement: Multi-Provider Agent Loop
The system SHALL support multiple AI providers for intent parsing.
#### Scenario: OpenAI Agent Flow
- GIVEN the user has configured an OpenAI API key
- WHEN the server receives a command
- THEN the system SHALL use the OpenAI Chat Completions API with native function calling
- AND SHALL construct a messages array with system prompt + user input + tool definitions
- AND SHALL loop up to 10 iterations, feeding tool results back to the LLM

#### Scenario: Gemini Agent Flow
- GIVEN the user has configured a Gemini API key
- WHEN the server receives a command
- THEN the system SHALL use the Gemini API with native function calling
- AND SHALL pass tool definitions as the `tools` parameter
- AND SHALL implement an agent loop that feeds tool results back
- AND SHALL support multi-step tool chaining

#### Scenario: OpenRouter Agent Flow
- GIVEN the user has configured an OpenRouter API key
- WHEN the server receives a command
- THEN the system SHALL use the OpenAI-compatible API via OpenRouter
- AND SHALL use the model specified in `OPENROUTER_MODEL`

#### Scenario: OpenCode Agent Flow
- GIVEN the user has configured an OpenCode API key
- WHEN the server receives a command
- THEN the system SHALL use the OpenAI-compatible API via OpenCode
- AND SHALL use the model specified in `OPENGODE_MODEL`

#### Scenario: Provider Priority
- GIVEN multiple API keys are configured
- WHEN the system initializes
- THEN it SHALL use the first available provider in order: OpenAI, OpenCode, Gemini, OpenRouter
- AND the user SHALL be able to override via the client settings

### Requirement: Tool Execution Loop
The system SHALL execute tool calls and feed results back to the LLM.
#### Scenario: Tool Execution
- GIVEN the LLM response contains tool_calls
- WHEN each tool call has a name and arguments
- THEN the system SHALL execute the corresponding handler
- AND SHALL append the result to the messages array as a tool message
- AND SHALL loop back to call the LLM again with the updated context

#### Scenario: Final Response
- GIVEN the LLM response contains text (no tool_calls)
- WHEN the agent loop reaches this state
- THEN the system SHALL return the text as the final result to the client
- AND SHALL store the conversation in the session history

#### Scenario: Maximum Iterations
- GIVEN the agent loop has run 10 iterations
- WHEN the LLM still returns tool calls
- THEN the system SHALL return an error message
- AND SHALL store the partial progress in the session

#### Scenario: Malformed Tool Arguments
- GIVEN the LLM returns a tool call with invalid JSON arguments
- WHEN the system attempts to parse the arguments
- THEN the system SHALL catch the JSONDecodeError
- AND SHALL use an empty arguments dict `{}`
- AND SHALL NOT crash the agent loop

### Requirement: Tool Definitions
The system SHALL define each handler as an AI function-calling tool.
#### Scenario: Tool Schema
- GIVEN a handler exists
- WHEN the system starts
- THEN each handler SHALL have a JSON tool definition with name, description, and JSON Schema parameters

#### Scenario: Tool Inventory
The system SHALL provide these tools to the agent:
- `browser_navigate` — Open a URL in the default browser (params: url)
- `browser_search` — Web search via browser (params: query, engine?)
- `yt_play` — Search YouTube and open first video with autoplay + auto-play (params: query)
- `yt_search` — Open YouTube search results for browsing (params: query)
- `yt_results` — Fetch top 10 YouTube results (params: query)
- `open_app` — Launch a Windows app (params: name)
- `navigate` — Open file/folder in Explorer (params: path)
- `list_dir` — List directory contents (params: path?)
- `create_file` — Create a file (params: path, content?)
- `create_folder` — Create a directory (params: path)
- `delete` — Delete file or folder (params: path)
- `copy` — Copy file/folder (params: source, destination)
- `move` — Move/rename file/folder (params: source, destination)
- `send_email` — Send email via SMTP (params: to, subject, body)
- `control_bluetooth` — Bluetooth on/off/scan/connect (params: action, device?)
- `play_media` — Search and play local media (params: query)
- `volume_up` — Increase system volume (no params)
- `volume_down` — Decrease system volume (no params)
- `volume_mute` — Toggle mute (no params)
- `set_volume` — Set volume to level (params: level)
- `media_control` — Keyboard simulation for media/browser (params: action)
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

### Requirement: Session Management
The system SHALL maintain conversation context across multiple messages.
#### Scenario: Session Creation
- GIVEN a new session_id is received
- WHEN the agent processes the first message
- THEN the system SHALL create a new session with system prompt + user message

#### Scenario: Session Continuation
- GIVEN an existing session_id is received
- WHEN the agent processes a new message
- THEN the system SHALL load the full message history
- AND SHALL append the new user message
- AND SHALL send the complete history to the LLM

#### Scenario: Session Limits
- GIVEN sessions accumulate over time
- WHEN the session count exceeds 50
- THEN the system SHALL evict the oldest session
- AND each session SHALL be limited to 100 messages

#### Scenario: Session Reset
- GIVEN the user starts a new chat
- WHEN a new session_id is generated
- THEN the system SHALL start with a fresh conversation history

### Requirement: System Prompt Design
The system SHALL define the agent's role, behavior, and autonomy rules.
#### Scenario: Agent Identity
- GIVEN the agent starts processing
- WHEN the system prompt is constructed
- THEN it SHALL define the agent as a "Windows PC assistant controlled by voice from a phone"
- AND SHALL instruct it to use tools to accomplish tasks
- AND SHALL instruct it to chain multiple tool calls when needed

#### Scenario: Autonomy Rules
- GIVEN the system prompt is constructed
- WHEN the agent receives it
- THEN it SHALL include these mandatory rules:
  - "ALWAYS respond in English, regardless of what language the user speaks"
  - "YOU control the PC completely. NEVER tell the user to click, tap, or do something themselves"
  - "After opening a YouTube video, you MUST call media_control(action='play_pause') to start playback"
  - "If a tool fails, analyze the error and try an alternative approach before giving up"
  - "Break complex tasks into steps. Execute each step, verify the result, then proceed"

### Requirement: Rule-Based Fallback
The system SHALL fall back to regex parsing when no AI provider is available.
#### Scenario: No Provider Configured
- GIVEN no API key is configured or all providers fail
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
- THEN it SHALL return a conversational response instead of trying to open a random app name

### Requirement: Error Recovery Protocol
The system SHALL recover from tool failures autonomously.
#### Scenario: Tool Returns Error
- GIVEN a tool call returns `{"success": false, "message": "..."}`
- WHEN the LLM receives the error result
- THEN the LLM SHALL analyze the error message
- AND SHALL try an alternative approach (e.g., different tool, different query)
- AND SHALL NOT give up after a single failure

#### Scenario: Provider API Failure
- GIVEN the primary AI provider returns an error
- WHEN the system detects the failure
- THEN the system SHALL try the next available provider
- AND SHALL fall back to rule-based parsing if all providers fail

### Non-Goals
- The system will NOT implement streaming responses
- The system will NOT support image or voice input beyond text transcripts
- The system will NOT implement custom model fine-tuning
- The system will NOT cache LLM responses
