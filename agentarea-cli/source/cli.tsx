#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import meow from 'meow';
import {handleCliCommand} from './cli-commands.js';
import App from './app.js';

const cli = meow(
	`
	Usage
	  $ agentarea [command]

	Commands
	  (no command)              Interactive TUI mode
	  login                     Sign in through the browser (OAuth + PKCE)
	  logout                    Clear the stored session
	  <resource> <verb> [args]  Run any resource action (agents, tasks,
	                            policies, access, mcp-servers, mcp-instances,
	                            providers, models, triggers, workspace,
	                            projects, skills, clients, ...)
	  <resource>                List a resource's verbs
	  agents list               Interactive agents view
	  tasks submit <agentId> <description>   Submit a task
	  tasks watch <agentId> <taskId>         Stream task events (SSE)
	  connect codex|claude      Connect a harness to its client bundle
	                            (creates the client if it does not exist)
	  mcp sync                  Same, addressing an existing client by id
	  api <operationId>         Escape hatch: call any operation by operationId
	  api --list                List all raw operationIds

	Options
	  --token         Bearer token (or use AGENTAREA_TOKEN env var)
	  --api-url       API server URL (default: http://localhost:8000)
	  --name          Client name to resolve or create (default: <host>-<harness>)
	  --alias         Local MCP server name in the harness (default: agentarea)
	  --mcp           MCP instance (name or id) to attach to the client
	  --no-login      Skip the harness's own OAuth step after wiring it up
	  --scope         project = write ./.codex/config.toml (codex) or the
	                  project scope (claude); user = the harness's own global
	                  config (default: project)
	  --client        Existing client id for 'mcp sync'
	  --target        Harness for 'mcp sync': codex or claude (default: codex)
	  --data          JSON request body (api / tasks submit)
	  --query         JSON query params (api)
	  --path          JSON path params (api)
	  --list          List operationIds (api)

	Examples
	  $ agentarea-cli --token=eyJ...
	  $ AGENTAREA_TOKEN=eyJ... agentarea-cli
	  $ agentarea-cli agents list --token=eyJ...
	  $ agentarea-cli api --list
	  $ agentarea-cli api listAgentsV1AgentsGet
	  $ agentarea-cli api getAgentV1AgentsAgentIdGet --path='{"agent_id":"abc"}'
`,
	{
		importMeta: import.meta,
		allowUnknownFlags: true,
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
			},
			alias: {
				type: 'string',
			},
			mcp: {
				type: 'string',
			},
			login: {
				type: 'boolean',
				default: true,
			},
			client: {
				type: 'string',
			},
			target: {
				type: 'string',
			},
			data: {
				type: 'string',
			},
			query: {
				type: 'string',
			},
			path: {
				type: 'string',
			},
			list: {
				type: 'boolean',
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
		alias: cli.flags.alias,
		mcp: cli.flags.mcp,
		login: cli.flags.login,
		client: cli.flags.client,
		target: cli.flags.target,
		data: cli.flags.data,
		query: cli.flags.query,
		path: cli.flags.path,
		list: cli.flags.list,
		args: cli.input,
		rawFlags: cli.flags as Record<string, unknown>,
	}).catch(error => {
		console.error('CLI command failed:', error);
		process.exit(1);
	});
} else {
	// No command provided - launch TUI mode
	render(<App token={token} apiUrl={cli.flags.apiUrl} />);
}
