import {apiClient} from './apiClient.js';
import {logger} from '../utils/logger.js';
import {NetworkError} from '../utils/error.js';
import {type Agent, type AgentList, type AgentStatus} from '../types/index.js';

export class AgentService {
	async fetchAgents(
		skip = 0,
		limit = 50,
		status?: AgentStatus,
		search?: string,
	): Promise<AgentList> {
		try {
			const params = new URLSearchParams();
			params.append('skip', String(skip));
			params.append('limit', String(limit));

			if (status) {
				params.append('status', status);
			}

			if (search) {
				params.append('search', search);
			}

			// AgentArea API uses /v1/agents endpoint
			const response = await apiClient
				.getClient()
				.get<{agents: Agent[]; total: number; timestamp: string}>(
					`/v1/agents?${params.toString()}`,
				);

			const agentList: AgentList = {
				agents: response.data.agents,
				total: response.data.total,
				timestamp: new Date(response.data.timestamp),
			};

			logger.debug(`Fetched ${agentList.agents.length} agents`);
			return agentList;
		} catch (error) {
			logger.error('Failed to fetch agents:', error);
			throw new NetworkError(`Failed to fetch agents: ${error}`);
		}
	}

	async getAgent(agentId: string): Promise<Agent> {
		try {
			const response = await apiClient
				.getClient()
				.get<Agent>(`/v1/agents/${agentId}`);

			logger.debug(`Fetched agent ${agentId}`);
			return response.data;
		} catch (error) {
			logger.error(`Failed to fetch agent ${agentId}:`, error);
			throw new NetworkError(`Failed to fetch agent: ${error}`);
		}
	}

	async getAgentCapabilities(agentId: string): Promise<string[]> {
		try {
			// Get agent details which includes capabilities
			const agent = await this.getAgent(agentId);
			logger.debug(
				`Fetched ${agent.capabilities.length} capabilities for agent ${agentId}`,
			);
			return agent.capabilities;
		} catch (error) {
			logger.error(`Failed to fetch capabilities for agent ${agentId}:`, error);
			throw new NetworkError(`Failed to fetch agent capabilities: ${error}`);
		}
	}

	filterAgents(
		agents: Agent[],
		status?: AgentStatus,
		search?: string,
	): Agent[] {
		let filtered = agents;

		if (status) {
			filtered = filtered.filter(agent => agent.status === status);
		}

		if (search) {
			const searchLower = search.toLowerCase();
			filtered = filtered.filter(
				agent =>
					agent.name.toLowerCase().includes(searchLower) ||
					(agent.description?.toLowerCase().includes(searchLower) ?? false),
			);
		}

		return filtered;
	}

	paginateAgents(agents: Agent[], skip: number, limit: number): Agent[] {
		return agents.slice(skip, skip + limit);
	}

	async searchAgents(query: string): Promise<Agent[]> {
		try {
			const agentList = await this.fetchAgents(0, 100, undefined, query);
			return agentList.agents;
		} catch (error) {
			logger.error('Failed to search agents:', error);
			return [];
		}
	}

	getAgentStatusColor(status: AgentStatus): string {
		switch (status) {
			case 'online':
				return 'green';
			case 'offline':
				return 'gray';
			case 'busy':
				return 'yellow';
			case 'error':
				return 'red';
			default:
				return 'white';
		}
	}

	getAgentStatusIcon(status: AgentStatus): string {
		switch (status) {
			case 'online':
				return '🟢';
			case 'offline':
				return '⚪';
			case 'busy':
				return '🟡';
			case 'error':
				return '🔴';
			default:
				return '⚪';
		}
	}
}

// Export a singleton instance
export const agentService = new AgentService();
