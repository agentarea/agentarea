import fs from 'fs/promises';
import os from 'os';
import path from 'path';
import {type AuthToken} from '../types/index.js';

type Scope = 'project' | 'user';
type Client = 'codex' | 'claude';

interface ConnectOptions {
	apiUrl: string;
	token: AuthToken;
	scope?: string;
	name?: string;
	clientId?: string;
}

interface ConnectionRecord {
	client: Client;
	name: string;
	scope: Scope;
	apiUrl: string;
	mcpUrl: string;
	tokenEnvVar: string;
	tokenPrefix: string;
	connectedAt: string;
	updatedAt: string;
	clientId?: string;
}

interface ConnectionState {
	version: 1;
	updatedAt: string;
	connections: Partial<Record<Client, Record<string, ConnectionRecord>>>;
}

function normalizedScope(scope: string | undefined): Scope {
	if (scope === 'user' || scope === 'project') {
		return scope;
	}

	return 'project';
}

function normalizedName(name: string | undefined): string {
	const value = name?.trim();
	return value || 'default';
}

function mcpServerName(name: string): string {
	if (name === 'default') {
		return 'agentarea';
	}

	const suffix = name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '_')
		.replace(/^_+|_+$/g, '');

	return `agentarea_${suffix || 'default'}`;
}

function targetSuffix(name: string): string {
	return (
		name
			.toUpperCase()
			.replace(/[^A-Z0-9]+/g, '_')
			.replace(/^_+|_+$/g, '') || 'DEFAULT'
	);
}

function tokenEnvVar(name: string): string {
	return name === 'default'
		? 'AGENTAREA_TOKEN'
		: `AGENTAREA_${targetSuffix(name)}_TOKEN`;
}

function mcpUrl(apiUrl: string, clientId?: string): string {
	const base = apiUrl.replace(/\/$/, '');
	return clientId ? `${base}/client-mcp/${clientId}` : `${base}/mcp`;
}

function agentareaDir(): string {
	return path.join(os.homedir(), '.agentarea');
}

function connectionsPath(): string {
	return path.join(agentareaDir(), 'connections.json');
}

function codexConfigPath(scope: Scope): string {
	return scope === 'user'
		? path.join(os.homedir(), '.codex', 'config.toml')
		: path.join(process.cwd(), '.codex', 'config.toml');
}

function tokenPrefix(token: AuthToken): string {
	return token.accessToken ? token.accessToken.slice(0, 12) : '';
}

async function loadConnectionState(): Promise<ConnectionState> {
	try {
		const raw = await fs.readFile(connectionsPath(), 'utf8');
		return JSON.parse(raw) as ConnectionState;
	} catch (error: unknown) {
		if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
			throw error;
		}

		return {
			version: 1,
			updatedAt: new Date(0).toISOString(),
			connections: {},
		};
	}
}

async function saveConnectionState(
	client: Client,
	scope: Scope,
	options: ConnectOptions,
): Promise<string> {
	const now = new Date().toISOString();
	const state = await loadConnectionState();
	const name = normalizedName(options.name);
	const previous = state.connections[client]?.[name];
	const record: ConnectionRecord = {
		client,
		name,
		scope,
		apiUrl: options.apiUrl.replace(/\/$/, ''),
		mcpUrl: mcpUrl(options.apiUrl, options.clientId),
		tokenEnvVar: tokenEnvVar(name),
		tokenPrefix: tokenPrefix(options.token),
		connectedAt: previous?.connectedAt ?? now,
		updatedAt: now,
		clientId: options.clientId,
	};

	state.connections[client] = {
		...(state.connections[client] ?? {}),
		[name]: record,
	};
	state.updatedAt = now;

	await fs.mkdir(agentareaDir(), {recursive: true, mode: 0o700});
	await fs.writeFile(connectionsPath(), `${JSON.stringify(state, null, 2)}\n`, {
		mode: 0o600,
	});

	return connectionsPath();
}

function codexBlockStart(name: string): string {
	return `# >>> agentarea-cli managed: ${mcpServerName(name)} MCP`;
}

function codexBlockEnd(name: string): string {
	return `# <<< agentarea-cli managed: ${mcpServerName(name)} MCP`;
}

function codexManagedBlock(
	apiUrl: string,
	name: string,
	clientId?: string,
): string {
	return [
		codexBlockStart(name),
		`[mcp_servers.${mcpServerName(name)}]`,
		`url = "${mcpUrl(apiUrl, clientId)}"`,
		`bearer_token_env_var = "${tokenEnvVar(name)}"`,
		'startup_timeout_sec = 10',
		'tool_timeout_sec = 60',
		codexBlockEnd(name),
	].join('\n');
}

async function writeCodexConfig(
	apiUrl: string,
	scope: Scope,
	name: string,
	clientId?: string,
): Promise<string> {
	const configPath = codexConfigPath(scope);
	let existing = '';

	try {
		existing = await fs.readFile(configPath, 'utf8');
	} catch (error: unknown) {
		if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
			throw error;
		}
	}

	const managedPattern = new RegExp(
		`${codexBlockStart(name)}[\\s\\S]*?${codexBlockEnd(name)}`,
		'm',
	);
	const nextBlock = codexManagedBlock(apiUrl, name, clientId);
	let nextConfig: string;

	if (managedPattern.test(existing)) {
		nextConfig = existing.replace(managedPattern, nextBlock);
	} else {
		const tablePattern = new RegExp(
			`^\\[mcp_servers\\.${mcpServerName(name)}\\]`,
			'm',
		);
		if (tablePattern.test(existing)) {
			throw new Error(
				`Refusing to overwrite existing unmanaged Codex MCP config ${mcpServerName(
					name,
				)} at ${configPath}`,
			);
		}

		nextConfig = `${existing.trimEnd()}${existing ? '\n\n' : ''}${nextBlock}\n`;
	}

	await fs.mkdir(path.dirname(configPath), {recursive: true});
	await fs.writeFile(configPath, nextConfig, 'utf8');
	return configPath;
}

function codexInstructions(
	apiUrl: string,
	configPath: string,
	name: string,
): string {
	return [
		'Codex connection',
		`- target: ${name}`,
		`- MCP server: ${mcpServerName(name)}`,
		`- config written: ${configPath}`,
		`- token source: ${tokenEnvVar(name)} environment variable`,
		'- local client gets one MCP for this Agentarea target',
		'',
		'Run Codex with:',
		`  export ${tokenEnvVar(name)}="<agentarea-token>"`,
		'',
		'No per-tool sync is needed. Hosted third-party MCP access changes in Agentarea policy.',
	].join('\n');
}

function claudeInstructions(
	apiUrl: string,
	scope: Scope,
	token: AuthToken,
	name: string,
	clientId?: string,
): string {
	const tokenPlaceholder = token.accessToken
		? '<stored-agentarea-token>'
		: '<agentarea-token>';

	return [
		'Claude Code connection',
		`- target: ${name}`,
		`- MCP server: ${mcpServerName(name)}`,
		`- scope: ${scope}`,
		'- local client gets one MCP for this Agentarea target',
		'- token source: stored Agentarea CLI token',
		'',
		'Run:',
		`  claude mcp add --transport http ${mcpServerName(
			name,
		)} --scope ${scope} ${mcpUrl(
			apiUrl,
			clientId,
		)} --header "Authorization: Bearer ${tokenPlaceholder}"`,
		'',
		'No per-tool sync is needed. Hosted third-party MCP access changes in Agentarea policy.',
	].join('\n');
}

function connectionModel(): string {
	return [
		'Model:',
		'  Claude/Codex -> agentarea MCP -> Agentarea policy/router -> hosted MCP instances',
		'',
		'Connect once. Local config stays stable; Agentarea handles grant, revoke, audit, and routing centrally.',
	].join('\n');
}

export async function connectClient(
	client: string | undefined,
	options: ConnectOptions,
): Promise<boolean> {
	if (client !== 'codex' && client !== 'claude') {
		console.error(
			'Usage: agentarea-cli connect <codex|claude> [--scope=project|user]',
		);
		return false;
	}

	const scope = normalizedScope(options.scope);
	const name = normalizedName(options.name);
	const statePath = await saveConnectionState(client, scope, options);
	const codexConfig =
		client === 'codex'
			? await writeCodexConfig(options.apiUrl, scope, name, options.clientId)
			: '';
	const output =
		client === 'codex'
			? codexInstructions(options.apiUrl, codexConfig, name)
			: claudeInstructions(
					options.apiUrl,
					scope,
					options.token,
					name,
					options.clientId,
			  );

	console.log(output);
	console.log('');
	console.log(connectionModel());
	console.log('');
	console.log(`Saved non-secret connection state: ${statePath}`);
	console.log('');
	console.log('Do not paste real tokens into project files.');
	return true;
}
