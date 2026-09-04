# agentarea-cli

Interactive CLI for Agent Management using Ink. Authenticate, discover agents, submit tasks, and monitor real-time execution output via Server-Sent Events (SSE).

## Features

- 🔐 **Authentication**: Secure login with token persistence in OS keychain
- 👥 **Agent Discovery**: List and filter available agents by status and capabilities
- 📋 **Task Submission**: Submit tasks with configurable parameters to agents
- 🔄 **Real-time Streaming**: Monitor task execution with live output streaming via SSE
- ⌨️ **Interactive CLI**: Responsive Ink-based interface with keyboard navigation
- 🛡️ **Error Handling**: Graceful error handling with user-friendly messages

## Installation

```bash
# Install globally
npm install --global agentarea-cli

# Or run locally
npm install
npm run build
npm start
```

## Quick Start

```bash
$ agentarea-cli

# First time: You'll be prompted to login
[?] Email: your.email@example.com
[?] Password: ••••••••

# Then: Select an agent and submit a task
[?] Select agent: Agent-1 (online)
[?] Task title: Run Analysis
[?] Parameters: {"dataset": "data.csv"}

# Finally: Watch real-time output
Running analysis...
Processing: 50%
✓ Analysis complete!
```

## Usage

### Login

```bash
$ agentarea-cli
# Prompts for email and password
# Token stored securely in OS keychain
```

### List Agents

After login, select "List Agents" to:

- View all available agents
- See agent status (online/offline/busy)
- View agent capabilities
- Filter by status or search by name

### Submit Task

After selecting an agent:

1. Enter task title
2. Provide task description (optional)
3. Configure parameters
4. Confirm submission

### Monitor Execution

Once task is submitted:

- Real-time stdout/stderr output displayed
- Progress indicators updated
- Status changes shown
- Completion or failure reported

## Configuration

Create a `.env` file based on `.env.example`:

```bash
# API Configuration
API_URL=http://localhost:3000
API_TIMEOUT=30000
MAX_RETRIES=3

# Logging
LOG_LEVEL=info

# UI
THEME=auto
```

## Development

```bash
# Install dependencies
npm install

# Watch mode
npm run dev

# Build
npm run build

# Test
npm test

# Lint and format
npm run test
```

## Architecture

```
source/
├── cli.tsx              # CLI entry point with meow parser
├── app.tsx              # Main application component
├── components/          # Ink UI components
├── services/            # API clients and business logic
├── hooks/               # React hooks for state management
├── context/             # React context providers
├── utils/               # Utility functions
└── types/               # TypeScript type definitions
```

## API Requirements

The CLI expects the following API endpoints:

### Authentication

- `POST /auth/login` - Login with credentials
- `POST /auth/refresh` - Refresh access token
- `POST /auth/logout` - Logout and invalidate token

### Agents

- `GET /agents` - List available agents
- `GET /agents/{agentId}` - Get agent details
- `GET /agents/{agentId}/capabilities` - Get agent capabilities

### Tasks

- `POST /tasks` - Submit a new task
- `GET /tasks` - List tasks
- `GET /tasks/{taskId}` - Get task details
- `DELETE /tasks/{taskId}` - Cancel a task
- `GET /sse/tasks/{taskId}` - SSE stream for task output

## Authentication

Credentials are stored securely:

- **macOS**: Keychain
- **Linux**: Secret Service (requires `libsecret`)
- **Windows**: Credential Manager

Token is automatically:

- Retrieved on app startup
- Refreshed before expiration
- Cleared on logout

## Keyboard Shortcuts

| Key    | Action           |
| ------ | ---------------- |
| ↑/↓    | Navigate options |
| Enter  | Select/Submit    |
| q      | Back to menu     |
| Escape | Cancel           |
| Ctrl+C | Exit CLI         |

## Testing

```bash
# Run all tests
npm test

# Watch mode
npm run test -- --watch

# With coverage
npm run test -- --coverage
```

## Troubleshooting

### "Cannot find module"

```bash
npm install
npm run build
```

### Keychain errors

```bash
# Linux: Install libsecret
sudo apt-get install libsecret-1-dev

# Then rebuild
npm rebuild
```

### API connection errors

1. Check API_URL in .env
2. Verify API server is running
3. Check network connectivity
4. Enable debug logging: `LOG_LEVEL=debug`

## License

Licensed under the Apache License 2.0 — see [LICENSE.md](../LICENSE.md) for details.

## See Also

- [Feature Specification](../specs/001-ink-cli/spec.md)
- [Implementation Plan](../specs/001-ink-cli/plan.md)
- [API Contracts](../specs/001-ink-cli/contracts/)
- [Data Model](../specs/001-ink-cli/data-model.md)
