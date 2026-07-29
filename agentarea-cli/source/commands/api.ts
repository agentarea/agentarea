import * as sdk from '@agentarea/api-client';
import {
	streamTaskEvents,
	submitTaskStream,
	TASK_FAILED,
} from '../services/sse.js';
import {printJson, reportResult, type SdkResult} from './output.js';

type SdkFn = (options?: unknown) => Promise<SdkResult>;

const NON_OPERATION_EXPORTS = new Set(['configureApiClient', 'client']);

function listOperationIds(): string[] {
	return Object.keys(sdk)
		.filter(
			key =>
				typeof (sdk as Record<string, unknown>)[key] === 'function' &&
				!NON_OPERATION_EXPORTS.has(key),
		)
		.sort();
}

export function printOperationList(): void {
	for (const name of listOperationIds()) {
		console.log(name);
	}
}

/**
 * Hidden escape hatch: call any generated operation by its raw operationId.
 * Kept for power users / debugging; the noun-verb router is the real CLI.
 */
export async function runApiPassthrough(
	operationId: string | undefined,
	opts: {data?: string; query?: string; path?: string},
): Promise<number> {
	if (!operationId) {
		console.error(
			'Usage: agentarea api <operationId> [--data <json>] [--query <json>] [--path <json>]',
		);
		console.error('       agentarea api --list');
		return 1;
	}

	const fn = (sdk as Record<string, unknown>)[operationId];
	if (typeof fn !== 'function' || NON_OPERATION_EXPORTS.has(operationId)) {
		console.error(`Unknown operationId: ${operationId}`);
		console.error('Run "agentarea api --list" to see available operations.');
		return 1;
	}

	const options: Record<string, unknown> = {};
	try {
		if (opts.query) {
			options['query'] = JSON.parse(opts.query);
		}

		if (opts.path) {
			options['path'] = JSON.parse(opts.path);
		}

		if (opts.data) {
			options['body'] = JSON.parse(opts.data);
		}
	} catch (error) {
		console.error(`Invalid JSON in options: ${(error as Error).message}`);
		return 1;
	}

	const result = await (fn as SdkFn)(options);
	return reportResult(result);
}

export async function runTasksSubmit(
	agentId: string | undefined,
	description: string | undefined,
	paramsJson?: string,
): Promise<number> {
	if (!agentId || !description) {
		console.error(
			'Usage: agentarea tasks submit <agentId> <description> [--data <json>]',
		);
		return 1;
	}

	let parameters: Record<string, unknown> | undefined;
	if (paramsJson) {
		try {
			parameters = JSON.parse(paramsJson);
		} catch (error) {
			console.error(`Invalid JSON in --data: ${(error as Error).message}`);
			return 1;
		}
	}

	try {
		for await (const event of submitTaskStream(agentId, {
			description,
			parameters,
		})) {
			printJson(event);
			if (event.event_type === TASK_FAILED) {
				return 1;
			}
		}
	} catch (error) {
		console.error(`Failed to submit task: ${(error as Error).message}`);
		return 1;
	}

	return 0;
}

export async function runTasksWatch(
	agentId: string | undefined,
	taskId: string | undefined,
): Promise<number> {
	if (!agentId || !taskId) {
		console.error('Usage: agentarea tasks watch <agentId> <taskId>');
		return 1;
	}

	try {
		for await (const event of streamTaskEvents(agentId, taskId)) {
			printJson(event);
			if (event.event_type === TASK_FAILED) {
				return 1;
			}
		}
	} catch (error) {
		console.error(`Failed to watch task: ${(error as Error).message}`);
		return 1;
	}

	return 0;
}
