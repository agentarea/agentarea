import {getApiBaseUrl, resolveToken} from './apiRuntime.js';
import {SSEError} from '../utils/error.js';

/**
 * The task event stream speaks the canonical event contract (ADR-0019): the
 * SSE event name and the payload's `event_type` are the same dotted name, and
 * every payload is the same envelope. The CLI stays vocabulary-agnostic — it
 * forwards whatever the server sends and only needs to recognise the terminals
 * to know when to stop, so new event types need no CLI change.
 */
export const TASK_COMPLETED = 'task.completed';
export const TASK_FAILED = 'task.failed';
export const TASK_CANCELLED = 'task.cancelled';

const TERMINAL_EVENT_TYPES: ReadonlySet<string> = new Set([
	TASK_COMPLETED,
	TASK_FAILED,
	TASK_CANCELLED,
]);

// Transport-level frames the server emits around the domain events.
const CONTROL_EVENT_TYPES: ReadonlySet<string> = new Set([
	'connected',
	'disconnected',
	'ping',
	'pong',
	'keepalive',
	'heartbeat',
	'stream_error',
]);

export interface TaskEvent {
	event_type: string;
	event_id?: string;
	timestamp?: string;
	data: Record<string, unknown>;
}

export function isTerminalEvent(eventType: string): boolean {
	return TERMINAL_EVENT_TYPES.has(eventType);
}

export function isControlEvent(eventType: string): boolean {
	return CONTROL_EVENT_TYPES.has(eventType.toLowerCase());
}

function parseFrame(frame: string): TaskEvent | null {
	let name: string | undefined;
	const dataLines: string[] = [];

	for (const line of frame.split('\n')) {
		if (line.startsWith(':')) {
			continue;
		}

		if (line.startsWith('event:')) {
			name = line.slice('event:'.length).trim();
		} else if (line.startsWith('data:')) {
			dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
		}
	}

	if (dataLines.length === 0) {
		return null;
	}

	let payload: Record<string, unknown>;
	try {
		payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
	} catch {
		return null;
	}

	// Domain events carry the envelope; control frames are bare dicts named
	// only by the SSE event field.
	const eventType =
		typeof payload['event_type'] === 'string' ? payload['event_type'] : name;
	if (!eventType) {
		return null;
	}

	const data = payload['data'];
	return {
		event_type: eventType,
		event_id: payload['event_id'] as string | undefined,
		timestamp: payload['timestamp'] as string | undefined,
		data:
			data && typeof data === 'object'
				? (data as Record<string, unknown>)
				: payload,
	};
}

/**
 * Parse a raw SSE byte stream into events. Frames are separated by a blank
 * line and may be split across chunk boundaries at any byte.
 */
export async function* parseSseStream(
	source: AsyncIterable<Uint8Array>,
): AsyncGenerator<TaskEvent> {
	const decoder = new TextDecoder();
	let buffer = '';

	for await (const chunk of source) {
		buffer += decoder.decode(chunk, {stream: true});

		let separator = buffer.indexOf('\n\n');
		while (separator !== -1) {
			const frame = buffer.slice(0, separator);
			buffer = buffer.slice(separator + 2);

			const event = parseFrame(frame);
			if (event) {
				yield event;
			}

			separator = buffer.indexOf('\n\n');
		}
	}

	const tail = parseFrame(buffer);
	if (tail) {
		yield tail;
	}
}

/**
 * Drop transport frames and stop after the task reaches a terminal event, so
 * a stream the server keeps open does not hang the caller.
 */
export async function* filterTaskEvents(
	source: AsyncIterable<TaskEvent>,
): AsyncGenerator<TaskEvent> {
	for await (const event of source) {
		if (isControlEvent(event.event_type)) {
			continue;
		}

		yield event;

		if (isTerminalEvent(event.event_type)) {
			return;
		}
	}
}

async function* openSseRequest(
	path: string,
	init: RequestInit = {},
): AsyncGenerator<TaskEvent> {
	const token = await resolveToken();
	if (!token) {
		throw new SSEError('No authentication token available for SSE connection');
	}

	const baseUrl = getApiBaseUrl().replace(/\/$/, '');
	const response = await fetch(`${baseUrl}${path}`, {
		...init,
		headers: {
			...init.headers,
			Authorization: `Bearer ${token}`,
			Accept: 'text/event-stream',
		},
	});

	if (!response.ok) {
		throw new SSEError(
			`Failed to open task stream: ${response.status} ${response.statusText}`,
		);
	}

	if (!response.body) {
		throw new SSEError('Task stream response has no body');
	}

	yield* parseSseStream(response.body as unknown as AsyncIterable<Uint8Array>);
}

export interface StreamTaskEventsOptions {
	includeChunks?: boolean;
	signal?: AbortSignal;
}

/**
 * Stream a task's events, ending after the terminal event. Catch-up history
 * replays first, then live events.
 */
export function streamTaskEvents(
	agentId: string,
	taskId: string,
	options: StreamTaskEventsOptions = {},
): AsyncGenerator<TaskEvent> {
	const query = options.includeChunks === false ? '?include_chunks=false' : '';
	return filterTaskEvents(
		openSseRequest(
			`/v1/agents/${agentId}/tasks/${taskId}/events/stream${query}`,
			{signal: options.signal},
		),
	);
}

/**
 * Create a task and stream its events. The create endpoint is itself an event
 * stream, so submitting and watching are the same read path.
 */
export function submitTaskStream(
	agentId: string,
	body: {description: string; parameters?: Record<string, unknown>},
): AsyncGenerator<TaskEvent> {
	// Task creation is JSON; the CLI sends no attachments.
	return filterTaskEvents(
		openSseRequest(`/v1/agents/${agentId}/tasks/`, {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({parameters: {}, ...body}),
		}),
	);
}
