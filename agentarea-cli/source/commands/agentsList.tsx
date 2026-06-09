import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {apiClient} from '../services/apiClient.js';
import {logger} from '../utils/logger.js';
import {type AxiosError} from 'axios';

interface Agent {
	id: string;
	name: string;
	description?: string;
	status?: string;
	created_at?: string;
}

export function AgentsList() {
	const [agents, setAgents] = useState<Agent[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const fetchAgents = async () => {
			try {
				setLoading(true);
				const response = await apiClient.getClient().get('/v1/agents', {
					headers: {
						'X-Workspace-ID': 'default',
					},
				});
				setAgents(response.data.data || response.data || []);
				logger.info(
					`Loaded ${(response.data.data || response.data).length} agents`,
				);
			} catch (err) {
				let message = 'Failed to load agents';
				const axiosError = err as AxiosError;

				if (axiosError?.response?.status === 401) {
					message =
						'Authentication failed. Your token may have expired. Please provide a new token.';
				} else if (axiosError?.response?.status === 403) {
					message = 'Access denied. You do not have permission to list agents.';
				} else if (axiosError?.code === 'ECONNREFUSED') {
					message =
						'Could not connect to API server at http://localhost:8000. Is it running?';
				} else if (axiosError?.code === 'ETIMEDOUT') {
					message =
						'API request timed out. The server may be slow or unreachable.';
				} else if (axiosError?.code === 'EPERM') {
					message =
						'Could not connect to API server. Check that it is running on http://localhost:8000';
				} else if (err instanceof Error) {
					message = err.message;
				}

				setError(message);
				logger.warn('Failed to load agents');
			} finally {
				setLoading(false);
			}
		};

		fetchAgents();
	}, []);

	if (loading) {
		return (
			<Box flexDirection="column" padding={1}>
				<Text color="yellow">⏳ Loading agents...</Text>
			</Box>
		);
	}

	if (error) {
		return (
			<Box
				flexDirection="column"
				padding={1}
				borderStyle="round"
				borderColor="red"
			>
				<Box marginBottom={1}>
					<Text bold color="red">
						❌ Failed to load agents
					</Text>
				</Box>
				<Box>
					<Text color="red">{error}</Text>
				</Box>
			</Box>
		);
	}

	if (agents.length === 0) {
		return (
			<Box flexDirection="column" padding={1}>
				<Text color="yellow">ℹ️ No agents found</Text>
			</Box>
		);
	}

	return (
		<Box flexDirection="column" padding={1}>
			<Box marginBottom={1}>
				<Text bold color="green">
					✓ Agents ({agents.length})
				</Text>
			</Box>
			{agents.map(agent => (
				<Box key={agent.id} flexDirection="column" marginBottom={1}>
					<Box>
						<Text bold>{agent.name}</Text>
						<Text dimColor> ({agent.id.substring(0, 8)}...)</Text>
					</Box>
					{agent.description && (
						<Box marginLeft={2}>
							<Text dimColor>{agent.description}</Text>
						</Box>
					)}
					{agent.status && (
						<Box marginLeft={2}>
							<Text dimColor>Status: {agent.status}</Text>
						</Box>
					)}
				</Box>
			))}
		</Box>
	);
}
