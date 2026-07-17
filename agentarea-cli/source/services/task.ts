import {
	createTaskForAgentWithStreamV1AgentsAgentIdTasksPost,
	listAgentTasksV1AgentsAgentIdTasksGet,
	getAllTasksV1TasksGet,
	getAgentTaskV1AgentsAgentIdTasksTaskIdGet,
	getTaskByIdV1TasksTaskIdGet,
	cancelAgentTaskV1AgentsAgentIdTasksTaskIdDelete,
} from '@agentarea/api-client';
import {logger} from '../utils/logger.js';
import {NetworkError, ValidationError} from '../utils/error.js';
import {type TaskStatus, type TaskSubmissionRequest} from '../types/index.js';

export class TaskService {
	async submitTask(request: TaskSubmissionRequest): Promise<unknown> {
		if (!request.agentId || !request.title) {
			throw new ValidationError('agentId and title are required');
		}

		if (request.title.trim().length === 0) {
			throw new ValidationError('Task title cannot be empty');
		}

		const {data, error} =
			await createTaskForAgentWithStreamV1AgentsAgentIdTasksPost({
				path: {agent_id: request.agentId},
				body: {
					description: request.title,
					parameters: request.parameters ?? {},
				},
			});

		if (error || !data) {
			logger.error('Failed to submit task:', error);
			throw new NetworkError(`Failed to submit task: ${JSON.stringify(error)}`);
		}

		return data;
	}

	async listTasks(
		agentId?: string,
		status?: TaskStatus,
		skip = 0,
		limit = 50,
	): Promise<unknown> {
		if (agentId) {
			const {data, error} = await listAgentTasksV1AgentsAgentIdTasksGet({
				path: {agent_id: agentId},
				query: status ? {status} : undefined,
			});

			if (error || !data) {
				logger.error('Failed to list tasks:', error);
				throw new NetworkError(
					`Failed to list tasks: ${JSON.stringify(error)}`,
				);
			}

			return data;
		}

		const {data, error} = await getAllTasksV1TasksGet({
			query: {status: status ?? null, limit, offset: skip},
		});

		if (error || !data) {
			logger.error('Failed to list tasks:', error);
			throw new NetworkError(`Failed to list tasks: ${JSON.stringify(error)}`);
		}

		return data;
	}

	async getTask(taskId: string, agentId?: string): Promise<unknown> {
		if (agentId) {
			const {data, error} = await getAgentTaskV1AgentsAgentIdTasksTaskIdGet({
				path: {agent_id: agentId, task_id: taskId},
			});

			if (error || !data) {
				logger.error(`Failed to fetch task ${taskId}:`, error);
				throw new NetworkError(
					`Failed to fetch task: ${JSON.stringify(error)}`,
				);
			}

			return data;
		}

		const {data, error} = await getTaskByIdV1TasksTaskIdGet({
			path: {task_id: taskId},
		});

		if (error || !data) {
			logger.error(`Failed to fetch task ${taskId}:`, error);
			throw new NetworkError(`Failed to fetch task: ${JSON.stringify(error)}`);
		}

		return data;
	}

	async cancelTask(taskId: string, agentId: string): Promise<void> {
		const {error} = await cancelAgentTaskV1AgentsAgentIdTasksTaskIdDelete({
			path: {agent_id: agentId, task_id: taskId},
		});

		if (error) {
			logger.error(`Failed to cancel task ${taskId}:`, error);
			throw new NetworkError(`Failed to cancel task: ${JSON.stringify(error)}`);
		}

		logger.info(`Task cancelled: ${taskId}`);
	}

	validateTaskParameters(parameters?: Record<string, unknown>): boolean {
		if (!parameters) {
			return true;
		}

		try {
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
}

// Export a singleton instance
export const taskService = new TaskService();
