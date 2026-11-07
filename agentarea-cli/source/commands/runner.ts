import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {Readable} from 'node:stream';
import {spawn, type ChildProcessWithoutNullStreams} from 'node:child_process';

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

export type RunnerHarness = 'codex' | 'claude';

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
	/**
	 * `profile`: every command the CLI runs sees only its task's folder, nothing of the
	 * runner's data or other people's profiles, and the network only to `allowDomains`
	 * and the client's own allowed domains;
	 * anything beyond that waits for a person's approval. `none`: commands run unconfined.
	 */
	sandbox: 'profile' | 'none';
	allowDomains: string[];
	/** Turns run at once. */
	capacity: number;
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
	/** Acts for the turn's actor on the client's MCP endpoint until the turn ends. */
	token: string;
	/** The client's MCP endpoint, relative to the platform's API. */
	mcp_path: string;
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
	clientDomains: string[] = [],
): string {
	const features = [
		'[features]',
		...ACCOUNT_FEATURES.map(feature => `${feature} = false`),
	];
	if (options.sandbox === 'none') {
		return [...features, ''].join('\n');
	}

	const domains = [...new Set([...options.allowDomains, ...clientDomains])];
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
function profileHome(
	options: RunnerOptions,
	userId: string,
	clientDomains: string[] = [],
): {home: string; config: string} {
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

	const config = codexConfig(options, home, clientDomains);
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

/** A newline-delimited JSON-RPC peer over a child's stdio, as `codex app-server` speaks it. */
class JsonRpcPeer {
	private next = 1;
	private readonly waiting = new Map<
		number,
		{resolve: (value: any) => void; reject: (error: Error) => void}
	>();

	private readonly child: ChildProcessWithoutNullStreams;
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
	) {
		this.child = child;
		this.onNotification = onNotification;
		this.onRequest = onRequest;
		const lines = readline.createInterface({input: child.stdout});
		lines.on('line', line => {
			this.receive(line);
		});
	}

	async request(method: string, params: unknown): Promise<any> {
		const id = this.next++;
		return new Promise((resolve, reject) => {
			this.waiting.set(id, {resolve, reject});
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
		for (const pending of this.waiting.values()) {
			pending.reject(error);
		}

		this.waiting.clear();
	}

	private write(message: unknown): void {
		this.child.stdin.write(`${JSON.stringify(message)}\n`);
	}

	private receive(line: string): void {
		let message: Record<string, any>;
		try {
			message = JSON.parse(line);
		} catch {
			console.error(`[runner] codex app-server said: ${line}`);
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
				new Error(String(message['error'].message ?? 'codex app-server error')),
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
		const unconfined = this.server.options.sandbox === 'none';
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
		if (this.threadId !== null) {
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
				const turn =
					typeof params['threadId'] === 'string'
						? this.byThread.get(params['threadId'])
						: undefined;
				turn?.onNotification(method, params);
			},
			(id, method, params) => {
				const turn =
					typeof params['threadId'] === 'string'
						? this.byThread.get(params['threadId'])
						: undefined;
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
			const error = new Error(
				this.stderr.trim() || `codex app-server exited with ${String(code)}`,
			);
			this.peer.failAll(error);
			for (const turn of [...this.byThread.values()]) {
				turn.end('failed', {error: error.message});
			}

			this.onExit();
		});
		this.ready = this.initialize();
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
		const {home} = profileHome(options, assign.requested_by);
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
			options.sandbox === 'none' ? 'bypassPermissions' : 'acceptEdits',
			'--mcp-config',
			JSON.stringify({
				mcpServers: {
					[MCP_SERVER_NAME]: {type: 'http', url: relay.url(assign.task_id)},
				},
			}),
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
		this.child.on('close', code => {
			this.end('failed', {
				error: this.stderr.trim() || `claude exited with ${String(code)}`,
			});
		});
		this.write({
			type: 'user',
			message: {role: 'user', content: assign.message},
			parent_tool_use_id: null,
		});
	}

	steer(messageId: string, text: string): void {
		if (this.ended) {
			this.sink.steered(messageId, false);
			return;
		}

		this.write({
			type: 'user',
			message: {role: 'user', content: text},
			parent_tool_use_id: null,
		});
		this.sink.steered(messageId, true);
	}

	cancel(): void {
		this.interrupting = true;
		this.write({
			type: 'control_request',
			request_id: `interrupt-${Date.now()}`,
			request: {subtype: 'interrupt'},
		});
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
	const res = await fetch(`${apiUrl}/v1/runner/whoami`, {
		headers: {Authorization: `Bearer ${key}`},
	});
	if (!res.ok) {
		throw new Error(
			`the platform refused the key: HTTP ${res.status} ${await res.text()}`,
		);
	}

	const identity = (await res.json()) as {
		client_id: string;
		workspace: string;
		kind: RunnerHarness;
	};
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
	return `${options.config.api_url}/v1/runner/${route}`;
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
		const file = path.join(cwd, rel);
		if (fs.statSync(file).size > MAX_UPLOAD_BYTES) {
			console.error(
				`[runner] ${rel}: larger than ${MAX_UPLOAD_BYTES} bytes, not uploaded`,
			);
			continue;
		}

		const encoded = rel.split('/').map(encodeURIComponent).join('/');
		const res = await fetch(
			runnerUrl(options, `tasks/${taskId}/files/${encoded}`),
			{
				method: 'PUT',
				headers: {
					Authorization: `Bearer ${options.config.token}`,
					'Content-Type': 'application/octet-stream',
				},
				body: fs.readFileSync(file),
			},
		);
		if (!res.ok) {
			console.error(
				`[runner] upload ${rel}: HTTP ${res.status} ${await res.text()}`,
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
		const upstream = await fetch(`${this.apiUrl}${turn.mcp_path}`, {
			method,
			headers,
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
			Readable.fromWeb(upstream.body as any).pipe(response);
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
	/** Tool calls the CLI started and has not answered, by id: their names. */
	open: Map<string, string>;
}

/**
 * The runner: one socket to the platform, reconnecting with backoff. Frames
 * that find the socket closed wait in the outbox and go after the next
 * `welcome`; the platform drops any it already kept by their position.
 */
class Runner {
	private socket: Socket | undefined;
	private welcomed = false;
	private outbox: Array<Record<string, unknown>> = [];
	private readonly running = new Map<string, Running>();
	private readonly codexServers = new Map<string, CodexServer>();
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
					: undefined;
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
		} else {
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
				this.start(frame as unknown as Assign);
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
				this.running.get(frame['turn_id'])?.control?.cancel();
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
				console.error(`[runner] unknown frame ${String(frame['type'])}`);
			}
		}
	}

	private onWelcome(frame: Record<string, any>): void {
		const kept = new Set((frame['turns'] ?? []) as string[]);
		for (const [turnId, turn] of this.running) {
			if (!kept.has(turnId)) {
				console.error(`[runner] turn ${turnId} was given away; stopping it`);
				turn.dropped = true;
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
				`[runner] uploading the files of task ${
					assign.task_id
				} failed: ${String(error)}`,
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
			`[runner] task ${assign.task_id} turn ${assign.iteration} ${status}${
				fields.error ? `: ${fields.error}` : ''
			}`,
		);
	}

	private start(assign: Assign): void {
		console.error(
			`[runner] task ${assign.task_id} turn ${assign.iteration} from ${assign.requested_by}`,
		);
		const running: Running = {
			assign,
			seq: 0,
			control: undefined,
			dropped: false,
			open: new Map(),
		};
		this.running.set(assign.turn_id, running);
		const sink = this.sinkFor(running);
		if (this.options.harness === 'claude') {
			running.control = new ClaudeTurn(this.options, this.relay, assign, sink);
			return;
		}

		void this.startCodex(running, sink);
	}

	private async startCodex(running: Running, sink: TurnSink): Promise<void> {
		const {assign} = running;
		const {home, config} = profileHome(
			this.options,
			assign.requested_by,
			assign.allow_domains,
		);
		let server = this.codexServers.get(home);
		if (server && server.config !== config) {
			console.error(
				`[runner] the client's allowed domains changed; restarting the CLI of ${assign.requested_by}`,
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

/** A sandboxed Codex needs its managed network proxy on, or no approval can reach a host. */
function checkCodexRequirements(options: RunnerOptions): void {
	if (options.harness !== 'codex' || options.sandbox === 'none') {
		return;
	}

	const requirements = fs.existsSync(CODEX_REQUIREMENTS_FILE)
		? fs.readFileSync(CODEX_REQUIREMENTS_FILE, 'utf8')
		: '';
	if (!managesNetwork(requirements)) {
		throw new Error(
			`${CODEX_REQUIREMENTS_FILE} must turn on Codex's managed network proxy, so a person can allow a host the client does not list:\n\n[network_proxy]\nenabled = true\n\nAdd it, or run with --sandbox none.`,
		);
	}
}

export async function runRunner(options: RunnerOptions): Promise<never> {
	checkCodexRequirements(options);
	console.error(
		`[runner] ${options.harness} serving client ${options.config.client_id} in ${options.config.workspace} at ${options.config.api_url}; data in ${options.root}`,
	);
	const runner = new Runner(options);
	await runner.relay.listen();
	runner.connect();
	return new Promise<never>(() => {
		// Runs until the process is stopped.
	});
}

export function defaultRunnerRoot(): string {
	return path.join(os.homedir(), '.agentarea', 'runner');
}
