import path from 'node:path';
import {spawn} from 'node:child_process';

/**
 * Harness wiring: resolve (or create) the client bundle on the server, then let
 * the harness's own CLI own its config and its OAuth session. We never write
 * `~/.codex/config.toml` or Claude's settings ourselves — `codex mcp add` and
 * `claude mcp add` are the supported entry points, and codex additionally keeps
 * its OAuth tokens in a store only it can read.
 */

const STARTUP_TIMEOUT_SEC = 60;
const TOOL_TIMEOUT_SEC = 120;

export type Harness = 'codex' | 'claude';
export type Scope = 'project' | 'user';

export interface ClientRef {
	id: string;
	name: string;
}

export interface ClientRecord {
	id: string;
	name: string;
	kind?: string;
	mcp_endpoint_url?: string | null;
	mcp_instances?: ClientRef[];
	skills?: ClientRef[];
}

export interface ClientApi {
	list(): Promise<ClientRecord[]>;
	create(data: {name: string; kind: string}): Promise<ClientRecord>;
	addMcp(clientId: string, mcpInstanceId: string): Promise<void>;
}

export function defaultClientName(hostname: string, harness: Harness): string {
	const machine = hostname
		.split('.')[0]!
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '');

	return `${machine || 'local'}-${harness}`;
}

export function mcpAlias(name: string): string {
	if (name === 'default') {
		return 'agentarea';
	}

	const suffix = name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '_')
		.replace(/^_+|_+$/g, '');

	return `agentarea_${suffix || 'default'}`;
}

export function harnessAddArgs(
	harness: Harness,
	options: {alias: string; url: string; scope: Scope},
): string[] {
	if (harness === 'codex') {
		return ['mcp', 'add', options.alias, '--url', options.url];
	}

	return [
		'mcp',
		'add',
		'--transport',
		'http',
		'--scope',
		options.scope,
		options.alias,
		options.url,
	];
}

/**
 * Codex authorizes from its own CLI; Claude Code has no `mcp login` — it runs
 * the OAuth flow in-app on first use (`/mcp`), so there is nothing to spawn.
 */
export function harnessLoginArgs(
	harness: Harness,
	alias: string,
): string[] | null {
	return harness === 'codex' ? ['mcp', 'login', alias] : null;
}

export async function resolveOrCreateClient(
	api: ClientApi,
	options: {name: string; kind: Harness},
): Promise<{client: ClientRecord; created: boolean}> {
	const clients = await api.list();
	const existing = clients.find(client => client.name === options.name);
	if (existing) {
		return {client: existing, created: false};
	}

	const client = await api.create({name: options.name, kind: options.kind});
	if (!client?.id) {
		throw new Error(`Creating client "${options.name}" returned no id`);
	}

	return {client, created: true};
}

export function resolveMcpInstanceId(
	instances: ClientRef[],
	reference: string,
): string {
	const byId = instances.find(instance => instance.id === reference);
	if (byId) {
		return byId.id;
	}

	const byName = instances.filter(instance => instance.name === reference);
	if (byName.length > 1) {
		throw new Error(
			`MCP instance name "${reference}" is ambiguous (${byName.length} matches); pass the id instead`,
		);
	}

	if (byName.length === 0) {
		const available = instances.map(instance => instance.name).join(', ');
		throw new Error(
			`No MCP instance "${reference}" in this workspace. Available: ${
				available || 'none'
			}`,
		);
	}

	return byName[0]!.id;
}

export async function attachMcpInstance(
	api: ClientApi,
	client: ClientRecord,
	mcpInstanceId: string,
): Promise<'attached' | 'already-attached'> {
	const attached = (client.mcp_instances ?? []).some(
		instance => instance.id === mcpInstanceId,
	);
	if (attached) {
		return 'already-attached';
	}

	await api.addMcp(client.id, mcpInstanceId);
	return 'attached';
}

export async function runHarnessCommand(
	bin: Harness,
	args: string[],
): Promise<void> {
	await new Promise<void>((resolve, reject) => {
		const child = spawn(bin, args, {stdio: 'inherit'});

		child.on('error', (error: NodeJS.ErrnoException) => {
			if (error.code === 'ENOENT') {
				reject(
					new Error(
						`\`${bin}\` is not on PATH; install it (or run the printed command yourself) — refusing to edit its config file directly`,
					),
				);
				return;
			}

			reject(error);
		});

		child.on('close', code => {
			if (code === 0) {
				resolve();
				return;
			}

			reject(
				new Error(`\`${bin} ${args.join(' ')}\` exited with code ${code}`),
			);
		});
	});
}

function escapeForRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function managedStart(alias: string): string {
	return `# >>> agentarea-cli managed: ${alias}`;
}

function managedEnd(alias: string): string {
	return `# <<< agentarea-cli managed: ${alias}`;
}

/**
 * Where codex reads a project-scoped server from. Codex walks up from the
 * working directory to the project root and the closest file wins, so a repo
 * can carry its own bundle without touching the user-wide config — which is
 * also the config other tools rewrite.
 */
export function codexProjectConfigPath(projectRoot: string): string {
	return path.join(projectRoot, '.codex', 'config.toml');
}

/**
 * Merge one server into a project `config.toml`, leaving everything else alone.
 * `codex mcp add` cannot do this — it only ever writes the user-wide config —
 * so this is the one place we edit a harness's file, and only inside markers we
 * own. An entry of the same name that we did not write is left untouched.
 */
export function upsertCodexServer(
	existing: string,
	alias: string,
	url: string,
): string {
	const block = [
		managedStart(alias),
		`[mcp_servers.${alias}]`,
		`url = "${url}"`,
		// Codex defaults to a 10s startup budget, and it drops a server that
		// misses it without a word in the log. A bundle aggregates every member
		// MCP's tools on `tools/list`, which measured ~15s for a single member
		// against prod, so the default is not survivable here.
		`startup_timeout_sec = ${STARTUP_TIMEOUT_SEC}`,
		`tool_timeout_sec = ${TOOL_TIMEOUT_SEC}`,
		managedEnd(alias),
		'',
	].join('\n');

	const managed = new RegExp(
		`${escapeForRegExp(managedStart(alias))}[\\s\\S]*?${escapeForRegExp(
			managedEnd(alias),
		)}\n?`,
		'm',
	);
	if (managed.test(existing)) {
		return existing.replace(managed, block);
	}

	const table = new RegExp(`^\\[mcp_servers\\.${escapeForRegExp(alias)}]`, 'm');
	if (table.test(existing)) {
		throw new Error(
			`Refusing to overwrite the unmanaged codex MCP entry "${alias}"; rename it or pass a different --alias`,
		);
	}

	return existing.trim() ? `${existing.trimEnd()}\n\n${block}` : block;
}

/**
 * Ask codex whether it actually resolves *alias* from the current directory.
 * A project-scoped file is ignored for an untrusted project, and codex says so
 * nowhere on write — only a later `mcp login` fails with "No MCP server named".
 */
export async function codexSeesServer(alias: string): Promise<boolean> {
	return new Promise<boolean>(resolve => {
		const child = spawn('codex', ['mcp', 'get', alias], {stdio: 'ignore'});
		child.on('error', () => {
			resolve(false);
		});
		child.on('close', code => {
			resolve(code === 0);
		});
	});
}
