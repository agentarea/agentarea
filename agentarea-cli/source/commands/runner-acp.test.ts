import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'ava';
import {
	AcpStream,
	AcpTurn,
	acpCommand,
	acpEvents,
	acpPermissionOption,
	isRunnerHarness,
	type ApprovalAsk,
	type Assign,
	type McpRelay,
	type RunnerOptions,
	type TurnEventBody,
} from './runner.js';

test('an ACP turn streams its message and says it once whole', t => {
	const stream = new AcpStream('turn');
	t.deepEqual(
		acpEvents(
			{
				sessionUpdate: 'agent_message_chunk',
				messageId: 'm1',
				content: {type: 'text', text: 'Hel'},
			},
			stream,
		),
		[{kind: 'message.delta', item_id: 'm1', text: 'Hel'}],
	);
	acpEvents(
		{
			sessionUpdate: 'agent_message_chunk',
			messageId: 'm1',
			content: {type: 'text', text: 'lo'},
		},
		stream,
	);
	t.deepEqual(
		acpEvents(
			{
				sessionUpdate: 'tool_call',
				toolCallId: 'c1',
				title: 'Read config',
				status: 'pending',
				rawInput: {path: 'a.toml'},
			},
			stream,
		),
		[
			{kind: 'message', item_id: 'm1', text: 'Hello'},
			{
				kind: 'tool.call',
				id: 'c1',
				name: 'Read config',
				arguments: {path: 'a.toml'},
			},
		],
	);
	t.deepEqual(
		acpEvents(
			{
				sessionUpdate: 'tool_call_update',
				toolCallId: 'c1',
				status: 'completed',
				content: [{type: 'content', content: {type: 'text', text: 'x = 1'}}],
			},
			stream,
		),
		[
			{
				kind: 'tool.result',
				id: 'c1',
				name: 'Read config',
				output: 'x = 1',
				success: true,
			},
		],
	);
	t.is(stream.response, 'Hello');
});

test('a permission is answered with the allow-once or reject-once option', t => {
	const options = [
		{optionId: 'yes-always', kind: 'allow_always'},
		{optionId: 'yes', kind: 'allow_once'},
		{optionId: 'no', kind: 'reject_once'},
	];
	t.is(acpPermissionOption(options, true), 'yes');
	t.is(acpPermissionOption(options, false), 'no');
	t.is(acpPermissionOption([{optionId: 'a', kind: 'allow_always'}], true), 'a');
});

test('each ACP harness has its command, and a custom one needs one given', t => {
	t.deepEqual(acpCommand({harness: 'opencode'}), ['opencode', 'acp']);
	t.deepEqual(
		acpCommand({harness: 'gemini', command: ['/opt/gemini', '--acp']}),
		['/opt/gemini', '--acp'],
	);
	t.throws(() => acpCommand({harness: 'acp'}), {message: /needs --command/});
	t.true(isRunnerHarness('goose'));
	t.true(isRunnerHarness('acp'));
	t.false(isRunnerHarness('harness'));
});

// An ACP agent that answers one prompt: a message, a tool call it asks
// permission for, the tool's result naming the option it was given, and a
// last message, then the end of the turn.
const FAKE_AGENT = `
import readline from 'node:readline';
const send = message => process.stdout.write(JSON.stringify(message) + '\\n');
const update = u => send({jsonrpc: '2.0', method: 'session/update', params: {sessionId: 's1', update: u}});
let prompt;
readline.createInterface({input: process.stdin}).on('line', line => {
	const m = JSON.parse(line);
	if (m.method === 'initialize') {
		send({id: m.id, result: {protocolVersion: 1, agentCapabilities: {loadSession: true, mcpCapabilities: {http: true}}}});
	} else if (m.method === 'session/new') {
		process.stderr.write('mcp ' + m.params.mcpServers[0].url);
		send({id: m.id, result: {sessionId: 's1'}});
	} else if (m.method === 'session/prompt') {
		prompt = m.id;
		update({sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: {type: 'text', text: m.params.prompt[0].text}});
		update({sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Write file', status: 'pending', rawInput: {path: 'a'}});
		send({id: 100, method: 'session/request_permission', params: {sessionId: 's1', toolCall: {toolCallId: 't1'}, options: [{optionId: 'ok', kind: 'allow_once'}, {optionId: 'no', kind: 'reject_once'}]}});
	} else if (m.id === 100) {
		update({sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed', content: [{type: 'content', content: {type: 'text', text: m.result.outcome.optionId}}]});
		update({sessionUpdate: 'agent_message_chunk', messageId: 'm2', content: {type: 'text', text: 'Done'}});
		send({id: prompt, result: {stopReason: 'end_turn'}});
	}
});
`;

test('an ACP turn runs a prompt, asks a person about a permission and ends with the answer', async t => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'acp-runner-'));
	const agent = path.join(root, 'agent.mjs');
	fs.writeFileSync(agent, FAKE_AGENT);
	const assign = {
		turn_id: 'turn-1',
		task_id: 'task-1',
		agent_id: 'agent-1',
		iteration: 1,
		message: 'Hi',
		session_id: null,
		requested_by: 'person',
		actor: {type: 'user', id: 'person'},
		model: null,
		reasoning_effort: null,
		instructions: null,
		allow_domains: [],
		sandbox: true,
		token: 't',
		mcp_path: '/mcp/clients/c1',
	} as Assign;
	const options = {
		config: {
			api_url: 'http://127.0.0.1:1',
			workspace: 'w',
			client_id: 'c1',
			kind: 'acp',
			token: 'k',
		},
		harness: 'acp',
		root,
		loginFrom: undefined,
		allowDomains: [],
		capacity: 1,
	} as RunnerOptions;
	const relay = {
		url: (task: string) => `http://127.0.0.1:9/relay/${task}`,
	} as unknown as McpRelay;
	const events: TurnEventBody[] = [];
	let started: string | undefined;
	let turn: AcpTurn | undefined;
	const finished = new Promise<{
		status: string;
		response?: string;
		sessionId?: string;
	}>(resolve => {
		turn = new AcpTurn(
			options,
			relay,
			assign,
			{
				started(id) {
					started = id;
				},
				event(body) {
					events.push(body);
				},
				approval(ask: ApprovalAsk) {
					t.is(ask.item_id, 't1');
					t.is(ask.tool_name, 'Write file');
					turn!.decide(ask.request_id, true);
				},
				steered() {},
				finished(status, fields) {
					resolve({status, ...fields});
				},
			},
			['node', agent],
		);
	});
	const result = await finished;
	t.is(result.status, 'completed');
	t.is(result.response, 'Done');
	t.is(result.sessionId, 's1');
	t.is(started, 's1');
	t.true(
		events.some(
			event =>
				event.kind === 'tool.result' && event.output === 'ok' && event.success,
		),
	);
	t.true(events.some(event => event.kind === 'message' && event.text === 'Hi'));
});
