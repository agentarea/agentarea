import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {logger} from '../utils/logger.js';
import {apiClient} from '../services/apiClient.js';
import {tokenStorage} from '../utils/storage.js';
import readline from 'readline';

interface REPLProps {
	userEmail: string;
	token: string;
}

interface CommandResult {
	type: 'success' | 'error' | 'info';
	message: string;
	data?: React.ReactNode;
}

interface Agent {
	id: string;
	name: string;
	description?: string;
	status?: string;
	created_at?: string;
}

const COMMANDS = ['/agents', '/auth', '/help', '/exit'];

export function REPL({userEmail, token}: REPLProps) {
	const [input, setInput] = useState('');
	const [output, setOutput] = useState<CommandResult[]>([]);
	const [isRunning, setIsRunning] = useState(true);

	useEffect(() => {
		if (!isRunning) {
			return undefined;
		}

		const rl = readline.createInterface({
			input: process.stdin,
			output: process.stdout,
			terminal: false, // Use line-by-line mode
		});

		const lines: string[] = [];
		let currentLineIndex = 0;
		let isClosed = false;

		rl.on('line', async (line) => {
			lines.push(line);
		});

		rl.on('close', () => {
			isClosed = true;
			setIsRunning(false);
			process.exit(0);
		});

		// Process commands from stdin
		const processNextCommand = async () => {
			if (currentLineIndex >= lines.length && isClosed) {
				setIsRunning(false);
				process.exit(0);
				return;
			}

			if (currentLineIndex < lines.length) {
				const command = lines[currentLineIndex].trim();
				currentLineIndex++;

				if (command) {
					const result = await executeCommand(command);
					if (result.type === 'info' && result.message === 'Exiting...') {
						setIsRunning(false);
						process.exit(0);
					}
					setOutput((prev) => [...prev, result]);
				}

				setTimeout(processNextCommand, 100);
			} else {
				setTimeout(processNextCommand, 100);
			}
		};

		setTimeout(processNextCommand, 100);

		return (() => {
			if (!isClosed) {
				rl.close();
			}
		}) as any;
	}, [isRunning]);

	const executeCommand = async (command: string): Promise<CommandResult> => {
		try {
			switch (command) {
				case '/exit':
					return {type: 'info', message: 'Exiting...'};

				case '/help': {
					return {
						type: 'info',
						message: 'Available commands:',
						data: (
							<Box flexDirection="column">
								<Text>  /agents        - List all agents</Text>
								<Text>  /auth          - Change authentication token</Text>
								<Text>  /help          - Show help</Text>
								<Text>  /exit          - Exit CLI</Text>
							</Box>
						),
					};
				}

				case '/agents':
					return await handleAgentsCommand();

				case '/auth':
					return await handleAuthCommand();

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
	};

	const handleAgentsCommand = async (): Promise<CommandResult> => {
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

			return {
				type: 'success',
				message: `Found ${agents.length} agent(s)`,
				data: (
					<Box flexDirection="column">
						{agents.map((agent, index) => (
							<Box key={agent.id} flexDirection="column" marginBottom={0}>
								<Text>
									  {index + 1}. <Text bold>{agent.name}</Text>{' '}
									<Text dimColor>({agent.id.substring(0, 8)}...)</Text>
								</Text>
								{agent.description && (
									<Text dimColor>     {agent.description}</Text>
								)}
								{agent.status && (
									<Text dimColor>     Status: {agent.status}</Text>
								)}
							</Box>
						))}
					</Box>
				),
			};
		} catch (error) {
			const message = error instanceof Error ? error.message : 'Failed to load agents';
			return {type: 'error', message};
		}
	};

	const handleAuthCommand = async (): Promise<CommandResult> => {
		try {
			const rl = readline.createInterface({
				input: process.stdin,
				output: process.stdout,
			});

			const newToken = await new Promise<string>((resolve) => {
				rl.question('Enter new JWT token: ', (answer) => {
					rl.close();
					resolve(answer.trim());
				});
			});

			if (!newToken) {
				return {type: 'error', message: 'Token cannot be empty'};
			}

			const parts = newToken.split('.');
			if (parts.length !== 3) {
				return {
					type: 'error',
					message: 'Invalid token format. JWT must have 3 parts separated by dots.',
				};
			}

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
	};

	if (!isRunning && output.length === 0) {
		return null;
	}

	return (
		<Box flexDirection="column" padding={1}>
			<Box marginBottom={1} borderStyle="round" borderColor="cyan" paddingX={1} paddingY={0}>
				<Text bold color="cyan">
					🤖 AgentArea CLI {userEmail}
				</Text>
			</Box>

			{output.map((result, index) => (
				<Box key={index} flexDirection="column" marginBottom={1}>
					{result.type === 'success' && (
						<>
							<Text>
								<Text color="green">✓</Text> {result.message}
							</Text>
							{result.data && <Box marginLeft={2}>{result.data}</Box>}
						</>
					)}
					{result.type === 'error' && (
						<Text color="red">
							✗ {result.message}
						</Text>
					)}
					{result.type === 'info' && (
						<>
							<Text color="cyan">
								ℹ {result.message}
							</Text>
							{result.data && <Box marginLeft={2}>{result.data}</Box>}
						</>
					)}
				</Box>
			))}

			{isRunning && (
				<Box>
					<Text color="cyan">▶ </Text>
					<Text bold>agentarea</Text>
					<Text> {input}</Text>
				</Box>
			)}
		</Box>
	);
}
