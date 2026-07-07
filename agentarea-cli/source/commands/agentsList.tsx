import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {agentService} from '../services/agent.js';
import {logger} from '../utils/logger.js';
import {type Agent} from '../types/index.js';

export function AgentsList() {
	const [agents, setAgents] = useState<Agent[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const fetchAgents = async () => {
			try {
				setLoading(true);
				const agentList = await agentService.fetchAgents(0, 100);
				setAgents(agentList.agents);
				logger.info(`Loaded ${agentList.agents.length} agents`);
			} catch (err) {
				const message = err instanceof Error ? err.message : 'Failed to load agents';
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
