import EventSource from 'eventsource';
import {getApiBaseUrl, resolveToken} from './apiRuntime.js';
import {logger} from '../utils/logger.js';
import {SSEError} from '../utils/error.js';
import {type TaskOutputEvent} from '../types/index.js';

export type SSEEventHandler = (event: TaskOutputEvent) => void;
export type SSEErrorHandler = (error: Error) => void;

interface SSEHandlers {
	agentId: string;
	onMessage: SSEEventHandler;
	onError: SSEErrorHandler;
}

const TASK_EVENT_TYPES = [
	'task-started',
	'output',
	'status-update',
	'progress',
	'task-completed',
	'task-error',
];

export class SSEService {
	private eventSources: Map<string, EventSource> = new Map();
	private handlers: Map<string, SSEHandlers> = new Map();
	private reconnectAttempts: Map<string, number> = new Map();
	private maxReconnectAttempts = 5;
	private reconnectDelay = 1000; // milliseconds

	async connect(
		agentId: string,
		taskId: string,
		onMessage: SSEEventHandler,
		onError: SSEErrorHandler,
		token?: string,
	): Promise<void> {
		try {
			this.disconnect(taskId);

			const token_ = token ?? (await resolveToken());

			if (!token_) {
				throw new SSEError(
					'No authentication token available for SSE connection',
				);
			}

			const baseUrl = getApiBaseUrl().replace(/\/$/, '');
			const url = `${baseUrl}/v1/agents/${agentId}/tasks/${taskId}/events/stream`;

			const eventSource = new EventSource(url, {
				headers: {
					Authorization: `Bearer ${token_}`,
				},
			});

			for (const type of TASK_EVENT_TYPES) {
				eventSource.addEventListener(type, (event: Event) => {
					const messageEvent = event as MessageEvent;
					const data = JSON.parse(messageEvent.data) as TaskOutputEvent;
					onMessage(data);

					if (type === 'task-completed' || type === 'task-error') {
						this.disconnect(taskId);
					}
				});
			}

			eventSource.onerror = () => {
				this.handleConnectionError(taskId, onError);
			};

			this.eventSources.set(taskId, eventSource);
			this.handlers.set(taskId, {agentId, onMessage, onError});
			this.reconnectAttempts.set(taskId, 0);

			logger.info(`SSE connection established for task ${taskId}`);
		} catch (error) {
			logger.error(
				`Failed to establish SSE connection for task ${taskId}:`,
				error,
			);
			throw error instanceof SSEError
				? error
				: new SSEError(`Failed to connect to task stream: ${error}`);
		}
	}

	private handleConnectionError(
		taskId: string,
		onError: SSEErrorHandler,
	): void {
		const attempts = (this.reconnectAttempts.get(taskId) || 0) + 1;
		this.reconnectAttempts.set(taskId, attempts);

		if (attempts > this.maxReconnectAttempts) {
			logger.error(`Max reconnection attempts reached for task ${taskId}`);
			const error = new Error(`Connection lost after ${attempts} attempts`);
			onError(error);
			this.disconnect(taskId);
			return;
		}

		const delay = this.reconnectDelay * Math.pow(2, attempts - 1);
		logger.warn(
			`SSE connection error for task ${taskId}, retrying in ${delay}ms (attempt ${attempts}/${this.maxReconnectAttempts})`,
		);

		setTimeout(() => {
			const handlers = this.handlers.get(taskId);
			if (handlers) {
				this.connect(
					handlers.agentId,
					taskId,
					handlers.onMessage,
					handlers.onError,
				).catch(error => {
					logger.error('Reconnection failed:', error);
				});
			}
		}, delay);
	}

	disconnect(taskId: string): void {
		const eventSource = this.eventSources.get(taskId);

		if (eventSource) {
			eventSource.close();
			this.eventSources.delete(taskId);
			this.handlers.delete(taskId);
			this.reconnectAttempts.delete(taskId);

			logger.debug(`SSE connection closed for task ${taskId}`);
		}
	}

	disconnectAll(): void {
		this.eventSources.forEach(eventSource => {
			eventSource.close();
		});

		this.eventSources.clear();
		this.handlers.clear();
		this.reconnectAttempts.clear();

		logger.debug('All SSE connections closed');
	}

	isConnected(taskId: string): boolean {
		const eventSource = this.eventSources.get(taskId);
		return (
			eventSource !== undefined && eventSource.readyState === EventSource.OPEN
		);
	}

	getActiveConnections(): string[] {
		return Array.from(this.eventSources.keys());
	}
}

// Export a singleton instance
export const sseService = new SSEService();
