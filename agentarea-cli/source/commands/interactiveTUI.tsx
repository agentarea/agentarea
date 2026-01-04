import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {logger} from '../utils/logger.js';
import {apiClient} from '../services/apiClient.js';
import {tokenStorage} from '../utils/storage.js';
import {
	formatPrompt,
	formatSuccess,
	formatError,
	formatInfo,
	formatHeader,
	formatHighlight,
	formatDim,
	showCursor,
	hideCursor,
} from '../utils/formatting.js';
import readline from 'readline';

interface InteractiveTUIProps {
	userEmail: string;
	token: string;
}

interface Agent {
	id: string;
	name: string;
	description?: string;
	status?: string;
	created_at?: string;
}

interface CommandResult {
	type: 'success' | 'error' | 'info';
	message: string;
	data?: any;
}

export function InteractiveTUI({userEmail, token}: InteractiveTUIProps) {
	useEffect(() => {
		const startRepl = async () => {
			const rl = readline.createInterface({
				input: process.stdin,
				output: process.stdout,
			});

			let isClosed = false;

			rl.on('close', () => {
				isClosed = true;
			});

			try {
				// Show welcome message with user info
				console.log(formatHeader(`🤖 AgentArea CLI ${formatHighlight(userEmail)}`));

				// Available commands for autocomplete
				const availableCommands = ['/agents', '/auth', '/help', '/exit'];

				// REPL loop
				let shouldExit = false;
				while (!shouldExit && !isClosed) {
					const command = await new Promise<string>((resolve) => {
						if (isClosed) {
							resolve('/exit');
						} else {
							let currentInput = '';
							let suggestions: string[] = [];

							// Handle line event
							const handleLine = (input: string) => {
								rl.removeListener('line', handleLine);
								resolve(input.trim());
							};

							// Show prompt
							process.stdout.write(formatPrompt('agentarea'));

							// Listen for input
							rl.on('line', handleLine);

							// Handle keypress for autocomplete
							if (process.stdin.isTTY) {
								const originalOnData = process.stdin.listeners('data')[0];
								const handleKeypress = (key: any) => {
									// Don't process if already resolved
									if (!rl.listeners('line').includes(handleLine)) return;

									// For terminal input, just let readline handle it
									if (originalOnData) {
										originalOnData(key);
									}
								};

								// Just use readline as-is for simplicity
							}
						}
					});

					if (!command) {
						continue;
					}

					// Process command
					const result = await processCommand(command, token, rl, availableCommands);

					// Display result (no extra blank lines)
					if (result.type === 'success') {
						console.log(formatSuccess(result.message));
						if (result.data) {
							console.log(result.data);
						}
					} else if (result.type === 'error') {
						console.log(formatError(result.message));
					} else {
						console.log(formatInfo(result.message));
					}

					// Check if we should exit
					if (command === '/exit') {
						shouldExit = true;
						console.log(formatInfo('Goodbye!'));
						if (!isClosed) {
							rl.close();
						}
						process.exit(0);
					}
				}
			} catch (error) {
				logger.error('REPL error:', error);
				if (!isClosed) {
					rl.close();
				}
				process.exit(1);
			}
		};

		startRepl();
	}, [userEmail, token]);

	// Component returns null since rendering happens during execution
	// All UI is managed through readline + direct console output to maintain interactive input
	return null;
}

async function processCommand(
	command: string,
	token: string,
	rl: readline.Interface,
	availableCommands?: string[],
): Promise<CommandResult> {
	try {
		switch (command) {
			case '/exit':
				return {type: 'info', message: 'Exiting...'};

			case '/help': {
				const helpText = `
  /agents        - List all agents
  /auth          - Change authentication token
  /help          - Show help
  /exit          - Exit CLI
`;
				return {
					type: 'info',
					message: 'Available commands:',
					data: helpText,
				};
			}

			case '/agents':
				return await handleAgentsCommand();

			case '/auth':
				return await handleAuthCommand(rl);

			default:
				return {
					type: 'error',
					message: `Unknown command: ${command}. Type /help for available commands.`,
				};
		}
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		return {type: 'error', message};
	}
}

async function handleAgentsCommand(): Promise<CommandResult> {
	try {
		const response = await apiClient.getClient().get('/v1/agents', {
			headers: {
				'X-Workspace-ID': 'default',
			},
		});

		const agents: Agent[] = response.data.data || response.data || [];

		if (agents.length === 0) {
			return {type: 'info', message: 'No agents found'};
		}

		const agentsList = agents
			.map((agent, index) => {
				let output = `  ${index + 1}. ${formatHighlight(agent.name)} ${formatDim(`(${agent.id.substring(0, 8)}...)`)}`;
				if (agent.description) {
					output += `\n     ${formatDim(agent.description)}`;
				}
				if (agent.status) {
					output += `\n     ${formatDim(`Status: ${agent.status}`)}`;
				}
				return output;
			})
			.join('\n\n');

		return {
			type: 'success',
			message: `Found ${agents.length} agent(s)`,
			data: agentsList,
		};
	} catch (error) {
		const message = error instanceof Error ? error.message : 'Failed to load agents';
		return {type: 'error', message};
	}
}

async function handleAuthCommand(rl: readline.Interface): Promise<CommandResult> {
	try {
		const newToken = await new Promise<string>((resolve) => {
			rl.question('Enter new JWT token: ', (answer) => {
				resolve(answer.trim());
			});
		});

		if (!newToken) {
			return {type: 'error', message: 'Token cannot be empty'};
		}

		// Validate token format
		const parts = newToken.split('.');
		if (parts.length !== 3) {
			return {
				type: 'error',
				message: 'Invalid token format. JWT must have 3 parts separated by dots.',
			};
		}

		// Save new token
		const authToken = {
			accessToken: newToken,
			tokenType: 'Bearer',
			expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000),
		};

		await tokenStorage.saveToken(authToken);
		apiClient.setToken(authToken);

		return {type: 'success', message: 'Token updated successfully'};
	} catch (error) {
		const message = error instanceof Error ? error.message : 'Failed to update token';
		return {type: 'error', message};
	}
}
