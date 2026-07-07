import {
	listAgentsV1AgentsGet,
	getAgentV1AgentsAgentIdGet,
	type AgentResponse,
} from '@agentarea/api-client';
import {logger} from '../utils/logger.js';
import {NetworkError} from '../utils/error.js';
import {type Agent, type AgentList, type AgentStatus} from '../types/index.js';

function toAgent(response: AgentResponse): Agent {
	return {
		id: response.id,
		name: response.name,
		description: response.description ?? undefined,
		status: (response.status as AgentStatus) || 'offline',
		capabilities: [],
		metadata: {slug: response.slug, agentType: response.agent_type},
	};
}

export class AgentService {
	async fetchAgents(
		skip = 0,
		limit = 50,
		status?: AgentStatus,
		search?: string,
	): Promise<AgentList> {
		const {data, error} = await listAgentsV1AgentsGet();

		if (error || !data) {
			logger.error('Failed to fetch agents:', error);
			throw new NetworkError(`Failed to fetch agents: ${JSON.stringify(error)}`);
		}

		let agents = data.map(toAgent);
		agents = this.filterAgents(agents, status, search);
		const total = agents.length;
		agents = this.paginateAgents(agents, skip, limit);

		logger.debug(`Fetched ${agents.length} agents`);
		return {agents, total, timestamp: new Date()};
	}

	async getAgent(agentId: string): Promise<Agent> {
		const {data, error} = await getAgentV1AgentsAgentIdGet({
			path: {agent_id: agentId},
		});

		if (error || !data) {
			logger.error(`Failed to fetch agent ${agentId}:`, error);
			throw new NetworkError(`Failed to fetch agent: ${JSON.stringify(error)}`);
		}

		logger.debug(`Fetched agent ${agentId}`);
		return toAgent(data);
	}

	async getAgentCapabilities(agentId: string): Promise<string[]> {
		const agent = await this.getAgent(agentId);
		return agent.capabilities;
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
