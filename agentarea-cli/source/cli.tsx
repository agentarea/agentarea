#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import meow from 'meow';
import {handleCliCommand} from './cli-commands.js';
import App from './app.js';

const cli = meow(
	`
	Usage
	  $ agentarea-cli [command]

	Commands
	  (no command)    Interactive TUI mode
	  agents list     List all agents
	  connect codex   Connect Codex to Agentarea MCP
	  connect claude  Connect Claude Code to Agentarea MCP
	  mcp sync        Connect a harness to a client-scoped MCP bundle

	Options
	  --token         JWT authentication token (or use AGENTAREA_TOKEN env var)
	  --api-url       API server URL (default: http://localhost:8000)
	  --name          Local Agentarea target name (default: default)
	  --scope         Connection scope: project or user (default: project)
	  --client        Client (agent-proxy) id for 'mcp sync'
	  --target        Harness for 'mcp sync': codex or claude (default: claude)

	Examples
	  $ agentarea-cli --token=eyJ...
	  $ AGENTAREA_TOKEN=eyJ... agentarea-cli
	  $ agentarea-cli agents list --token=eyJ...
`,
	{
		importMeta: import.meta,
		flags: {
			token: {
				type: 'string',
			},
			apiUrl: {
				type: 'string',
				default: 'http://localhost:8000',
			},
			scope: {
				type: 'string',
				default: 'project',
			},
			name: {
				type: 'string',
				default: 'default',
			},
			client: {
				type: 'string',
			},
			target: {
				type: 'string',
			},
		},
	},
);

const token = cli.flags.token || process.env['AGENTAREA_TOKEN'];
const command = cli.input[0];
const subcommand = cli.input[1];

// If a command is provided, handle it directly
if (command) {
	handleCliCommand(command, subcommand, {
		token,
		apiUrl: cli.flags.apiUrl,
		scope: cli.flags.scope,
		name: cli.flags.name,
		client: cli.flags.client,
		target: cli.flags.target,
	}).catch(error => {
		console.error('CLI command failed:', error);
		process.exit(1);
	});
} else {
	// No command provided - launch TUI mode
	render(<App token={token} apiUrl={cli.flags.apiUrl} />);
}
