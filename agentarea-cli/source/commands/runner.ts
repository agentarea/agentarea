import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {Readable, pipeline} from 'node:stream';
import {
	spawn,
	spawnSync,
	type ChildProcessWithoutNullStreams,
} from 'node:child_process';

/**
 * Runner: serve a harness client's turns with the Codex or Claude Code CLI on
 * this machine. Registered once with a runner key issued for the client, it
 * holds that key, never a person's session. It keeps one outbound WebSocket to the platform
 * (ADR-0051): turns are assigned over it as they are queued, and what the CLI
 * does streams back as it happens. Codex runs as `codex app-server`, Claude
 * Code in stream-json mode, so a turn can be stopped, steered with a new
 * message, and paused for a person's approval. The CLI keeps its own
 * conversation; the platform keeps the session id, so a restarted runner
 * resumes where the task left off. Each turn comes with a token that acts for
 * the turn's actor until the turn ends; the CLI reaches the client's tools on the
 * platform's MCP endpoint through a relay on this machine that adds it, so the token is never in the
 * CLI's config, its environment or anything its commands can read.
 */

/** Harnesses that speak the Agent Client Protocol, by the command that starts them in it. */
export const ACP_COMMANDS: Record<string, string[]> = {
	opencode: ['opencode', 'acp'],
	gemini: ['gemini', '--acp'],
	qwen: ['qwen', '--acp'],
	goose: ['goose', 'acp'],
	cursor: ['cursor-agent', 'acp'],
};

/** A harness of any other ACP command, the one the runner is started with. */
export const CUSTOM_ACP = 'acp';

export type RunnerHarness = 'codex' | 'claude' | string;

/** The command an ACP harness's turns run. */
export function acpCommand(
	options: Pick<RunnerOptions, 'harness' | 'command'>,
): string[] {
	const command = options.command?.length
		? options.command
		: ACP_COMMANDS[options.harness];
	if (!command) {
		throw new Error(
			`a ${options.harness} runner needs --command, the ACP command its turns run`,
		);
	}

	return command;
}

/** Whether the runner serves this kind of client. */
export function isRunnerHarness(kind: unknown): kind is RunnerHarness {
	return (
		kind === 'codex' ||
		kind === 'claude' ||
		kind === CUSTOM_ACP ||
		(typeof kind === 'string' && kind in ACP_COMMANDS)
	);
}

/** What `agentarea runner register` stores in the runner's root. */
export interface RunnerConfig {
	api_url: string;
	workspace: string;
	client_id: string;
	kind: RunnerHarness;
	/** The client's runner key; it reaches nothing but the client's runner routes. */
	token: string;
}

const CONFIG_FILE = 'runner.json';
const VERSION = 'runner/2';

export interface RunnerOptions {
	config: RunnerConfig;
	harness: RunnerHarness;
	root: string;
	loginFrom: string | undefined;
	/** Hosts every sandboxed turn may reach, beside the client's own. */
	allowDomains: string[];
	/** Turns run at once. */
	capacity: number;
	/** The command an ACP harness runs, when not its usual one; the only one a custom harness has. */
	command?: string[];
	/** Environment variables an ACP harness keeps, e.g. the API key it signs in with. */
	passEnv?: string[];
}

/** A turn as the platform assigns it. */
export interface Assign {
	turn_id: string;
	task_id: string;
	agent_id: string;
	iteration: number;
	message: string;
	session_id: string | null;
	requested_by: string;
	actor: {type: 'user' | 'agent'; id: string};
	model: string | null;
	reasoning_effort: string | null;
	instructions: string | null;
	/** Hosts the client allows the CLI's sandbox, beside `allowDomains`. */
	allow_domains: string[];
	/**
	 * The client's setting. On, every command the CLI runs sees only its task's
	 * folder, nothing of the runner's data or other people's profiles, and the
	 * network only to the allowed hosts; anything beyond that waits for a
	 * person's approval. Off, commands run unconfined. Absent counts as on.
	 */
	sandbox?: boolean;
	/** Acts for the turn's actor on the client's MCP endpoint until the turn ends. */
	token: string;
	/** The client's MCP endpoint, relative to the platform's API. */
	mcp_path: string;
}

const ID_SEGMENT = /^[\w-]{1,64}$/;
const HOST =
	/^(\*\.)?[a-z\d]([a-z\d-]*[a-z\d])?(\.[a-z\d]([a-z\d-]*[a-z\d])?)*$/i;
const CLIENT_MCP_PATH = /^\/mcp\/clients\/[\w-]{1,64}$/;

/** A value from the platform, made safe to put on one log line. */
export function logged(value: unknown): string {
	return String(value).replace(/[\r\n\u2028\u2029]/g, ' ');
}

/** The turn the platform assigned, checked before its ids name folders or URLs. */
export function checkedAssign(frame: Record<string, unknown>): Assign {
	for (const field of ['turn_id', 'task_id', 'agent_id', 'requested_by']) {
		if (typeof frame[field] !== 'string' || !ID_SEGMENT.test(frame[field])) {
			throw new Error(`turn.assign has an invalid ${field}`);
		}
	}

	if (
		typeof frame['mcp_path'] !== 'string' ||
		!CLIENT_MCP_PATH.test(frame['mcp_path'])
	) {
		throw new Error('turn.assign has an invalid mcp_path');
	}

	checkedDomains(frame['allow_domains']);
	return frame as unknown as Assign;
}

/** Hosts for the sandbox's allowlist; anything else would be written into the CLI's config. */
export function checkedDomains(domains: unknown): string[] {
	if (
		!Array.isArray(domains) ||
		!domains.every(domain => typeof domain === 'string' && HOST.test(domain))
	) {
		throw new Error(
			`invalid allowed domains: ${logged(JSON.stringify(domains))}`,
		);
	}

	return domains as string[];
}

/** What a turn reports, as `turn.event` bodies. */
export type TurnEventBody =
	| {
			kind: 'message.delta';
			item_id: string;
			text: string;
			channel?: 'text' | 'thinking';
	  }
	| {kind: 'message'; item_id: string; text: string; model?: string}
	| {
			kind: 'tool.call';
			id: string;
			name: string;
			arguments: Record<string, unknown>;
	  }
	| {kind: 'tool.progress'; id: string; name: string; output: string}
	| {
			kind: 'tool.result';
			id: string;
			name: string;
			output: string;
			success: boolean;
			exit_code?: number | null;
	  };

export interface ApprovalAsk {
	request_id: string;
	item_id: string | null;
	kind: 'command' | 'file_change' | 'tool';
	tool_name: string;
	arguments: Record<string, unknown>;
	reason: string | null;
}

export type FinishStatus = 'completed' | 'failed' | 'interrupted';

/** What a running turn reports to the platform. */
interface TurnSink {
	started(sessionId: string): void;
	event(body: TurnEventBody): void;
	approval(ask: ApprovalAsk): void;
	steered(messageId: string, accepted: boolean): void;
	finished(
		status: FinishStatus,
		fields: {response?: string; error?: string; sessionId?: string},
	): void;
}

/** A running turn, as the platform drives it. */
interface TurnControl {
	steer(messageId: string, text: string): void;
	cancel(): void;
	decide(requestId: string, approved: boolean): void;
}

const PERMISSION_PROFILE = 'agentarea_task';
/** The client's tools on the platform, as the CLI names them. */
const MCP_SERVER_NAME = 'agentarea';

/** What a ChatGPT login brings along on its own: the account's apps, plugins, browser and computer use. */
const ACCOUNT_FEATURES = [
	'apps',
	'plugins',
	'remote_plugin',
	'plugin_discovery_prefetch',
	'tool_suggest',
	'browser_use',
	'browser_use_external',
	'computer_use',
];

/**
 * The CLI's config: only the tools the platform gives it, and under `profile`
 * a permission profile that writes the task folder, never reads the runner's
 * data and reaches only the allowed domains.
 */
export function codexConfig(
	options: RunnerOptions,
	home: string,
	clientDomains: string[],
	sandboxed: boolean,
): string {
	const features = [
		'[features]',
		...ACCOUNT_FEATURES.map(feature => `${feature} = false`),
	];
	if (!sandboxed) {
		return [...features, ''].join('\n');
	}

	const domains = [
		...new Set(checkedDomains([...options.allowDomains, ...clientDomains])),
	];
	const hidden = [
		options.root,
		...(options.loginFrom ? [options.loginFrom] : []),
	].map(dir => path.resolve(dir));
	return [
		`default_permissions = "${PERMISSION_PROFILE}"`,
		'',
		...features,
		'network_proxy = true',
		'',
		`[permissions.${PERMISSION_PROFILE}]`,
		'extends = ":workspace"',
		'',
		`[permissions.${PERMISSION_PROFILE}.filesystem]`,
		...hidden.map(dir => `${JSON.stringify(dir)} = "deny"`),
		// The CLI's sandbox helper and its network proxy's CA live in its home; only
		// a "write" rule reopens a path under a denied one.
		...['tmp', 'proxy'].map(
			dir => `${JSON.stringify(path.join(path.resolve(home), dir))} = "write"`,
		),
		'',
		`[permissions.${PERMISSION_PROFILE}.network]`,
		// Every host goes through the proxy: one off the list waits for a person.
		'enabled = true',
		'mode = "limited"',
		'',
		`[permissions.${PERMISSION_PROFILE}.network.domains]`,
		...domains.map(domain => `${JSON.stringify(domain)} = "allow"`),
		'',
	].join('\n');
}

/**
 * A person's own CLI home on this machine, so one sender never sees another's
 * sessions, and the Codex config written into it.
 */
/** Whether the turn's commands run sandboxed; a platform that does not say keeps them so. */
export function sandboxed(assign: Pick<Assign, 'sandbox'>): boolean {
	return assign.sandbox !== false;
}

function profileHome(
	options: RunnerOptions,
	assign: Pick<Assign, 'requested_by' | 'allow_domains' | 'sandbox'>,
): {home: string; config: string} {
	const userId = assign.requested_by;
	const safe = userId.replace(/[^a-zA-Z0-9_-]/g, '_');
	const home = path.join(options.root, 'profiles', safe, options.harness);
	fs.mkdirSync(home, {recursive: true});
	if (options.harness !== 'codex') {
		return {home, config: ''};
	}

	if (options.loginFrom) {
		const auth = path.join(home, 'auth.json');
		if (!fs.existsSync(auth)) {
			fs.symlinkSync(path.join(options.loginFrom, 'auth.json'), auth);
		}
	}

	const config = codexConfig(
		options,
		home,
		assign.allow_domains,
		sandboxed(assign),
	);
	fs.writeFileSync(path.join(home, 'config.toml'), config);
	return {home, config};
}

/** Where Codex reads the machine's requirements; only they let a person approve a host. */
export const CODEX_REQUIREMENTS_FILE = '/etc/codex/requirements.toml';

/**
 * Whether Codex requirements turn on its managed network proxy. Without it,
 * Codex blocks a host off the allowlist outright and approving the command
 * changes nothing; with it, Codex asks for the host and the answer reaches it.
 */
export function managesNetwork(requirements: string): boolean {
	const table =
		/^\s*\[network_proxy\]\s*$([\s\S]*?)(?=^\s*\[|(?![\s\S]))/m.exec(
			requirements,
		);
	return table !== null && /^\s*enabled\s*=\s*true\s*$/m.test(table[1]!);
}

/** Only what the CLI needs: the runner's own credentials must not reach the commands it runs. */
function cliEnv(
	home: string,
	extra: Record<string, string>,
): NodeJS.ProcessEnv {
	const keep = [
		'PATH',
		'LANG',
		'LC_ALL',
		'TERM',
		'TMPDIR',
		'SSL_CERT_FILE',
		'SSL_CERT_DIR',
	];
	const env: NodeJS.ProcessEnv = {HOME: home, ...extra};
	for (const name of keep) {
		if (process.env[name] !== undefined) {
			env[name] = process.env[name];
		}
	}

	return env;
}

function taskDir(options: RunnerOptions, taskId: string): string {
	const cwd = path.join(options.root, 'tasks', taskId);
	fs.mkdirSync(cwd, {recursive: true});
	return cwd;
}

/** The command a Codex command item ran, as a person would type it. */
function shownCommand(item: Record<string, any>): string {
	const actions = (item['commandActions'] ?? []) as Array<
		Record<string, unknown>
	>;
	const inner = actions
		.map(action => action['command'])
		.filter((command): command is string => typeof command === 'string');
	return inner.length > 0 ? inner.join(' && ') : String(item['command'] ?? '');
}

/**
 * What a `codex app-server` notification adds to the turn. `fileChanges`
 * keeps each file change's paths from its start, since its approval request
 * carries none.
 */
export function codexEvents(
	method: string,
	params: Record<string, any>,
	model: string | null,
	fileChanges: Map<string, unknown>,
): TurnEventBody[] {
	if (method === 'item/agentMessage/delta') {
		return [
			{kind: 'message.delta', item_id: params['itemId'], text: params['delta']},
		];
	}

	if (method === 'item/commandExecution/outputDelta') {
		return [
			{
				kind: 'tool.progress',
				id: params['itemId'],
				name: 'shell',
				output: params['delta'],
			},
		];
	}

	if (method !== 'item/started' && method !== 'item/completed') {
		return [];
	}

	const item = (params['item'] ?? {}) as Record<string, any>;
	const done = method === 'item/completed';
	const id = String(item['id']);
	switch (item['type']) {
		case 'agentMessage': {
			return done
				? [
						{
							kind: 'message',
							item_id: id,
							text: String(item['text'] ?? ''),
							...(model ? {model} : {}),
						},
				  ]
				: [];
		}

		case 'commandExecution': {
			return done
				? [
						{
							kind: 'tool.result',
							id,
							name: 'shell',
							output: String(item['aggregatedOutput'] ?? ''),
							success: item['status'] === 'completed' && item['exitCode'] === 0,
							exit_code:
								typeof item['exitCode'] === 'number' ? item['exitCode'] : null,
						},
				  ]
				: [
						{
							kind: 'tool.call',
							id,
							name: 'shell',
							arguments: {command: shownCommand(item)},
						},
				  ];
		}

		case 'mcpToolCall': {
			const name = `${String(item['server'])}.${String(item['tool'])}`;
			return done
				? [
						{
							kind: 'tool.result',
							id,
							name,
							output: JSON.stringify(item['result'] ?? item['error'] ?? ''),
							success: item['status'] === 'completed',
						},
				  ]
				: [
						{
							kind: 'tool.call',
							id,
							name,
							arguments: (item['arguments'] ?? {}) as Record<string, unknown>,
						},
				  ];
		}

		case 'fileChange': {
			const changes = (item['changes'] ?? []) as Array<Record<string, any>>;
			fileChanges.set(id, changes);
			return done
				? [
						{
							kind: 'tool.result',
							id,
							name: 'apply_patch',
							output: changes
								.map(
									change => `${change['kind']?.type ?? ''} ${change['path']}`,
								)
								.join('\n'),
							success: item['status'] === 'completed',
						},
				  ]
				: [
						{
							kind: 'tool.call',
							id,
							name: 'apply_patch',
							arguments: {
								changes: changes.map(change => ({
									path: change['path'],
									kind: change['kind']?.type,
								})),
							},
						},
				  ];
		}

		default: {
			return [];
		}
	}
}

/** How long a request to `codex app-server` may go unanswered. */
const REQUEST_TIMEOUT_MS = 60_000;
/** How long a stopped turn's CLI may take to stop before the runner stops it itself. */
const CANCEL_GRACE_MS = 10_000;

async function delay(ms: number): Promise<void> {
	return new Promise(resolve => {
		setTimeout(resolve, ms);
	});
}

/** Why a CLI could not start, as a turn's error says it. */
function spawnFailure(command: string, error: NodeJS.ErrnoException): string {
	return error.code === 'ENOENT'
		? `${command} not found on PATH`
		: `${command} could not start: ${error.message}`;
}

/** A newline-delimited JSON-RPC peer over a child's stdio, as `codex app-server` speaks it. */
export class JsonRpcPeer {
	private next = 1;
	private failed: Error | undefined;
	private readonly waiting = new Map<
		number,
		{resolve: (value: any) => void; reject: (error: Error) => void}
	>();

	private readonly child: ChildProcessWithoutNullStreams;
	private readonly timeoutMs: number;
	private readonly name: string;
	/** Tag every message `"jsonrpc": "2.0"`; ACP agents drop one without it, Codex needs none. */
	private readonly tagged: boolean;
	private readonly onNotification: (
		method: string,
		params: Record<string, any>,
	) => void;

	private readonly onRequest: (
		id: number | string,
		method: string,
		params: Record<string, any>,
	) => void;

	constructor(
		child: ChildProcessWithoutNullStreams,
		onNotification: (method: string, params: Record<string, any>) => void,
		onRequest: (
			id: number | string,
			method: string,
			params: Record<string, any>,
		) => void,
		timeoutMs = REQUEST_TIMEOUT_MS,
		name = 'codex app-server',
		tagged = false,
	) {
		this.timeoutMs = timeoutMs;
		this.name = name;
		this.tagged = tagged;
		this.child = child;
		this.onNotification = onNotification;
		this.onRequest = onRequest;
		child.stdin.on('error', (error: Error) => {
			console.error(`[runner] writing to ${this.name}: ${String(error)}`);
		});
		const lines = readline.createInterface({input: child.stdout});
		lines.on('line', line => {
			this.receive(line);
		});
	}

	/** A request; `timeoutMs` 0 waits as long as it takes, as a whole turn does. */
	async request(
		method: string,
		params: unknown,
		timeoutMs = this.timeoutMs,
	): Promise<any> {
		if (this.failed) {
			throw this.failed;
		}

		const id = this.next++;
		return new Promise((resolve, reject) => {
			const timer =
				timeoutMs > 0
					? setTimeout(() => {
							this.waiting.delete(id);
							reject(
								new Error(
									`${this.name} did not answer ${method} in ${timeoutMs} ms`,
								),
							);
					  }, timeoutMs)
					: undefined;
			this.waiting.set(id, {
				resolve(value) {
					clearTimeout(timer);
					resolve(value);
				},
				reject(error) {
					clearTimeout(timer);
					reject(error);
				},
			});
			this.write({id, method, params});
		});
	}

	notify(method: string, params?: unknown): void {
		this.write(params === undefined ? {method} : {method, params});
	}

	respond(id: number | string, result: unknown): void {
		this.write({id, result});
	}

	respondError(id: number | string, message: string): void {
		this.write({id, error: {code: -32601, message}});
	}

	failAll(error: Error): void {
		this.failed = error;
		for (const pending of this.waiting.values()) {
			pending.reject(error);
		}

		this.waiting.clear();
	}

	private write(message: Record<string, unknown>): void {
		const sent = this.tagged ? {jsonrpc: '2.0', ...message} : message;
		this.child.stdin.write(`${JSON.stringify(sent)}\n`);
	}

	private receive(line: string): void {
		let message: Record<string, any>;
		try {
			message = JSON.parse(line);
		} catch {
			console.error(`[runner] ${this.name} said: ${line}`);
			return;
		}

		// A request of the server's own carries a method; its ids overlap ours.
		if (typeof message['method'] === 'string' && 'id' in message) {
			this.onRequest(message['id'], message['method'], message['params'] ?? {});
			return;
		}

		if (typeof message['method'] === 'string') {
			this.onNotification(message['method'], message['params'] ?? {});
			return;
		}

		const pending = this.waiting.get(message['id']);
		if (!pending) {
			return;
		}

		this.waiting.delete(message['id']);
		if (message['error']) {
			pending.reject(
				new Error(String(message['error'].message ?? `${this.name} error`)),
			);
		} else {
			pending.resolve(message['result']);
		}
	}
}

/** One Codex turn on a thread of a shared `codex app-server`. */
class CodexTurn implements TurnControl {
	threadId: string | null = null;
	codexTurnId: string | null = null;
	private readonly pendingSteers: Array<{messageId: string; text: string}> = [];
	private cancelled = false;
	private ended = false;
	private stopTimer: NodeJS.Timeout | undefined;
	private response: string | undefined;
	private error: string | undefined;
	readonly fileChanges = new Map<string, unknown>();
	readonly approvals = new Map<
		string,
		{rpcId: number | string; method: string; params: any}
	>();

	private readonly server: CodexServer;
	readonly assign: Assign;
	readonly sink: TurnSink;

	constructor(server: CodexServer, assign: Assign, sink: TurnSink) {
		this.server = server;
		this.assign = assign;
		this.sink = sink;
		server.turns.add(this);
	}

	steer(messageId: string, text: string): void {
		if (this.codexTurnId === null) {
			this.pendingSteers.push({messageId, text});
			return;
		}

		void this.sendSteer(messageId, text);
	}

	cancel(): void {
		this.cancelled = true;
		if (this.codexTurnId !== null && this.threadId !== null) {
			this.server.peer
				.request('turn/interrupt', {
					threadId: this.threadId,
					turnId: this.codexTurnId,
				})
				.catch((error: unknown) => {
					console.error(`[runner] interrupt: ${String(error)}`);
				});
		}

		this.stopTimer ??= setTimeout(() => {
			if (!this.ended) {
				console.error(
					`[runner] codex did not stop turn ${logged(
						this.assign.turn_id,
					)}; ending it here`,
				);
				this.end('interrupted', {});
			}
		}, CANCEL_GRACE_MS);
	}

	decide(requestId: string, approved: boolean): void {
		const pending = this.approvals.get(requestId);
		if (!pending) {
			return;
		}

		this.approvals.delete(requestId);
		if (pending.method === 'item/permissions/requestApproval') {
			this.server.peer.respond(pending.rpcId, {
				permissions: approved ? pending.params['permissions'] : {},
				scope: 'turn',
			});
			return;
		}

		if (pending.method === 'mcpServer/elicitation/request') {
			this.server.peer.respond(pending.rpcId, {
				action: approved ? 'accept' : 'decline',
				content: approved ? {} : null,
				_meta: null,
			});
			return;
		}

		this.server.peer.respond(pending.rpcId, {
			decision: approved ? 'accept' : 'decline',
		});
	}

	async start(): Promise<void> {
		const {assign} = this;
		const cwd = taskDir(this.server.options, assign.task_id);
		const unconfined = !sandboxed(assign);
		const threadParams = {
			cwd,
			approvalPolicy: unconfined ? 'never' : 'on-request',
			...(unconfined ? {sandbox: 'danger-full-access'} : {}),
			...(assign.instructions
				? {developerInstructions: assign.instructions}
				: {}),
			config: {
				mcp_servers: {
					[MCP_SERVER_NAME]: {url: this.server.relay.url(assign.task_id)},
				},
			},
		};
		const thread = assign.session_id
			? await this.server.peer.request('thread/resume', {
					threadId: assign.session_id,
					excludeTurns: true,
					...threadParams,
			  })
			: await this.server.peer.request('thread/start', {
					...threadParams,
					...(assign.model ? {model: assign.model} : {}),
			  });
		this.threadId = String(thread.thread.id);
		if (this.ended) {
			return;
		}

		this.server.byThread.set(this.threadId, this);
		this.sink.started(this.threadId);
		const started = await this.server.peer.request('turn/start', {
			threadId: this.threadId,
			input: [{type: 'text', text: assign.message, text_elements: []}],
			...(assign.model ? {model: assign.model} : {}),
			...(assign.reasoning_effort ? {effort: assign.reasoning_effort} : {}),
		});
		this.codexTurnId = String(started.turn.id);
		if (this.cancelled) {
			this.cancel();
		}

		if (this.ended) {
			return;
		}

		for (const {messageId, text} of this.pendingSteers.splice(0)) {
			void this.sendSteer(messageId, text);
		}
	}

	onNotification(method: string, params: Record<string, any>): void {
		for (const body of codexEvents(
			method,
			params,
			this.assign.model,
			this.fileChanges,
		)) {
			if (body.kind === 'message') {
				const phase = params['item']?.['phase'];
				if (phase === 'final_answer' || phase === null || phase === undefined) {
					this.response = body.text;
				}
			}

			this.sink.event(body);
		}

		if (method === 'error' && params['willRetry'] === false) {
			this.error = String(params['error']?.message ?? 'codex error');
		}

		if (method === 'turn/completed') {
			const turn = params['turn'] ?? {};
			const status = String(turn['status']);
			if (status === 'completed') {
				this.end('completed', {response: this.response ?? ''});
			} else if (status === 'interrupted') {
				this.end('interrupted', {});
			} else {
				this.end('failed', {
					error: String(turn['error']?.message ?? this.error ?? 'turn failed'),
				});
			}
		}
	}

	onRequest(
		id: number | string,
		method: string,
		params: Record<string, any>,
	): void {
		const requestId = String(id);
		const itemId =
			typeof params['itemId'] === 'string' ? params['itemId'] : null;
		if (
			method === 'item/commandExecution/requestApproval' &&
			params['networkApprovalContext']
		) {
			// A command reached a host off the allowlist; allowing it lets this request through.
			const network = params['networkApprovalContext'] as {
				host: string;
				protocol: string;
			};
			this.approvals.set(requestId, {rpcId: id, method, params});
			this.sink.approval({
				request_id: requestId,
				item_id: null,
				kind: 'command',
				tool_name: 'network',
				arguments: {host: network.host, protocol: network.protocol},
				reason: params['reason'] ?? null,
			});
			return;
		}

		if (method === 'item/commandExecution/requestApproval') {
			this.approvals.set(requestId, {rpcId: id, method, params});
			this.sink.approval({
				request_id: requestId,
				item_id: itemId,
				kind: 'command',
				tool_name: 'shell',
				arguments: {
					command: shownCommand(params),
					cwd: params['cwd'] ?? null,
				},
				reason: params['reason'] ?? null,
			});
			return;
		}

		if (method === 'item/fileChange/requestApproval') {
			this.approvals.set(requestId, {rpcId: id, method, params});
			this.sink.approval({
				request_id: requestId,
				item_id: itemId,
				kind: 'file_change',
				tool_name: 'apply_patch',
				arguments: {changes: itemId ? this.fileChanges.get(itemId) ?? [] : []},
				reason: params['reason'] ?? null,
			});
			return;
		}

		if (method === 'item/permissions/requestApproval') {
			this.approvals.set(requestId, {rpcId: id, method, params});
			this.sink.approval({
				request_id: requestId,
				item_id: itemId,
				kind: 'command',
				tool_name: 'permissions',
				arguments: {permissions: params['permissions'] ?? {}},
				reason: params['reason'] ?? null,
			});
			return;
		}

		if (method === 'mcpServer/elicitation/request') {
			this.approvals.set(requestId, {rpcId: id, method, params});
			this.sink.approval({
				request_id: requestId,
				item_id: null,
				kind: 'tool',
				tool_name: `${String(params['serverName'])} tool`,
				arguments: {
					message: params['message'] ?? null,
					...(params['url'] ? {url: params['url']} : {}),
				},
				reason:
					typeof params['message'] === 'string' ? params['message'] : null,
			});
			return;
		}

		this.server.peer.respondError(id, `the runner does not answer ${method}`);
	}

	end(status: FinishStatus, fields: {response?: string; error?: string}): void {
		if (this.ended) {
			return;
		}

		this.ended = true;
		clearTimeout(this.stopTimer);
		if (
			this.threadId !== null &&
			this.server.byThread.get(this.threadId) === this
		) {
			this.server.byThread.delete(this.threadId);
		}

		this.server.turns.delete(this);
		if (this.server.retired && this.server.turns.size === 0) {
			this.server.stop();
		}

		this.sink.finished(status, {
			...fields,
			sessionId: this.threadId ?? undefined,
		});
	}

	private async sendSteer(messageId: string, text: string): Promise<void> {
		try {
			await this.server.peer.request('turn/steer', {
				threadId: this.threadId,
				expectedTurnId: this.codexTurnId,
				input: [{type: 'text', text, text_elements: []}],
			});
		} catch (error) {
			console.error(`[runner] steer refused: ${String(error)}`);
			this.sink.steered(messageId, false);
			return;
		}

		this.sink.steered(messageId, true);
	}
}

/**
 * The turn of `turns` a Codex notification belongs to: the one with its thread
 * and turn id. A thread resumed for a new turn while its earlier, stopped turn
 * winds down hears both; `latest` is the thread's newest turn, which takes
 * what carries no turn id and what arrives before its own turn id is known.
 */
export function notifiedTurn<
	T extends {threadId: string | null; codexTurnId: string | null},
>(
	turns: Iterable<T>,
	latest: T | undefined,
	params: Record<string, any>,
): T | undefined {
	const threadId: unknown = params['threadId'];
	if (typeof threadId !== 'string') {
		return undefined;
	}

	const turnId: unknown = params['turnId'] ?? params['turn']?.['id'];
	if (typeof turnId !== 'string') {
		return latest;
	}

	for (const turn of turns) {
		if (turn.threadId === threadId && turn.codexTurnId === turnId) {
			return turn;
		}
	}

	return latest?.codexTurnId === null ? latest : undefined;
}

/**
 * One `codex app-server` for one person's CLI home, shared by their tasks'
 * turns. It keeps the config it started with: a thread it loaded keeps the
 * network allowlist of that config, so a changed config retires the server
 * and the next turn starts a new one.
 */
class CodexServer {
	readonly byThread = new Map<string, CodexTurn>();
	readonly turns = new Set<CodexTurn>();
	/** Takes no more turns; stops once its last one ends. */
	retired = false;
	readonly peer: JsonRpcPeer;
	private readonly child: ChildProcessWithoutNullStreams;
	private stderr = '';
	private closed = false;
	readonly ready: Promise<void>;

	readonly options: RunnerOptions;
	readonly relay: McpRelay;
	readonly config: string;
	private readonly onExit: () => void;

	constructor(
		options: RunnerOptions,
		relay: McpRelay,
		home: string,
		config: string,
		onExit: () => void,
	) {
		this.options = options;
		this.relay = relay;
		this.config = config;
		this.onExit = onExit;
		this.child = spawn('codex', ['app-server'], {
			cwd: home,
			env: cliEnv(home, {CODEX_HOME: home}),
			stdio: ['pipe', 'pipe', 'pipe'],
		});
		this.child.stderr.on('data', (chunk: Buffer) => {
			this.stderr = (this.stderr + chunk.toString()).slice(-4000);
		});
		this.peer = new JsonRpcPeer(
			this.child,
			(method, params) => {
				this.turnOf(params)?.onNotification(method, params);
			},
			(id, method, params) => {
				const turn = this.turnOf(params);
				if (turn) {
					turn.onRequest(id, method, params);
				} else {
					this.peer.respondError(
						id,
						`no turn of this runner asked for ${method}`,
					);
				}
			},
		);
		this.child.on('close', code => {
			this.close(
				this.stderr.trim() || `codex app-server exited with ${String(code)}`,
			);
		});
		this.child.on('error', (error: NodeJS.ErrnoException) => {
			console.error(`[runner] codex app-server: ${String(error)}`);
			this.close(spawnFailure('codex', error));
		});
		this.ready = this.initialize();
	}

	/** The turn a notification or request of the server is about; one of an earlier turn on the thread is not the current one's. */
	private turnOf(params: Record<string, any>): CodexTurn | undefined {
		const turn = notifiedTurn(
			this.turns,
			typeof params['threadId'] === 'string'
				? this.byThread.get(params['threadId'])
				: undefined,
			params,
		);
		if (!turn && typeof params['threadId'] === 'string') {
			console.debug(
				`[runner] codex said something of a turn this runner no longer runs`,
			);
		}

		return turn;
	}

	private close(message: string): void {
		if (this.closed) {
			return;
		}

		this.closed = true;
		const error = new Error(message);
		this.peer.failAll(error);
		for (const turn of [...this.turns]) {
			turn.end('failed', {error: error.message});
		}

		this.onExit();
	}

	/** Retire the server for one with a new config; it stops when its turns end. */
	retire(): void {
		this.retired = true;
		if (this.turns.size === 0) {
			this.stop();
		}
	}

	stop(): void {
		this.child.kill();
	}

	private async initialize(): Promise<void> {
		await this.peer.request('initialize', {
			clientInfo: {
				name: 'agentarea_runner',
				title: 'AgentArea runner',
				version: VERSION,
			},
			capabilities: {
				experimentalApi: false,
				requestAttestation: false,
				optOutNotificationMethods: [
					'account/rateLimits/updated',
					'turn/moderationMetadata',
					'remoteControl/status/changed',
					'mcpServer/startupStatus/updated',
				],
			},
		});
		this.peer.notify('initialized');
	}
}

/** One Claude Code process per turn, in stream-json mode, resuming the task's session. */
class ClaudeTurn implements TurnControl {
	private readonly child: ChildProcessWithoutNullStreams;
	private ended = false;
	private interrupting = false;
	private stderr = '';
	private sessionId: string | undefined;
	private messageId = '';
	private readonly approvals = new Map<string, Record<string, any>>();
	/** Settles once the process is gone. */
	readonly exited: Promise<void>;

	readonly assign: Assign;
	private readonly sink: TurnSink;

	constructor(
		options: RunnerOptions,
		relay: McpRelay,
		assign: Assign,
		sink: TurnSink,
	) {
		this.assign = assign;
		this.sink = sink;
		const {home} = profileHome(options, assign);
		const args = [
			'-p',
			'--input-format',
			'stream-json',
			'--output-format',
			'stream-json',
			'--verbose',
			'--include-partial-messages',
			'--permission-prompt-tool',
			'stdio',
			'--permission-mode',
			sandboxed(assign) ? 'acceptEdits' : 'bypassPermissions',
			'--mcp-config',
			privateFile(
				home,
				`mcp-${assign.task_id}.json`,
				JSON.stringify({
					mcpServers: {
						[MCP_SERVER_NAME]: {type: 'http', url: relay.url(assign.task_id)},
					},
				}),
			),
			'--settings',
			privateFile(
				home,
				'settings.json',
				JSON.stringify(claudeSettings(options)),
			),
			// Each call is judged by the platform for the turn's actor.
			'--allowedTools',
			`mcp__${MCP_SERVER_NAME}`,
		];
		if (assign.model) {
			args.push('--model', assign.model);
		}

		if (assign.reasoning_effort) {
			args.push('--effort', assign.reasoning_effort);
		}

		if (assign.instructions) {
			args.push('--append-system-prompt', assign.instructions);
		}

		if (assign.session_id) {
			args.push('--resume', assign.session_id);
		}

		this.child = spawn('claude', args, {
			cwd: taskDir(options, assign.task_id),
			env: cliEnv(home, {CLAUDE_CONFIG_DIR: home}),
			stdio: ['pipe', 'pipe', 'pipe'],
		});
		this.child.stderr.on('data', (chunk: Buffer) => {
			this.stderr = (this.stderr + chunk.toString()).slice(-4000);
		});
		readline.createInterface({input: this.child.stdout}).on('line', line => {
			this.receive(line);
		});
		this.child.stdin.on('error', (error: Error) => {
			console.error(`[runner] writing to claude: ${String(error)}`);
		});
		this.exited = new Promise(resolve => {
			this.child.on('close', code => {
				resolve();
				if (this.interrupting) {
					this.end('interrupted', {});
					return;
				}

				this.end('failed', {
					error: this.stderr.trim() || `claude exited with ${String(code)}`,
				});
			});
			this.child.on('error', (error: NodeJS.ErrnoException) => {
				console.error(`[runner] claude: ${String(error)}`);
				resolve();
				this.end('failed', {error: spawnFailure('claude', error)});
			});
		});
		this.write({
			type: 'user',
			message: {role: 'user', content: assign.message},
			parent_tool_use_id: null,
		});
	}

	steer(messageId: string, _text: string): void {
		// Claude answers a message written mid-turn as an exchange of its own, after
		// this turn's result; refused, the platform sends it as the next turn.
		this.sink.steered(messageId, false);
	}

	cancel(): void {
		this.interrupting = true;
		this.write({
			type: 'control_request',
			request_id: `interrupt-${Date.now()}`,
			request: {subtype: 'interrupt'},
		});
		setTimeout(() => {
			if (this.running) {
				console.error(
					`[runner] claude did not stop turn ${logged(
						this.assign.turn_id,
					)}; killing it`,
				);
				this.child.kill('SIGKILL');
			}
		}, CANCEL_GRACE_MS);
	}

	/** Wait for the process of an earlier turn to exit, killing it after `graceMs`. */
	async stop(graceMs: number): Promise<void> {
		await Promise.race([this.exited, delay(graceMs)]);
		if (this.running) {
			console.error(
				`[runner] claude of turn ${logged(
					this.assign.turn_id,
				)} still running; killing it`,
			);
			this.child.kill('SIGKILL');
			await Promise.race([this.exited, delay(graceMs)]);
		}
	}

	private get running(): boolean {
		return this.child.exitCode === null && this.child.signalCode === null;
	}

	decide(requestId: string, approved: boolean): void {
		const request = this.approvals.get(requestId);
		if (!request) {
			return;
		}

		this.approvals.delete(requestId);
		this.write({
			type: 'control_response',
			response: {
				subtype: 'success',
				request_id: requestId,
				response: approved
					? {behavior: 'allow', updatedInput: request['input'] ?? {}}
					: {behavior: 'deny', message: 'A person denied this.'},
			},
		});
	}

	private write(message: unknown): void {
		if (!this.child.stdin.writable) {
			return;
		}

		this.child.stdin.write(`${JSON.stringify(message)}\n`);
	}

	private receive(line: string): void {
		let event: Record<string, any>;
		try {
			event = JSON.parse(line);
		} catch {
			return;
		}

		for (const body of claudeEvents(event, this)) {
			this.sink.event(body);
		}

		if (event['type'] === 'system' && event['subtype'] === 'init') {
			this.sessionId = String(event['session_id']);
			this.sink.started(this.sessionId);
		} else if (
			event['type'] === 'control_request' &&
			event['request']?.subtype === 'can_use_tool'
		) {
			const request = event['request'];
			this.approvals.set(String(event['request_id']), request);
			this.sink.approval({
				request_id: String(event['request_id']),
				item_id: request['tool_use_id'] ?? null,
				kind: 'tool',
				tool_name: String(request['tool_name']),
				arguments: (request['input'] ?? {}) as Record<string, unknown>,
				reason: request['decision_reason'] ?? null,
			});
		} else if (event['type'] === 'control_request') {
			this.write({
				type: 'control_response',
				response: {
					subtype: 'error',
					request_id: event['request_id'],
					error: `the runner does not answer ${String(
						event['request']?.subtype,
					)}`,
				},
			});
		} else if (event['type'] === 'result') {
			this.sessionId = String(event['session_id'] ?? this.sessionId);
			if (!event['is_error']) {
				this.end('completed', {response: String(event['result'] ?? '')});
			} else if (this.interrupting) {
				this.end('interrupted', {});
			} else {
				this.end('failed', {error: String(event['result'] ?? 'claude failed')});
			}

			this.child.stdin.end();
		}
	}

	/** The message the deltas belong to, from the stream's `message_start`. */
	currentMessage(id?: string): string {
		if (id) {
			this.messageId = id;
		}

		return this.messageId;
	}

	private end(
		status: FinishStatus,
		fields: {response?: string; error?: string},
	): void {
		if (this.ended) {
			return;
		}

		this.ended = true;
		this.sink.finished(status, {...fields, sessionId: this.sessionId});
	}
}

/** What a Claude Code stream-json line adds to the turn. */
export function claudeEvents(
	event: Record<string, any>,
	stream: {currentMessage(id?: string): string},
): TurnEventBody[] {
	if (event['type'] === 'stream_event') {
		const inner = event['event'] ?? {};
		if (inner['type'] === 'message_start') {
			stream.currentMessage(inner['message']?.id);
			return [];
		}

		const delta = inner['delta'] ?? {};
		if (
			inner['type'] === 'content_block_delta' &&
			delta['type'] === 'text_delta'
		) {
			return [
				{
					kind: 'message.delta',
					item_id: stream.currentMessage(),
					text: delta['text'],
				},
			];
		}

		return [];
	}

	if (event['type'] === 'assistant') {
		const message = event['message'] ?? {};
		return ((message['content'] ?? []) as Array<Record<string, any>>).flatMap(
			(block): TurnEventBody[] => {
				if (block['type'] === 'text' && block['text']) {
					return [
						{
							kind: 'message',
							item_id: String(message['id']),
							text: block['text'],
							...(message['model'] ? {model: message['model']} : {}),
						},
					];
				}

				if (block['type'] === 'tool_use') {
					return [
						{
							kind: 'tool.call',
							id: block['id'],
							name: block['name'],
							arguments: block['input'] ?? {},
						},
					];
				}

				return [];
			},
		);
	}

	if (event['type'] === 'user') {
		return (
			(event['message']?.content ?? []) as Array<Record<string, any>>
		).flatMap((block): TurnEventBody[] => {
			if (block['type'] !== 'tool_result') {
				return [];
			}

			const content = Array.isArray(block['content'])
				? block['content'].map((c: any) => c.text ?? '').join('\n')
				: String(block['content'] ?? '');
			return [
				{
					kind: 'tool.result',
					id: block['tool_use_id'],
					name: 'tool',
					output: content,
					success: !block['is_error'],
				},
			];
		});
	}

	return [];
}

/** Check a client's runner key with the platform and keep it in `root`. */
export async function registerRunner(
	apiUrl: string,
	key: string,
	root: string,
): Promise<RunnerConfig> {
	const res = await fetch(apiRoute(apiUrl, '/v1/runner/whoami'), {
		headers: {Authorization: `Bearer ${key}`},
	});
	if (!res.ok) {
		throw new Error(
			`the platform refused the key: HTTP ${res.status} ${logged(
				await res.text(),
			)}`,
		);
	}

	const identity = (await res.json()) as {
		client_id: string;
		workspace: string;
		kind: RunnerHarness;
	};
	if (
		!ID_SEGMENT.test(String(identity.client_id)) ||
		!ID_SEGMENT.test(String(identity.workspace)) ||
		!isRunnerHarness(identity.kind)
	) {
		throw new Error(
			`the platform answered an unexpected identity: ${logged(
				JSON.stringify(identity),
			)}`,
		);
	}

	const config: RunnerConfig = {
		api_url: apiUrl,
		workspace: identity.workspace,
		client_id: identity.client_id,
		kind: identity.kind,
		token: key,
	};
	fs.mkdirSync(root, {recursive: true});
	const file = path.join(root, CONFIG_FILE);
	fs.writeFileSync(file, JSON.stringify(config, null, 2), {mode: 0o600});
	fs.chmodSync(file, 0o600);
	return config;
}

export function loadRunnerConfig(root: string): RunnerConfig {
	const file = path.join(root, CONFIG_FILE);
	if (!fs.existsSync(file)) {
		throw new Error(
			`${file} not found; run \`agentarea runner register --api-url <url> --key <key>\` first`,
		);
	}

	return JSON.parse(fs.readFileSync(file, 'utf8')) as RunnerConfig;
}

function runnerUrl(options: RunnerOptions, route: string): string {
	return apiRoute(options.config.api_url, `/v1/runner/${route}`);
}

/** A path on the platform's API; refuses one that would leave its origin. */
export function apiRoute(apiUrl: string, pathname: string): string {
	const base = new URL(apiUrl);
	const url = new URL(base.pathname.replace(/\/$/, '') + pathname, base);
	if (url.origin !== base.origin) {
		throw new Error(`${logged(pathname)} leaves the platform's API`);
	}

	return url.toString();
}

/** The runner's socket URL: the API's, over ws(s). */
export function socketUrl(config: RunnerConfig): string {
	const url = new URL(`${config.api_url}/v1/runner/connect`);
	url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
	return url.toString();
}

/** Folders a CLI fills with tooling rather than results. */
const SKIPPED_DIRS = new Set(['node_modules', '__pycache__']);
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

function taskFiles(dir: string, base = ''): string[] {
	return fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
		if (entry.name.startsWith('.') || SKIPPED_DIRS.has(entry.name)) {
			return [];
		}

		const rel = base ? `${base}/${entry.name}` : entry.name;
		if (entry.isDirectory()) {
			return taskFiles(path.join(dir, entry.name), rel);
		}

		return entry.isFile() ? [rel] : [];
	});
}

/** Copy the task folder up, so the platform opens what the CLI made. */
export async function uploadTaskFiles(
	options: RunnerOptions,
	taskId: string,
	cwd: string,
): Promise<void> {
	for (const rel of taskFiles(cwd)) {
		const body = fs.readFileSync(path.join(cwd, rel));
		if (body.length > MAX_UPLOAD_BYTES) {
			console.error(
				`[runner] ${rel}: larger than ${MAX_UPLOAD_BYTES} bytes, not uploaded`,
			);
			continue;
		}

		const encoded = rel.split('/').map(encodeURIComponent).join('/');
		const res = await fetch(
			runnerUrl(
				options,
				`tasks/${encodeURIComponent(taskId)}/files/${encoded}`,
			),
			{
				method: 'PUT',
				headers: {
					Authorization: `Bearer ${options.config.token}`,
					'Content-Type': 'application/octet-stream',
				},
				body,
			},
		);
		if (!res.ok) {
			console.error(
				`[runner] upload ${rel}: HTTP ${res.status} ${logged(
					await res.text(),
				)}`,
			);
		}
	}
}

export interface RunnerReport {
	models: Array<{
		name: string;
		reasoning_levels: string[];
		default_reasoning: string | null;
	}>;
	default_model: string | null;
}

/** The models the signed-in CLI offers, from Codex's own model cache in its login home. */
export function codexRunnerReport(
	loginFrom: string | undefined,
): RunnerReport | undefined {
	if (!loginFrom) {
		return undefined;
	}

	const cache = path.join(loginFrom, 'models_cache.json');
	if (!fs.existsSync(cache)) {
		return undefined;
	}

	const parsed = JSON.parse(fs.readFileSync(cache, 'utf8')) as
		| {models?: unknown[]}
		| unknown[];
	const raw = (Array.isArray(parsed) ? parsed : parsed.models ?? []) as Array<
		Record<string, any>
	>;
	const models = raw
		.filter(
			model =>
				model['visibility'] === 'list' && typeof model['slug'] === 'string',
		)
		.map(model => ({
			name: String(model['slug']),
			reasoning_levels: (model['supported_reasoning_levels'] ?? [])
				.map((level: Record<string, unknown>) => level['effort'])
				.filter(
					(effort: unknown): effort is string => typeof effort === 'string',
				),
			default_reasoning:
				typeof model['default_reasoning_level'] === 'string'
					? model['default_reasoning_level']
					: null,
		}));
	return {models, default_model: models[0]?.name ?? null};
}

/** What a turn's tool call left unanswered when the turn stopped. */
const STOPPED_TOOL_OUTPUT = 'Stopped before it finished.';

/** Request headers a streamable-HTTP MCP exchange carries through the relay. */
const RELAYED_REQUEST_HEADERS = [
	'content-type',
	'accept',
	'mcp-session-id',
	'mcp-protocol-version',
	'last-event-id',
];
const RELAYED_RESPONSE_HEADERS = [
	'content-type',
	'mcp-session-id',
	'cache-control',
];

/** The messages and tool calls of one ACP turn, as its updates arrive. */
export class AcpStream {
	private messageId: string | undefined;
	private text = '';
	private count = 0;
	private last = '';
	private readonly toolNames = new Map<string, string>();
	private readonly prefix: string;

	constructor(prefix: string) {
		this.prefix = prefix;
	}

	/** What the agent said last, the turn's answer. */
	get response(): string {
		return this.last;
	}

	/** The message under way, as one event, once something else begins. */
	flush(): TurnEventBody[] {
		if (!this.messageId || !this.text) {
			this.messageId = undefined;
			return [];
		}

		const done: TurnEventBody = {
			kind: 'message',
			item_id: this.messageId,
			text: this.text,
		};
		this.last = this.text;
		this.messageId = undefined;
		this.text = '';
		return [done];
	}

	chunk(id: string | undefined, text: string): TurnEventBody[] {
		const flushed =
			this.messageId && id && id !== this.messageId ? this.flush() : [];
		this.messageId ??= id ?? `${this.prefix}-m${++this.count}`;
		this.text += text;
		return [...flushed, {kind: 'message.delta', item_id: this.messageId, text}];
	}

	nameTool(id: string, name: string): string {
		this.toolNames.set(id, name);
		return name;
	}

	toolName(id: string, fallback: unknown): string {
		return this.toolNames.get(id) ?? String(fallback ?? 'tool');
	}
}

/** The text of an ACP tool call's content blocks, or its raw output. */
function acpToolOutput(update: Record<string, any>): string {
	const parts = ((update['content'] ?? []) as Array<Record<string, any>>)
		.map(block => {
			if (block['type'] === 'content' && block['content']?.type === 'text') {
				return String(block['content'].text);
			}

			if (block['type'] === 'diff') {
				return `${String(block['path'] ?? '')}\n${String(
					block['newText'] ?? '',
				)}`;
			}

			return '';
		})
		.filter(Boolean);
	if (parts.length > 0) {
		return parts.join('\n');
	}

	return update['rawOutput'] === undefined || update['rawOutput'] === null
		? ''
		: JSON.stringify(update['rawOutput']);
}

/** What an ACP `session/update` adds to the turn. */
export function acpEvents(
	update: Record<string, any>,
	stream: AcpStream,
): TurnEventBody[] {
	const kind = update['sessionUpdate'];
	if (kind === 'agent_message_chunk') {
		const content = update['content'] ?? {};
		return content['type'] === 'text' && content['text']
			? stream.chunk(update['messageId'] ?? undefined, String(content['text']))
			: [];
	}

	if (kind === 'agent_thought_chunk') {
		const content = update['content'] ?? {};
		return content['type'] === 'text' && content['text']
			? [
					{
						kind: 'message.delta',
						item_id: `${String(update['messageId'] ?? 'thought')}-thinking`,
						text: String(content['text']),
						channel: 'thinking',
					},
			  ]
			: [];
	}

	if (kind === 'tool_call') {
		const id = String(update['toolCallId']);
		const name = stream.nameTool(
			id,
			String(update['title'] ?? update['name'] ?? update['kind'] ?? 'tool'),
		);
		const events: TurnEventBody[] = [
			...stream.flush(),
			{
				kind: 'tool.call',
				id,
				name,
				arguments: (update['rawInput'] ?? {}) as Record<string, unknown>,
			},
		];
		if (update['status'] === 'completed' || update['status'] === 'failed') {
			events.push({
				kind: 'tool.result',
				id,
				name,
				output: acpToolOutput(update),
				success: update['status'] === 'completed',
			});
		}

		return events;
	}

	if (kind === 'tool_call_update') {
		const id = String(update['toolCallId']);
		const name = stream.toolName(id, update['title']);
		const output = acpToolOutput(update);
		if (update['status'] === 'completed' || update['status'] === 'failed') {
			return [
				{
					kind: 'tool.result',
					id,
					name,
					output,
					success: update['status'] === 'completed',
				},
			];
		}

		return output ? [{kind: 'tool.progress', id, name, output}] : [];
	}

	return [];
}

/** An ACP harness's process, with the machine's own sign-in and the variables it keeps. */
function spawnAcp(
	options: Pick<RunnerOptions, 'passEnv'>,
	command: string[],
	cwd: string,
): ChildProcessWithoutNullStreams {
	const keep: Record<string, string> = {};
	for (const name of options.passEnv ?? []) {
		const value = process.env[name];
		if (value !== undefined) {
			keep[name] = value;
		}
	}

	return spawn(command[0]!, command.slice(1), {
		cwd,
		// The machine's own sign-in to the CLI lives in its home.
		env: cliEnv(os.homedir(), keep),
		stdio: ['pipe', 'pipe', 'pipe'],
	});
}

/**
 * The models an ACP harness offers, from a session opened for the asking, so
 * the client's page can pick the one its turns use.
 */
export async function acpRunnerReport(
	options: RunnerOptions,
): Promise<RunnerReport | undefined> {
	const command = acpCommand(options);
	const cwd = path.join(options.root, 'models');
	fs.mkdirSync(cwd, {recursive: true});
	const child = spawnAcp(options, command, cwd);
	const peer = new JsonRpcPeer(
		child,
		() => {},
		(id, method) => {
			peer.respondError(id, `the runner does not answer ${method}`);
		},
		REQUEST_TIMEOUT_MS,
		command[0] ?? 'acp',
		true,
	);
	child.on('error', (error: Error) => {
		peer.failAll(error);
	});
	try {
		await peer.request('initialize', {
			protocolVersion: 1,
			clientCapabilities: {
				fs: {readTextFile: false, writeTextFile: false},
				terminal: false,
			},
			clientInfo: {name: 'agentarea-runner', version: VERSION},
		});
		const session = await peer.request('session/new', {cwd, mcpServers: []});
		const options = (session?.configOptions ?? []) as Array<
			Record<string, any>
		>;
		const models = acpModels(options);
		if (models.length === 0) {
			return undefined;
		}

		const current = options.find(option => option['category'] === 'model')?.[
			'currentValue'
		];
		return {
			models: models.map(name => ({
				name,
				reasoning_levels: [],
				default_reasoning: null,
			})),
			default_model: typeof current === 'string' ? current : null,
		};
	} finally {
		child.kill('SIGTERM');
	}
}

/** The id of a session's model option, the way OpenCode offers its models. */
export function acpModelOption(
	configOptions: Array<Record<string, any>>,
): string | undefined {
	const option = configOptions.find(
		candidate => candidate['category'] === 'model',
	);
	return option ? String(option['id']) : undefined;
}

/** The models a session offers, by the value that picks one. */
export function acpModels(configOptions: Array<Record<string, any>>): string[] {
	const option = configOptions.find(
		candidate => candidate['category'] === 'model',
	);
	return ((option?.['options'] ?? []) as Array<Record<string, any>>).map(
		choice => String(choice['value']),
	);
}

/** The option that answers a permission request: allow once, or reject once. */
export function acpPermissionOption(
	options: Array<Record<string, any>>,
	approved: boolean,
): string | undefined {
	const wanted = approved
		? ['allow_once', 'allow_always']
		: ['reject_once', 'reject_always'];
	for (const kind of wanted) {
		const option = options.find(candidate => candidate['kind'] === kind);
		if (option) {
			return String(option['optionId']);
		}
	}

	return undefined;
}

/**
 * One turn of a harness that speaks the Agent Client Protocol (OpenCode,
 * Gemini CLI, Goose, Qwen Code, Cursor, or a command of the runner's own),
 * one process per turn. The task's session carries on through `session/load`
 * when the agent can load one. A sandboxed turn asks a person about every
 * permission the agent asks for; an unconfined one allows them.
 */
export class AcpTurn implements TurnControl {
	private readonly child: ChildProcessWithoutNullStreams;
	private readonly peer: JsonRpcPeer;
	private readonly stream: AcpStream;
	private readonly permissions = new Map<
		string,
		{id: number | string; options: Array<Record<string, any>>}
	>();

	private sessionId: string | undefined;
	private replaying = false;
	private interrupting = false;
	private ended = false;
	private stderr = '';
	/** Settles once the process is gone. */
	readonly exited: Promise<void>;

	readonly assign: Assign;
	private readonly sink: TurnSink;
	private readonly label: string;
	private readonly options: RunnerOptions;

	constructor(
		options: RunnerOptions,
		relay: McpRelay,
		assign: Assign,
		sink: TurnSink,
		command: string[],
	) {
		this.options = options;
		this.assign = assign;
		this.sink = sink;
		this.label = command[0] ?? 'acp';
		this.stream = new AcpStream(assign.turn_id);
		this.child = spawnAcp(options, command, taskDir(options, assign.task_id));
		this.child.stderr.on('data', (chunk: Buffer) => {
			this.stderr = (this.stderr + chunk.toString()).slice(-4000);
		});
		this.peer = new JsonRpcPeer(
			this.child,
			(method, params) => {
				this.notified(method, params);
			},
			(id, method, params) => {
				this.requested(id, method, params);
			},
			REQUEST_TIMEOUT_MS,
			this.label,
			true,
		);
		this.exited = new Promise(resolve => {
			this.child.on('close', code => {
				resolve();
				this.peer.failAll(new Error(`${this.label} exited`));
				if (this.interrupting) {
					this.end('interrupted', {});
					return;
				}

				this.end('failed', {
					error:
						this.stderr.trim() || `${this.label} exited with ${String(code)}`,
				});
			});
			this.child.on('error', (error: NodeJS.ErrnoException) => {
				console.error(`[runner] ${this.label}: ${String(error)}`);
				resolve();
				this.end('failed', {error: spawnFailure(this.label, error)});
			});
		});
		void this.run(relay).catch((error: unknown) => {
			this.end(this.interrupting ? 'interrupted' : 'failed', {
				error: String(error instanceof Error ? error.message : error),
			});
			this.child.kill('SIGTERM');
		});
	}

	private async run(relay: McpRelay): Promise<void> {
		const {assign} = this;
		const init = await this.peer.request('initialize', {
			protocolVersion: 1,
			clientCapabilities: {
				fs: {readTextFile: false, writeTextFile: false},
				terminal: false,
			},
			clientInfo: {name: 'agentarea-runner', version: VERSION},
		});
		const capabilities = (init?.agentCapabilities ?? {}) as Record<string, any>;
		if (!capabilities['mcpCapabilities']?.http) {
			throw new Error(
				`${this.label} takes no HTTP MCP server, so the client's tools would be missing from its turns`,
			);
		}

		const cwd = taskDir(this.options, assign.task_id);
		const mcpServers = [
			{
				type: 'http',
				name: MCP_SERVER_NAME,
				url: relay.url(assign.task_id),
				headers: [],
			},
		];
		let resumed = false;
		let session: Record<string, any> | null;
		if (assign.session_id && capabilities['loadSession']) {
			// Loading replays the session's history as updates; it is not this turn's.
			this.replaying = true;
			session = await this.peer.request('session/load', {
				sessionId: assign.session_id,
				cwd,
				mcpServers,
			});
			this.replaying = false;
			this.sessionId = assign.session_id;
			resumed = true;
		} else {
			session = await this.peer.request('session/new', {cwd, mcpServers});
			this.sessionId = String(session?.['sessionId']);
		}

		this.sink.started(this.sessionId);
		if (assign.model) {
			await this.pickModel(assign.model, session?.['configOptions'] ?? []);
		}

		const text =
			assign.instructions && !resumed
				? `${assign.instructions}\n\n${assign.message}`
				: assign.message;
		const result = await this.peer.request(
			'session/prompt',
			{sessionId: this.sessionId, prompt: [{type: 'text', text}]},
			0,
		);
		for (const body of this.stream.flush()) {
			this.sink.event(body);
		}

		const stop = String(result?.stopReason ?? 'end_turn');
		if (stop === 'cancelled' || this.interrupting) {
			this.end('interrupted', {});
		} else if (stop === 'refusal') {
			this.end('failed', {error: `${this.label} refused the turn`});
		} else {
			this.end('completed', {response: this.stream.response});
		}

		this.child.stdin.end();
	}

	/** The turn's model: the session's model option, or `session/set_model` where it has none. */
	private async pickModel(
		model: string,
		configOptions: Array<Record<string, any>>,
	): Promise<void> {
		const option = acpModelOption(configOptions);
		if (option) {
			await this.peer.request('session/set_config_option', {
				sessionId: this.sessionId,
				configId: option,
				value: model,
			});
			return;
		}

		await this.peer.request('session/set_model', {
			sessionId: this.sessionId,
			modelId: model,
		});
	}

	private notified(method: string, params: Record<string, any>): void {
		if (method !== 'session/update' || this.replaying) {
			return;
		}

		for (const body of acpEvents(params['update'] ?? {}, this.stream)) {
			this.sink.event(body);
		}
	}

	private requested(
		id: number | string,
		method: string,
		params: Record<string, any>,
	): void {
		if (method !== 'session/request_permission') {
			this.peer.respondError(id, `the runner does not answer ${method}`);
			return;
		}

		const options = (params['options'] ?? []) as Array<Record<string, any>>;
		const call = (params['toolCall'] ?? {}) as Record<string, any>;
		if (!sandboxed(this.assign)) {
			this.answer(id, acpPermissionOption(options, true));
			return;
		}

		const requestId = `${this.assign.turn_id}-${String(id)}`;
		this.permissions.set(requestId, {id, options});
		this.sink.approval({
			request_id: requestId,
			item_id: call['toolCallId'] ?? null,
			kind: 'tool',
			tool_name: this.stream.toolName(
				String(call['toolCallId'] ?? ''),
				call['title'] ?? call['kind'],
			),
			arguments: (call['rawInput'] ?? {}) as Record<string, unknown>,
			reason: null,
		});
	}

	private answer(id: number | string, optionId: string | undefined): void {
		this.peer.respond(id, {
			outcome: optionId
				? {outcome: 'selected', optionId}
				: {outcome: 'cancelled'},
		});
	}

	steer(messageId: string, _text: string): void {
		// ACP takes one prompt at a time; the platform sends this one as the next turn.
		this.sink.steered(messageId, false);
	}

	cancel(): void {
		this.interrupting = true;
		for (const {id} of this.permissions.values()) {
			this.answer(id, undefined);
		}

		this.permissions.clear();
		if (this.sessionId) {
			this.peer.notify('session/cancel', {sessionId: this.sessionId});
		}

		setTimeout(() => {
			if (this.running) {
				console.error(
					`[runner] ${this.label} did not stop turn ${logged(
						this.assign.turn_id,
					)}; killing it`,
				);
				this.child.kill('SIGKILL');
			}
		}, CANCEL_GRACE_MS);
	}

	decide(requestId: string, approved: boolean): void {
		const pending = this.permissions.get(requestId);
		if (!pending) {
			return;
		}

		this.permissions.delete(requestId);
		this.answer(pending.id, acpPermissionOption(pending.options, approved));
	}

	/** Wait for the process of an earlier turn to exit, killing it after `graceMs`. */
	async stop(graceMs: number): Promise<void> {
		await Promise.race([this.exited, delay(graceMs)]);
		if (this.running) {
			this.child.kill('SIGKILL');
			await Promise.race([this.exited, delay(graceMs)]);
		}
	}

	private get running(): boolean {
		return this.child.exitCode === null && this.child.signalCode === null;
	}

	private end(
		status: FinishStatus,
		fields: {response?: string; error?: string},
	): void {
		if (this.ended) {
			return;
		}

		this.ended = true;
		this.sink.finished(status, {...fields, sessionId: this.sessionId});
	}
}

/**
 * The CLI's way to the client's MCP endpoint: a local endpoint per task that
 * forwards there with the token of the task's running turn. Between turns,
 * or for a task this runner holds no turn of, it refuses. Its address carries a
 * random secret; commands the CLI runs in its sandbox cannot reach it anyway.
 */
export class McpRelay {
	private readonly secret = crypto.randomBytes(16).toString('hex');
	private port = 0;
	private readonly server: http.Server;
	private readonly apiUrl: string;
	private readonly turnOf: (taskId: string) => Assign | undefined;

	constructor(apiUrl: string, turnOf: (taskId: string) => Assign | undefined) {
		this.apiUrl = apiUrl;
		this.turnOf = turnOf;
		this.server = http.createServer((request, response) => {
			this.relay(request, response).catch((error: unknown) => {
				console.error(`[runner] MCP relay: ${String(error)}`);
				if (!response.headersSent) {
					response.writeHead(502);
				}

				response.end();
			});
		});
	}

	async listen(): Promise<void> {
		await new Promise<void>(resolve => {
			this.server.listen(0, '127.0.0.1', resolve);
		});
		this.port = (this.server.address() as {port: number}).port;
	}

	url(taskId: string): string {
		return `http://127.0.0.1:${this.port}/${this.secret}/tasks/${taskId}/mcp`;
	}

	private async relay(
		request: http.IncomingMessage,
		response: http.ServerResponse,
	): Promise<void> {
		const match = /^\/([\da-f]+)\/tasks\/([^/?]+)\/mcp\/?(?:\?.*)?$/.exec(
			request.url ?? '',
		);
		if (!match || match[1] !== this.secret) {
			response.writeHead(404).end();
			return;
		}

		const turn = this.turnOf(match[2]!);
		if (!turn) {
			response.writeHead(403, {'content-type': 'application/json'}).end(
				JSON.stringify({
					jsonrpc: '2.0',
					id: null,
					error: {code: -32001, message: 'no turn of this task is running'},
				}),
			);
			return;
		}

		const chunks: Buffer[] = [];
		for await (const chunk of request) {
			chunks.push(chunk as Buffer);
		}

		const headers: Record<string, string> = {
			Authorization: `Bearer ${turn.token}`,
		};
		for (const name of RELAYED_REQUEST_HEADERS) {
			const value = request.headers[name];
			if (typeof value === 'string') {
				headers[name] = value;
			}
		}

		const method = request.method ?? 'GET';
		const gone = new AbortController();
		response.on('close', () => {
			gone.abort();
		});
		const upstream = await fetch(apiRoute(this.apiUrl, turn.mcp_path), {
			method,
			headers,
			signal: gone.signal,
			...(method === 'GET' || method === 'HEAD' || method === 'DELETE'
				? {}
				: {body: Buffer.concat(chunks)}),
		});
		const shown: Record<string, string> = {};
		for (const name of RELAYED_RESPONSE_HEADERS) {
			const value = upstream.headers.get(name);
			if (value !== null) {
				shown[name] = value;
			}
		}

		response.writeHead(upstream.status, shown);
		if (upstream.body) {
			pipeline(Readable.fromWeb(upstream.body as any), response, error => {
				if (error && !gone.signal.aborted) {
					console.error(`[runner] MCP relay stream: ${String(error)}`);
				}
			});
		} else {
			response.end();
		}
	}
}

/** The global WebSocket of Node 22+, which takes request headers. */
interface Socket {
	readyState: number;
	send(data: string): void;
	close(): void;
	addEventListener(type: string, listener: (event: any) => void): void;
}

const SocketImpl = (globalThis as any).WebSocket as new (
	url: string,
	init: {headers: Record<string, string>},
) => Socket;
const OPEN = 1;
const MAX_BACKOFF_MS = 30_000;

/** A turn this runner runs: its position counter and the CLI driving it. */
interface Running {
	assign: Assign;
	seq: number;
	control: TurnControl | undefined;
	/** The platform gave the turn away while this runner was disconnected. */
	dropped: boolean;
	/** The platform stopped the turn, maybe before its CLI started. */
	cancelled: boolean;
	/** Tool calls the CLI started and has not answered, by id: their names. */
	open: Map<string, string>;
}

/**
 * What waits for the next `welcome` when the socket is closed: a turn's end.
 * The platform gives every running turn away on reconnect, so what those turns
 * report meanwhile is dropped rather than queued.
 */
export function queuedWhileAway(frame: Record<string, unknown>): boolean {
	return frame['type'] === 'turn.finished';
}

/**
 * The runner: one socket to the platform, reconnecting with backoff. Frames
 * that find the socket closed are dropped, except those `queuedWhileAway`
 * keeps for after the next `welcome`.
 */
class Runner {
	private socket: Socket | undefined;
	private welcomed = false;
	private outbox: Array<Record<string, unknown>> = [];
	private readonly running = new Map<string, Running>();
	private readonly codexServers = new Map<string, CodexServer>();
	/** Each task's latest Claude process, which a new turn of the task waits out. */
	private readonly claudeTurns = new Map<string, ClaudeTurn>();
	private readonly acpTurns = new Map<string, AcpTurn>();
	/** An ACP harness's models, asked once at start. */
	acpReport: RunnerReport | undefined;
	private pinger: NodeJS.Timeout | undefined;
	private backoff = 1000;

	private readonly options: RunnerOptions;
	readonly relay: McpRelay;

	constructor(options: RunnerOptions) {
		this.options = options;
		this.relay = new McpRelay(options.config.api_url, taskId => {
			for (const running of this.running.values()) {
				if (running.assign.task_id === taskId && !running.dropped) {
					return running.assign;
				}
			}

			return undefined;
		});
	}

	connect(): void {
		const socket = new SocketImpl(socketUrl(this.options.config), {
			headers: {Authorization: `Bearer ${this.options.config.token}`},
		});
		this.socket = socket;
		this.welcomed = false;
		let opened = false;
		socket.addEventListener('open', () => {
			opened = true;
			this.backoff = 1000;
			const report =
				this.options.harness === 'codex'
					? codexRunnerReport(this.options.loginFrom)
					: this.acpReport;
			socket.send(
				JSON.stringify({
					type: 'hello',
					capacity: this.options.capacity,
					version: VERSION,
					turns: [...this.running.keys()],
					...(report ?? {}),
				}),
			);
		});
		socket.addEventListener('message', event => {
			this.receive(JSON.parse(String(event.data)) as Record<string, any>);
		});
		socket.addEventListener('close', event => {
			clearInterval(this.pinger);
			this.socket = undefined;
			this.welcomed = false;
			console.error(
				opened
					? `[runner] socket closed (${String(event.code)}); reconnecting`
					: `[runner] the platform refused the socket; is the runner key still valid? retrying in ${this.backoff} ms`,
			);
			setTimeout(() => {
				this.connect();
			}, this.backoff);
			this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
		});
		socket.addEventListener('error', () => {
			// The close event that follows reconnects.
		});
	}

	private send(frame: Record<string, unknown>): void {
		if (this.socket?.readyState === OPEN && this.welcomed) {
			this.socket.send(JSON.stringify(frame));
		} else if (queuedWhileAway(frame)) {
			this.outbox.push(frame);
		}
	}

	private receive(frame: Record<string, any>): void {
		switch (frame['type']) {
			case 'welcome': {
				this.onWelcome(frame);
				break;
			}

			case 'turn.assign': {
				let assign: Assign;
				try {
					assign = checkedAssign(frame);
				} catch (error) {
					console.error(`[runner] refused a turn: ${logged(error)}`);
					if (typeof frame['turn_id'] === 'string') {
						this.send({
							type: 'turn.finished',
							turn_id: frame['turn_id'],
							status: 'failed',
							response: null,
							error: String(error),
							session_id: null,
						});
					}

					break;
				}

				this.start(assign);
				break;
			}

			case 'turn.steer': {
				const turn = this.running.get(frame['turn_id']);
				if (turn?.control) {
					turn.control.steer(
						String(frame['message_id']),
						String(frame['text']),
					);
				} else {
					this.send({
						type: 'steer.rejected',
						turn_id: frame['turn_id'],
						message_id: frame['message_id'],
					});
				}

				break;
			}

			case 'turn.cancel': {
				const turn = this.running.get(frame['turn_id']);
				if (turn) {
					turn.cancelled = true;
					turn.control?.cancel();
				}

				break;
			}

			case 'approval.decision': {
				this.running
					.get(frame['turn_id'])
					?.control?.decide(
						String(frame['request_id']),
						Boolean(frame['approved']),
					);
				break;
			}

			default: {
				console.error(`[runner] unknown frame ${logged(frame['type'])}`);
			}
		}
	}

	private onWelcome(frame: Record<string, any>): void {
		const kept = new Set((frame['turns'] ?? []) as string[]);
		for (const [turnId, turn] of this.running) {
			if (!kept.has(turnId)) {
				console.error(`[runner] turn ${turnId} was given away; stopping it`);
				turn.dropped = true;
				turn.cancelled = true;
				turn.control?.cancel();
			}
		}

		this.welcomed = true;
		const waiting = this.outbox.filter(
			queued => !this.running.get(String(queued['turn_id']))?.dropped,
		);
		this.outbox = [];
		for (const queued of waiting) {
			this.send(queued);
		}

		const every = Number(frame['ping_seconds'] ?? 10) * 1000;
		clearInterval(this.pinger);
		this.pinger = setInterval(() => {
			if (this.socket?.readyState === OPEN) {
				this.socket.send(JSON.stringify({type: 'ping'}));
			}
		}, every);
		console.error(
			`[runner] connected; ${kept.size} turns kept, ${waiting.length} frames resent`,
		);
	}

	private sinkFor(running: Running): TurnSink {
		const turnId = running.assign.turn_id;
		const send = (frame: Record<string, unknown>) => {
			if (!running.dropped) {
				this.send({...frame, turn_id: turnId});
			}
		};

		return {
			started(sessionId) {
				send({type: 'turn.started', session_id: sessionId});
			},
			event(body) {
				if (body.kind === 'tool.call') {
					running.open.set(body.id, body.name);
				} else if (
					(body.kind === 'tool.result' || body.kind === 'tool.progress') &&
					!running.open.has(body.id)
				) {
					// A command an earlier, stopped turn left running; that turn closed it.
					return;
				} else if (body.kind === 'tool.result') {
					running.open.delete(body.id);
				}

				running.seq += 1;
				send({type: 'turn.event', seq: running.seq, event: body});
			},
			approval(ask) {
				send({type: 'approval.request', ...ask});
			},
			steered(messageId, accepted) {
				send({
					type: accepted ? 'steer.accepted' : 'steer.rejected',
					message_id: messageId,
				});
			},
			finished: (status, fields) => {
				// A stopped turn answers the calls it cut short, so its transcript closes.
				for (const [id, name] of running.open) {
					running.seq += 1;
					send({
						type: 'turn.event',
						seq: running.seq,
						event: {
							kind: 'tool.result',
							id,
							name,
							output: STOPPED_TOOL_OUTPUT,
							success: false,
						},
					});
				}

				running.open.clear();
				void this.finish(running, status, fields);
			},
		};
	}

	private async finish(
		running: Running,
		status: FinishStatus,
		fields: {response?: string; error?: string; sessionId?: string},
	): Promise<void> {
		const {assign} = running;
		try {
			await uploadTaskFiles(
				this.options,
				assign.task_id,
				taskDir(this.options, assign.task_id),
			);
		} catch (error) {
			console.error(
				`[runner] uploading the files of task ${logged(
					assign.task_id,
				)} failed: ${logged(error)}`,
			);
		}

		this.running.delete(assign.turn_id);
		if (!running.dropped) {
			this.send({
				type: 'turn.finished',
				turn_id: assign.turn_id,
				status,
				response: fields.response ?? null,
				error: fields.error ?? null,
				session_id: fields.sessionId ?? null,
			});
		}

		console.error(
			`[runner] task ${logged(assign.task_id)} turn ${logged(
				assign.iteration,
			)} ${status}${fields.error ? `: ${logged(fields.error)}` : ''}`,
		);
	}

	private start(assign: Assign): void {
		console.error(
			`[runner] task ${logged(assign.task_id)} turn ${logged(
				assign.iteration,
			)} from ${logged(assign.requested_by)}`,
		);
		const running: Running = {
			assign,
			seq: 0,
			control: undefined,
			dropped: false,
			cancelled: false,
			open: new Map(),
		};
		this.running.set(assign.turn_id, running);
		const sink = this.sinkFor(running);
		if (this.options.harness === 'claude') {
			void this.startClaude(running, sink);
			return;
		}

		if (this.options.harness !== 'codex') {
			void this.startAcp(running, sink);
			return;
		}

		void this.startCodex(running, sink);
	}

	private async startAcp(running: Running, sink: TurnSink): Promise<void> {
		const {assign} = running;
		// Two processes on one session would both write it.
		await this.acpTurns.get(assign.task_id)?.stop(CANCEL_GRACE_MS);
		if (running.cancelled) {
			sink.finished('interrupted', {});
			return;
		}

		const turn = new AcpTurn(
			this.options,
			this.relay,
			assign,
			sink,
			acpCommand(this.options),
		);
		running.control = turn;
		this.acpTurns.set(assign.task_id, turn);
		void turn.exited.then(() => {
			if (this.acpTurns.get(assign.task_id) === turn) {
				this.acpTurns.delete(assign.task_id);
			}
		});
	}

	private async startClaude(running: Running, sink: TurnSink): Promise<void> {
		const {assign} = running;
		// Two processes resuming one session would both write it.
		await this.claudeTurns.get(assign.task_id)?.stop(CANCEL_GRACE_MS);
		if (running.cancelled) {
			sink.finished('interrupted', {});
			return;
		}

		let turn: ClaudeTurn;
		try {
			turn = new ClaudeTurn(this.options, this.relay, assign, sink);
		} catch (error) {
			sink.finished('failed', {error: String(error)});
			return;
		}

		running.control = turn;
		this.claudeTurns.set(assign.task_id, turn);
		void turn.exited.then(() => {
			if (this.claudeTurns.get(assign.task_id) === turn) {
				this.claudeTurns.delete(assign.task_id);
			}
		});
	}

	private async startCodex(running: Running, sink: TurnSink): Promise<void> {
		const {assign} = running;
		if (sandboxed(assign) && !managesNetwork(codexRequirements())) {
			sink.finished('failed', {error: REQUIREMENTS_MISSING});
			return;
		}

		const {home, config} = profileHome(this.options, assign);
		let server = this.codexServers.get(home);
		if (server && server.config !== config) {
			console.error(
				`[runner] the client's sandbox or allowed domains changed; restarting the CLI of ${logged(
					assign.requested_by,
				)}`,
			);
			server.retire();
			server = undefined;
		}

		if (!server) {
			const started: CodexServer = new CodexServer(
				this.options,
				this.relay,
				home,
				config,
				() => {
					if (this.codexServers.get(home) === started) {
						this.codexServers.delete(home);
					}
				},
			);
			server = started;
			this.codexServers.set(home, server);
		}

		const turn = new CodexTurn(server, assign, sink);
		running.control = turn;
		try {
			await server.ready;
			await turn.start();
		} catch (error) {
			turn.end('failed', {error: String(error)});
		}
	}
}

/** A file only this user can read; its path goes on a command line instead of its content. */
function privateFile(dir: string, name: string, content: string): string {
	const file = path.join(dir, name);
	fs.writeFileSync(file, content, {mode: 0o600});
	fs.chmodSync(file, 0o600);
	return file;
}

/**
 * Claude Code has no command jail here: its commands wait for a person's
 * approval, and its own file tools are kept off the runner's key, logins and
 * per-person profiles.
 */
export function claudeSettings(options: RunnerOptions): {
	permissions: {deny: string[]};
} {
	const secret = [
		path.join(path.resolve(options.root), CONFIG_FILE),
		path.join(path.resolve(options.root), 'profiles', '**'),
		...(options.loginFrom
			? [path.join(path.resolve(options.loginFrom), '**')]
			: []),
	];
	return {
		permissions: {
			deny: secret.flatMap(target => [`Read(/${target})`, `Edit(/${target})`]),
		},
	};
}

function codexRequirements(): string {
	return fs.existsSync(CODEX_REQUIREMENTS_FILE)
		? fs.readFileSync(CODEX_REQUIREMENTS_FILE, 'utf8')
		: '';
}

/** Why a sandboxed Codex turn cannot run: no approval could reach a host off the list. */
const REQUIREMENTS_MISSING = `${CODEX_REQUIREMENTS_FILE} must turn on Codex's managed network proxy, so a person can allow a host the client does not list; run \`agentarea runner setup\` on the runner's machine, or turn the client's sandbox off`;

/**
 * Turn on Codex's managed network proxy for this machine. The file is the
 * machine's, under /etc, so writing it asks for the person's sudo password.
 */
export function setupCodexRequirements(): 'already' | 'written' {
	const current = codexRequirements();
	if (managesNetwork(current)) return 'already';
	if (/^\s*\[network_proxy\]\s*$/m.test(current)) {
		throw new Error(
			`${CODEX_REQUIREMENTS_FILE} has a [network_proxy] table without \`enabled = true\`; set it there`,
		);
	}

	const mkdir = spawnSync(
		'sudo',
		['mkdir', '-p', path.dirname(CODEX_REQUIREMENTS_FILE)],
		{
			stdio: 'inherit',
		},
	);
	const tee =
		mkdir.status === 0
			? spawnSync('sudo', ['tee', '-a', CODEX_REQUIREMENTS_FILE], {
					input: `${
						current && !current.endsWith('\n') ? '\n' : ''
					}\n[network_proxy]\nenabled = true\n`,
					stdio: ['pipe', 'ignore', 'inherit'],
			  })
			: mkdir;
	if (tee.status !== 0) {
		throw new Error(`could not write ${CODEX_REQUIREMENTS_FILE}`);
	}

	return 'written';
}

export async function runRunner(options: RunnerOptions): Promise<never> {
	if (options.harness !== 'codex' && options.harness !== 'claude') {
		// A custom harness without a command stops here, not at its first turn.
		acpCommand(options);
	}

	if (options.harness === 'codex' && !managesNetwork(codexRequirements())) {
		console.error(
			`[runner] ${REQUIREMENTS_MISSING}; until then its sandboxed turns fail.`,
		);
	}
	console.error(
		`[runner] ${options.harness} serving client ${options.config.client_id} in ${options.config.workspace} at ${options.config.api_url}; data in ${options.root}`,
	);
	const runner = new Runner(options);
	if (options.harness !== 'codex' && options.harness !== 'claude') {
		try {
			runner.acpReport = await acpRunnerReport(options);
		} catch (error) {
			console.error(
				`[runner] could not ask ${options.harness} for its models: ${String(
					error,
				)}`,
			);
		}
	}

	await runner.relay.listen();
	runner.connect();
	return new Promise<never>(() => {
		// Runs until the process is stopped.
	});
}

export function defaultRunnerRoot(): string {
	return path.join(os.homedir(), '.agentarea', 'runner');
}
