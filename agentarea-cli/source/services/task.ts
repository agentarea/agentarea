import {apiClient} from './apiClient.js';
import {logger} from '../utils/logger.js';
import {NetworkError, ValidationError} from '../utils/error.js';
import {
	type Task,
	type TaskSubmissionRequest,
	type TaskResponse,
	type TaskStatus,
} from '../types/index.js';

export class TaskService {
	async submitTask(request: TaskSubmissionRequest): Promise<TaskResponse> {
		try {
			// Validate required fields
			if (!request.agentId || !request.title) {
				throw new ValidationError('agentId and title are required');
			}

			if (request.title.trim().length === 0) {
				throw new ValidationError('Task title cannot be empty');
			}

			// AgentArea API uses /v1/agents/{agent_id}/tasks endpoint
			const response = await apiClient
				.getClient()
				.post<TaskResponse>(`/v1/agents/${request.agentId}/tasks`, {
					description: request.title, // AgentArea uses 'description' instead of 'title'
					parameters: request.parameters || {},
				});

			logger.info(
				`Task submitted: ${
					(response.data as any).taskId || (response.data as any).id
				}`,
			);
			return response.data;
		} catch (error) {
			logger.error('Failed to submit task:', error);
			throw error instanceof ValidationError
				? error
				: new NetworkError(`Failed to submit task: ${error}`);
		}
	}

	async listTasks(
		agentId?: string,
		status?: TaskStatus,
		skip = 0,
		limit = 50,
	): Promise<{tasks: Task[]; total: number}> {
		try {
			// AgentArea uses /v1/tasks endpoint for global task listing
			const params = new URLSearchParams();
			params.append('skip', String(skip));
			params.append('limit', String(limit));

			if (status) {
				params.append('status', status);
			}

			const response = await apiClient
				.getClient()
				.get<{tasks: Task[] | any[]; total: number}>(
					`/v1/tasks?${params.toString()}`,
				);

			logger.debug(`Fetched ${response.data.tasks.length} tasks`);
			return response.data as {tasks: Task[]; total: number};
		} catch (error) {
			logger.error('Failed to list tasks:', error);
			throw new NetworkError(`Failed to list tasks: ${error}`);
		}
	}

	async getTask(taskId: string, agentId?: string): Promise<Task> {
		try {
			// AgentArea uses /v1/agents/{agent_id}/tasks/{task_id} or /v1/tasks/{task_id}
			const endpoint = agentId
				? `/v1/agents/${agentId}/tasks/${taskId}`
				: `/v1/tasks/${taskId}`;

			const response = await apiClient.getClient().get<Task>(endpoint);

			logger.debug(`Fetched task ${taskId}`);
			return response.data;
		} catch (error) {
			logger.error(`Failed to fetch task ${taskId}:`, error);
			throw new NetworkError(`Failed to fetch task: ${error}`);
		}
	}

	async cancelTask(taskId: string, agentId?: string): Promise<void> {
		try {
			// AgentArea uses DELETE on task endpoint
			const endpoint = agentId
				? `/v1/agents/${agentId}/tasks/${taskId}`
				: `/v1/tasks/${taskId}`;

			await apiClient.getClient().delete(endpoint);

			logger.info(`Task cancelled: ${taskId}`);
		} catch (error) {
			logger.error(`Failed to cancel task ${taskId}:`, error);
			throw new NetworkError(`Failed to cancel task: ${error}`);
		}
	}

	validateTaskParameters(parameters?: Record<string, unknown>): boolean {
		if (!parameters) {
			return true;
		}

		try {
			// Verify that all parameters are serializable to JSON
			JSON.stringify(parameters);
			return true;
		} catch (error) {
			logger.error('Invalid task parameters:', error);
			return false;
		}
	}

	formatTaskStatus(status: TaskStatus): string {
		const statusMap: Record<TaskStatus, string> = {
			pending: '⏳ Pending',
			running: '🔄 Running',
			completed: '✓ Completed',
			failed: '✗ Failed',
			cancelled: '⊘ Cancelled',
		};

		return statusMap[status] || status;
	}

	getSSEStreamUrl(taskId: string): string {
		return `/sse/tasks/${taskId}`;
	}
}

// Export a singleton instance
export const taskService = new TaskService();
