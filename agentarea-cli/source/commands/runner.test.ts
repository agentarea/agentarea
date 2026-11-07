import test from 'ava';
import {
	apiRoute,
	checkedAssign,
	claudeEvents,
	codexConfig,
	codexEvents,
	managesNetwork,
	socketUrl,
} from './runner.js';

test('codex app-server items become the turn events the platform keeps', t => {
	const changes = new Map<string, unknown>();
	t.deepEqual(
		codexEvents(
			'item/agentMessage/delta',
			{itemId: 'msg_1', delta: 'Hel'},
			null,
			changes,
		),
		[{kind: 'message.delta', item_id: 'msg_1', text: 'Hel'}],
	);
	t.deepEqual(
		codexEvents(
			'item/started',
			{
				item: {
					type: 'commandExecution',
					id: 'exec-1',
					command: "/bin/bash -lc 'ls -la'",
					commandActions: [{type: 'listFiles', command: 'ls -la'}],
				},
			},
			null,
			changes,
		),
		[
			{
				kind: 'tool.call',
				id: 'exec-1',
				name: 'shell',
				arguments: {command: 'ls -la'},
			},
		],
	);
	t.deepEqual(
		codexEvents(
			'item/completed',
			{
				item: {
					type: 'commandExecution',
					id: 'exec-1',
					status: 'failed',
					aggregatedOutput: 'nope',
					exitCode: 2,
				},
			},
			null,
			changes,
		),
		[
			{
				kind: 'tool.result',
				id: 'exec-1',
				name: 'shell',
				output: 'nope',
				success: false,
				exit_code: 2,
			},
		],
	);
	t.deepEqual(
		codexEvents(
			'item/completed',
			{item: {type: 'agentMessage', id: 'msg_1', text: 'Hello'}},
			'gpt-6-luna',
			changes,
		),
		[{kind: 'message', item_id: 'msg_1', text: 'Hello', model: 'gpt-6-luna'}],
	);
	t.deepEqual(codexEvents('turn/diff/updated', {diff: ''}, null, changes), []);
});

test('a codex file change keeps its paths for the approval that names none', t => {
	const changes = new Map<string, unknown>();
	codexEvents(
		'item/started',
		{
			item: {
				type: 'fileChange',
				id: 'patch-1',
				changes: [{path: 'a.md', kind: {type: 'add'}, diff: '+x'}],
			},
		},
		null,
		changes,
	);
	t.deepEqual(changes.get('patch-1'), [
		{path: 'a.md', kind: {type: 'add'}, diff: '+x'},
	]);
});

test('claude stream-json deltas belong to the message that started them', t => {
	let current = '';
	const stream = {
		currentMessage(id?: string) {
			if (id) {
				current = id;
			}

			return current;
		},
	};
	t.deepEqual(
		claudeEvents(
			{
				type: 'stream_event',
				event: {type: 'message_start', message: {id: 'm1'}},
			},
			stream,
		),
		[],
	);
	t.deepEqual(
		claudeEvents(
			{
				type: 'stream_event',
				event: {
					type: 'content_block_delta',
					delta: {type: 'text_delta', text: 'Hi'},
				},
			},
			stream,
		),
		[{kind: 'message.delta', item_id: 'm1', text: 'Hi'}],
	);
	t.deepEqual(
		claudeEvents(
			{
				type: 'assistant',
				message: {
					id: 'm1',
					content: [
						{type: 'text', text: 'Hi there'},
						{type: 'tool_use', id: 'tu1', name: 'Bash', input: {command: 'ls'}},
					],
				},
			},
			stream,
		),
		[
			{kind: 'message', item_id: 'm1', text: 'Hi there'},
			{kind: 'tool.call', id: 'tu1', name: 'Bash', arguments: {command: 'ls'}},
		],
	);
});

test('the socket is the API over ws, or wss behind https', t => {
	const config = {
		api_url: 'https://api.example.test',
		workspace: 'w',
		client_id: 'c1',
		kind: 'codex' as const,
		token: 'aat_x',
	};
	t.is(socketUrl(config), 'wss://api.example.test/v1/runner/connect');
	t.is(
		socketUrl({...config, api_url: 'http://127.0.0.1:18000'}),
		'ws://127.0.0.1:18000/v1/runner/connect',
	);
});

test('only requirements that turn the managed network proxy on let a host be approved', t => {
	t.true(managesNetwork('[network_proxy]\nenabled = true\n'));
	t.true(
		managesNetwork(
			'allowed_approval_policies = ["on-request"]\n\n[network_proxy]\nallow_local_binding = false\nenabled = true\n\n[rules]\nx = 1\n',
		),
	);
	t.false(managesNetwork(''));
	t.false(managesNetwork('[network_proxy]\nenabled = false\n'));
	t.false(managesNetwork('[network_proxy]\n\n[rules]\nenabled = true\n'));
});

test('a sandboxed config proxies every host, so one off the list can be asked for', t => {
	const options = {
		config: {
			api_url: 'http://127.0.0.1:18000',
			workspace: 'w',
			client_id: 'c1',
			kind: 'codex' as const,
			token: 'aat_x',
		},
		harness: 'codex' as const,
		root: '/data',
		loginFrom: '/login',
		sandbox: 'profile' as const,
		allowDomains: [],
		capacity: 1,
	};
	const config = codexConfig(options, '/data/profiles/u/codex', ['pypi.org']);
	t.regex(config, /\.network\]\nenabled = true\n/);
	t.regex(config, /"pypi\.org" = "allow"/);
	t.regex(codexConfig(options, '/data/profiles/u/codex'), /enabled = true/);
});

const assign = {
	turn_id: 'a3f1c2d4-0000-4000-8000-000000000001',
	task_id: 'a3f1c2d4-0000-4000-8000-000000000002',
	agent_id: 'a3f1c2d4-0000-4000-8000-000000000003',
	requested_by: 'a3f1c2d4-0000-4000-8000-000000000004',
	mcp_path: '/mcp/clients/a3f1c2d4-0000-4000-8000-000000000005',
	allow_domains: ['pypi.org', '*.npmjs.org'],
};

test('a turn whose ids would name folders outside the runner root is refused', t => {
	t.notThrows(() => checkedAssign(assign));
	t.throws(() => checkedAssign({...assign, task_id: '../../etc'}), {
		message: /task_id/,
	});
	t.throws(() => checkedAssign({...assign, requested_by: 'a/b'}), {
		message: /requested_by/,
	});
});

test('a turn may reach only its client MCP endpoint and plain hosts', t => {
	t.throws(() => checkedAssign({...assign, mcp_path: '@evil.example/mcp'}), {
		message: /mcp_path/,
	});
	t.throws(() => checkedAssign({...assign, allow_domains: ['a.org"\n[x]']}), {
		message: /allowed domains/,
	});
});

test('an API route stays on the platform origin', t => {
	t.is(
		apiRoute('http://localhost:8000', '/v1/runner/whoami'),
		'http://localhost:8000/v1/runner/whoami',
	);
	t.is(
		apiRoute('https://api.example.com/base/', '/mcp/clients/x'),
		'https://api.example.com/base/mcp/clients/x',
	);
	t.throws(() => apiRoute('http://localhost:8000', '//evil.example/x'));
});
