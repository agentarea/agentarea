import {useState, useEffect, useCallback} from 'react';
import {sseService} from '../services/sse.js';
import {logger} from '../utils/logger.js';
import {type TaskOutputEvent, type TaskStatus} from '../types/index.js';

export interface SSEState {
	isConnected: boolean;
	isLoading: boolean;
	error: string | null;
	events: TaskOutputEvent[];
	currentStatus: TaskStatus | null;
	progress: {current: number; total: number; percentage: number} | null;
	output: string;
}

export function useSSE(taskId?: string) {
	const [state, setState] = useState<SSEState>({
		isConnected: false,
		isLoading: false,
		error: null,
		events: [],
		currentStatus: null,
		progress: null,
		output: '',
	});

	const connect = useCallback(async (id: string) => {
		setState(prev => ({...prev, isLoading: true, error: null}));

		try {
			await sseService.connect(
				id,
				// onMessage handler
				event => {
					logger.debug(`SSE event: ${event.eventType}`);

					setState(prev => {
						let newOutput = prev.output;
						let newProgress = prev.progress;
						let newStatus = prev.currentStatus;

						// Process different event types
						if (event.eventType === 'output' && 'content' in event.data) {
							newOutput += event.data.content + '\n';
						} else if (
							event.eventType === 'progress' &&
							'percentage' in event.data
						) {
							newProgress = {
								current: event.data.current as number,
								total: event.data.total as number,
								percentage: event.data.percentage as number,
							};
						} else if (event.eventType === 'status' && 'status' in event.data) {
							newStatus = event.data.status as TaskStatus;
						}

						return {
							...prev,
							events: [...prev.events, event],
							output: newOutput,
							progress: newProgress,
							currentStatus: newStatus,
						};
					});
				},
				// onError handler
				error => {
					logger.error('SSE connection error:', error);
					setState(prev => ({
						...prev,
						isConnected: false,
						isLoading: false,
						error: error.message,
					}));
				},
			);

			setState(prev => ({
				...prev,
				isConnected: true,
				isLoading: false,
			}));

			logger.info(`Connected to SSE stream for task ${id}`);
		} catch (error) {
			const errorMessage =
				error instanceof Error ? error.message : 'Failed to connect to stream';

			setState(prev => ({
				...prev,
				isLoading: false,
				error: errorMessage,
			}));

			logger.error('SSE connection failed:', errorMessage);
		}
	}, []);

	const disconnect = useCallback((id: string) => {
		sseService.disconnect(id);
		setState(prev => ({
			...prev,
			isConnected: false,
		}));

		logger.debug(`Disconnected from SSE stream for task ${id}`);
	}, []);

	const clearError = useCallback(() => {
		setState(prev => ({...prev, error: null}));
	}, []);

	const clearOutput = useCallback(() => {
		setState(prev => ({
			...prev,
			output: '',
			events: [],
			progress: null,
		}));
	}, []);

	// Auto-connect if taskId provided
	useEffect(() => {
		if (taskId) {
			connect(taskId);

			return () => {
				disconnect(taskId);
			};
		}

		return undefined;
	}, [taskId, connect, disconnect]);

	return {
		...state,
		connect,
		disconnect,
		clearError,
		clearOutput,
	};
}
