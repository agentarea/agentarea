import test from 'ava';
import {
	filterTaskEvents,
	isControlEvent,
	isTerminalEvent,
	parseSseStream,
	type TaskEvent,
} from './sse.js';

function events(...types: string[]): AsyncIterable<TaskEvent> {
	return {
		async *[Symbol.asyncIterator]() {
			for (const event_type of types) {
				yield {event_type, data: {}};
			}
		},
	};
}

async function collectEvents(
	source: AsyncIterable<TaskEvent>,
): Promise<string[]> {
	const seen: string[] = [];
	for await (const event of filterTaskEvents(source)) {
		seen.push(event.event_type);
	}

	return seen;
}

function stream(...chunks: string[]): AsyncIterable<Uint8Array> {
	const encoder = new TextEncoder();
	return {
		async *[Symbol.asyncIterator]() {
			for (const chunk of chunks) {
				yield encoder.encode(chunk);
			}
		},
	};
}

async function collect(
	source: AsyncIterable<Uint8Array>,
): Promise<TaskEvent[]> {
	const events: TaskEvent[] = [];
	for await (const event of parseSseStream(source)) {
		events.push(event);
	}

	return events;
}

test('unwraps the canonical envelope', async t => {
	const events = await collect(
		stream(
			'event: llm.call.completed\n' +
				'data: {"event_type": "llm.call.completed", "event_id": "e1", "timestamp": "t1", "data": {"content": "hi"}}\n\n',
		),
	);

	t.deepEqual(events, [
		{
			event_type: 'llm.call.completed',
			event_id: 'e1',
			timestamp: 't1',
			data: {content: 'hi'},
		},
	]);
});

test('is vocabulary-agnostic: unknown event types pass through', async t => {
	const events = await collect(
		stream(
			'event: some.future.type\ndata: {"event_type": "some.future.type", "data": {"x": 1}}\n\n',
		),
	);

	t.is(events.length, 1);
	t.is(events[0]?.event_type, 'some.future.type');
	t.deepEqual(events[0]?.data, {x: 1});
});

test('falls back to the SSE event name when the payload has no event_type', async t => {
	const events = await collect(
		stream(
			'event: connected\ndata: {"task_id": "t", "message": "Connected"}\n\n',
		),
	);

	t.is(events[0]?.event_type, 'connected');
	t.deepEqual(events[0]?.data, {task_id: 't', message: 'Connected'});
});

test('reassembles events split across chunk boundaries', async t => {
	const events = await collect(
		stream(
			'event: task.st',
			'arted\ndata: {"event_type": "task.start',
			'ed", "data": {}}\n',
			'\nevent: task.completed\ndata: {"event_type": "task.completed", "data": {}}\n\n',
		),
	);

	t.deepEqual(
		events.map(event => event.event_type),
		['task.started', 'task.completed'],
	);
});

test('joins multi-line data payloads', async t => {
	const events = await collect(
		stream('event: x\ndata: {"event_type": "x",\ndata:  "data": {"a": 1}}\n\n'),
	);

	t.deepEqual(events[0]?.data, {a: 1});
});

test('skips comments, heartbeats and malformed payloads', async t => {
	const events = await collect(
		stream(
			': heartbeat\n\n',
			'event: broken\ndata: {not json\n\n',
			'event: task.completed\ndata: {"event_type": "task.completed", "data": {}}\n\n',
		),
	);

	t.deepEqual(
		events.map(event => event.event_type),
		['task.completed'],
	);
});

test('terminal detection covers exactly the canonical terminals', t => {
	t.true(isTerminalEvent('task.completed'));
	t.true(isTerminalEvent('task.failed'));
	t.true(isTerminalEvent('task.cancelled'));
	t.false(isTerminalEvent('task.started'));
	t.false(isTerminalEvent('llm.call.chunk'));
	t.false(isTerminalEvent('complete'));
});

test('control events are recognised so they stay out of the output', t => {
	t.true(isControlEvent('connected'));
	t.true(isControlEvent('ping'));
	t.false(isControlEvent('llm.call.chunk'));
	t.false(isControlEvent('task.completed'));
});

test('filter drops control frames and keeps domain events', async t => {
	t.deepEqual(
		await collectEvents(
			events('connected', 'task.started', 'ping', 'llm.call.chunk'),
		),
		['task.started', 'llm.call.chunk'],
	);
});

test('filter stops at the terminal event and yields it', async t => {
	t.deepEqual(
		await collectEvents(
			events('task.started', 'task.completed', 'llm.call.chunk'),
		),
		['task.started', 'task.completed'],
	);
});

test('filter stops on a failed task', async t => {
	t.deepEqual(await collectEvents(events('task.started', 'task.failed')), [
		'task.started',
		'task.failed',
	]);
});
