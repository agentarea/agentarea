import {useState, useEffect, useCallback} from 'react';
import {agentService} from '../services/agent.js';
import {logger} from '../utils/logger.js';
import {type Agent, type AgentStatus, type AgentList} from '../types/index.js';

export interface AgentState {
	agents: Agent[];
	isLoading: boolean;
	error: string | null;
	total: number;
	skip: number;
	limit: number;
	filteredAgents: Agent[];
	currentFilter: {
		status?: AgentStatus;
		search?: string;
	};
}

export function useAgent(autoFetch = true) {
	const [state, setState] = useState<AgentState>({
		agents: [],
		isLoading: false,
		error: null,
		total: 0,
		skip: 0,
		limit: 50,
		filteredAgents: [],
		currentFilter: {},
	});

	// Fetch agents on mount
	useEffect(() => {
		if (autoFetch) {
			fetchAgents();
		}
	}, []);

	// Apply filters whenever agents or filter changes
	useEffect(() => {
		const filtered = agentService.filterAgents(
			state.agents,
			state.currentFilter.status,
			state.currentFilter.search,
		);

		setState(prev => ({
			...prev,
			filteredAgents: filtered,
		}));
	}, [state.agents, state.currentFilter]);

	const fetchAgents = useCallback(
		async (skip = 0, limit = 50, status?: AgentStatus, search?: string) => {
			setState(prev => ({...prev, isLoading: true, error: null}));

			try {
				const agentList = await agentService.fetchAgents(
					skip,
					limit,
					status,
					search,
				);

				setState(prev => ({
					...prev,
					agents: agentList.agents,
					total: agentList.total,
					skip,
					limit,
					isLoading: false,
				}));

				logger.debug(`Fetched ${agentList.agents.length} agents`);
				return agentList;
			} catch (error) {
				const errorMessage =
					error instanceof Error ? error.message : 'Failed to fetch agents';

				setState(prev => ({
					...prev,
					isLoading: false,
					error: errorMessage,
				}));

				logger.error('Error fetching agents:', errorMessage);
				return null;
			}
		},
		[],
	);

	const getAgent = useCallback(
		async (agentId: string): Promise<Agent | null> => {
			try {
				const agent = await agentService.getAgent(agentId);
				return agent;
			} catch (error) {
				logger.error(`Error fetching agent ${agentId}:`, error);
				return null;
			}
		},
		[],
	);

	const filterByStatus = useCallback((status?: AgentStatus) => {
		setState(prev => ({
			...prev,
			currentFilter: {
				...prev.currentFilter,
				status,
			},
		}));
	}, []);

	const search = useCallback((query?: string) => {
		setState(prev => ({
			...prev,
			currentFilter: {
				...prev.currentFilter,
				search: query,
			},
		}));
	}, []);

	const nextPage = useCallback(() => {
		const newSkip = state.skip + state.limit;
		if (newSkip < state.total) {
			fetchAgents(
				newSkip,
				state.limit,
				state.currentFilter.status,
				state.currentFilter.search,
			);
		}
	}, [state.skip, state.limit, state.total, state.currentFilter, fetchAgents]);

	const previousPage = useCallback(() => {
		const newSkip = Math.max(0, state.skip - state.limit);
		if (newSkip !== state.skip) {
			fetchAgents(
				newSkip,
				state.limit,
				state.currentFilter.status,
				state.currentFilter.search,
			);
		}
	}, [state.skip, state.limit, state.currentFilter, fetchAgents]);

	const getFilteredAgents = useCallback((): Agent[] => {
		return state.filteredAgents;
	}, [state.filteredAgents]);

	const hasNextPage = useCallback((): boolean => {
		return state.skip + state.limit < state.total;
	}, [state.skip, state.limit, state.total]);

	const hasPreviousPage = useCallback((): boolean => {
		return state.skip > 0;
	}, [state.skip]);

	const clearError = useCallback(() => {
		setState(prev => ({...prev, error: null}));
	}, []);

	const refreshAgents = useCallback(() => {
		fetchAgents(
			0,
			state.limit,
			state.currentFilter.status,
			state.currentFilter.search,
		);
	}, [state.limit, state.currentFilter, fetchAgents]);

	return {
		...state,
		fetchAgents,
		getAgent,
		filterByStatus,
		search,
		nextPage,
		previousPage,
		getFilteredAgents,
		hasNextPage,
		hasPreviousPage,
		clearError,
		refreshAgents,
	};
}
