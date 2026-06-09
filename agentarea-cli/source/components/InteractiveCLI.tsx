import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {useInput} from 'ink';
import {logger} from '../utils/logger.js';
import {apiClient} from '../services/apiClient.js';
import {tokenStorage} from '../utils/storage.js';
import {type AxiosError} from 'axios';

interface InteractiveCLIProps {
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

export function InteractiveCLI({userEmail, token}: InteractiveCLIProps) {
	const [input, setInput] = useState('');
	const [output, setOutput] = useState<CommandResult[]>([]);
	const [isExiting, setIsExiting] = useState(false);
	const [suggestions, setSuggestions] = useState<string[]>([]);

	// useInput will throw error if stdin is not TTY
	// Only call it when we're sure we have a real terminal
	if (!process.stdin.isTTY) {
		return (
			<Box flexDirection="column" paddingX={1} paddingY={1}>
				<Box
					marginBottom={1}
					borderStyle="round"
					borderColor="cyan"
					paddingX={1}
				>
					<Text bold color="cyan">
						🤖 AgentArea CLI {userEmail}
					</Text>
				</Box>
				<Text color="red">
					✗ Interactive mode requires a TTY. Use a proper terminal or provide
					commands via command-line flags.
				</Text>
			</Box>
		);
	}

	useInput((inputChar, key) => {
		if (isExiting) return;

		if (key.return) {
			// Execute command
			if (input.trim()) {
				executeCommandAndSetOutput(input.trim());
				setInput('');
				setSuggestions([]);
			}
		} else if (key.backspace || key.delete) {
			// Handle backspace
			const newInput = input.slice(0, -1);
			setInput(newInput);
			updateSuggestions(newInput);
		} else if (!key.ctrl && !key.meta && !key.shift && inputChar) {
			// Add character to input
			const newInput = input + inputChar;
			setInput(newInput);
			updateSuggestions(newInput);
		}
	});

	const updateSuggestions = (currentInput: string) => {
		if (currentInput.startsWith('/')) {
			const matching = COMMANDS.filter(cmd =>
				cmd.startsWith(currentInput.toLowerCase()),
			);
			setSuggestions(matching);
		} else {
			setSuggestions([]);
		}
	};

	const executeCommandAndSetOutput = async (command: string) => {
		const result = await executeCommand(command);
		setOutput(prev => [...prev, result]);

		if (command === '/exit') {
			setIsExiting(true);
			setTimeout(() => process.exit(0), 100);
		}
	};

	const executeCommand = async (command: string): Promise<CommandResult> => {
		try {
			switch (command) {
				case '/exit':
					return {type: 'info', message: 'Goodbye!'};

				case '/help': {
					return {
						type: 'info',
						message: 'Available commands:',
						data: (
							<Box flexDirection="column">
								<Text> /agents - List all agents</Text>
								<Text> /auth - Change authentication token</Text>
								<Text> /help - Show help</Text>
								<Text> /exit - Exit CLI</Text>
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
									<Text dimColor> {agent.description}</Text>
								)}
								{agent.status && <Text dimColor> Status: {agent.status}</Text>}
							</Box>
						))}
					</Box>
				),
			};
		} catch (error) {
			let message = 'Failed to load agents';

			if ((error as AxiosError)?.response?.status === 401) {
				message =
					'Authentication failed. Your token may have expired. Please use /auth to update.';
			} else if ((error as AxiosError)?.response?.status === 403) {
				message = 'Access denied. You do not have permission to list agents.';
			} else if ((error as AxiosError)?.code === 'ECONNREFUSED') {
				message = 'Could not connect to API server. Is it running?';
			} else if (error instanceof Error) {
				message = error.message;
			}

			return {type: 'error', message};
		}
	};

	const handleAuthCommand = async (): Promise<CommandResult> => {
		return {
			type: 'info',
			message:
				'Auth command - update token via /auth (not yet fully implemented)',
		};
	};

	return (
		<Box flexDirection="column" paddingX={1} paddingY={1}>
			{/* Header */}
			<Box marginBottom={1} borderStyle="round" borderColor="cyan" paddingX={1}>
				<Text bold color="cyan">
					🤖 AgentArea CLI {userEmail}
				</Text>
			</Box>

			{/* Output history */}
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
						<Text color="red">✗ {result.message}</Text>
					)}
					{result.type === 'info' && (
						<>
							<Text color="cyan">ℹ {result.message}</Text>
							{result.data && <Box marginLeft={2}>{result.data}</Box>}
						</>
					)}
				</Box>
			))}

			{/* Suggestions */}
			{suggestions.length > 0 && (
				<Box flexDirection="column" marginBottom={1}>
					{suggestions.map(suggestion => (
						<Text key={suggestion} color="gray" dimColor>
							{suggestion}
						</Text>
					))}
				</Box>
			)}

			{/* Input prompt */}
			{!isExiting && (
				<Box>
					<Text color="cyan">▶ </Text>
					<Text bold>agentarea</Text>
					<Text> {input}</Text>
					<Text color="gray">█</Text>
				</Box>
			)}
		</Box>
	);
}
