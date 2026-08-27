import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import * as sdk from '@agentarea/api-client';
import {
	attachMcpInstance,
	defaultClientName,
	harnessAddArgs,
	harnessLoginArgs,
	mcpAlias,
	resolveMcpInstanceId,
	resolveOrCreateClient,
	runHarnessCommand,
	type ClientApi,
	type ClientRecord,
	type ClientRef,
	type Harness,
	type Scope,
} from './harness.js';
import {type SdkResult} from './output.js';

/**
 * `agentarea connect <codex|claude>` — point a local harness at a governed
 * client bundle. The client is resolved (or created) server-side, the harness's
 * own CLI writes its config and runs its OAuth flow, and nothing here ever
 * touches a token or another tool's config file.
 */

export interface ConnectOptions {
	apiUrl: string;
	clientId?: string;
	name?: string;
	alias?: string;
	scope?: string;
	mcp?: string;
	login?: boolean;
}

interface ConnectionRecord {
	client: Harness;
	clientId: string;
	clientName: string;
	alias: string;
	scope: Scope;
	apiUrl: string;
	mcpUrl: string;
	auth: 'oauth';
	connectedAt: string;
	updatedAt: string;
}

interface ConnectionState {
	version: 1;
	updatedAt: string;
	connections: Partial<Record<Harness, Record<string, ConnectionRecord>>>;
}

function normalizedScope(scope: string | undefined): Scope {
	return scope === 'user' ? 'user' : 'project';
}

function unwrap<T>(result: SdkResult, what: string): T {
	const status = result.response?.status;
	if (result.error !== undefined || (status !== undefined && status >= 400)) {
		throw new Error(
			`Failed to ${what} (${status ?? 'no status'}): ${JSON.stringify(
				result.error ?? null,
			)}`,
		);
	}

	return result.data as T;
}

function clientApi(): ClientApi {
	return {
		async list() {
			return unwrap<ClientRecord[]>(
				(await sdk.listClientsV1ClientsGet({})) as SdkResult,
				'list clients',
			);
		},
		async create(data) {
			return unwrap<ClientRecord>(
				(await sdk.createClientV1ClientsPost({
					body: {name: data.name, kind: data.kind, description: null},
				} as never)) as SdkResult,
				`create client "${data.name}"`,
			);
		},
		async addMcp(clientId, mcpInstanceId) {
			unwrap(
				(await sdk.addMcpInstanceToClientV1ClientsClientIdMcpInstancesPost({
					path: {client_id: clientId},
					body: {id: mcpInstanceId},
				} as never)) as SdkResult,
				'attach the MCP instance to the client',
			);
		},
	};
}

async function getClient(clientId: string): Promise<ClientRecord> {
	return unwrap<ClientRecord>(
		(await sdk.getClientV1ClientsClientIdGet({
			path: {client_id: clientId},
		} as never)) as SdkResult,
		`read client ${clientId}`,
	);
}

async function setClientKind(
	clientId: string,
	kind: Harness,
): Promise<ClientRecord> {
	return unwrap<ClientRecord>(
		(await sdk.updateClientV1ClientsClientIdPatch({
			path: {client_id: clientId},
			body: {kind},
		} as never)) as SdkResult,
		`label client ${clientId} as ${kind}`,
	);
}

async function listMcpInstances(): Promise<ClientRef[]> {
	const instances = unwrap<Array<{id: string; name: string}>>(
		(await sdk.listMcpServerInstancesV1McpServerInstancesGet({})) as SdkResult,
		'list MCP instances',
	);
	return instances.map(instance => ({id: instance.id, name: instance.name}));
}

function connectionsPath(): string {
	return path.join(os.homedir(), '.agentarea', 'connections.json');
}

async function loadConnectionState(): Promise<ConnectionState> {
	try {
		return JSON.parse(
			await fs.readFile(connectionsPath(), 'utf8'),
		) as ConnectionState;
	} catch (error: unknown) {
		if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
			throw error;
		}

		return {version: 1, updatedAt: new Date(0).toISOString(), connections: {}};
	}
}

async function saveConnectionState(record: ConnectionRecord): Promise<string> {
	const state = await loadConnectionState();
	const previous = state.connections[record.client]?.[record.alias];
	state.connections[record.client] = {
		...(state.connections[record.client] ?? {}),
		[record.alias]: {
			...record,
			connectedAt: previous?.connectedAt ?? record.connectedAt,
		},
	};
	state.updatedAt = record.updatedAt;

	await fs.mkdir(path.dirname(connectionsPath()), {
		recursive: true,
		mode: 0o700,
	});
	await fs.writeFile(connectionsPath(), `${JSON.stringify(state, null, 2)}\n`, {
		mode: 0o600,
	});
	return connectionsPath();
}

export async function connectClient(
	harness: string | undefined,
	options: ConnectOptions,
): Promise<boolean> {
	if (harness !== 'codex' && harness !== 'claude') {
		console.error(
			'Usage: agentarea connect <codex|claude> [--name=<client>] [--mcp=<instance>] [--alias=<local name>] [--scope=project|user]',
		);
		return false;
	}

	const scope = normalizedScope(options.scope);
	const api = clientApi();
	const clientName = options.name ?? defaultClientName(os.hostname(), harness);

	let client: ClientRecord;
	if (options.clientId) {
		client = await getClient(options.clientId);
		console.log(`Using client ${client.name} (${client.id})`);
		if (client.kind !== harness) {
			client = await setClientKind(client.id, harness);
			console.log(`Labelled it as a ${harness} harness`);
		}
	} else {
		const resolved = await resolveOrCreateClient(api, {
			name: clientName,
			kind: harness,
		});
		client = resolved.client;
		console.log(
			`${resolved.created ? 'Created' : 'Reusing'} client ${client.name} (${
				client.id
			})`,
		);
	}

	if (options.mcp) {
		const instanceId = resolveMcpInstanceId(
			await listMcpInstances(),
			options.mcp,
		);
		const outcome = await attachMcpInstance(api, client, instanceId);
		console.log(
			outcome === 'attached'
				? `Attached MCP instance ${instanceId}`
				: `MCP instance ${instanceId} was already attached`,
		);
		client = await getClient(client.id);
	}

	const mcpUrl = client.mcp_endpoint_url;
	if (!mcpUrl) {
		throw new Error(
			`The API returned no mcp_endpoint_url for client ${client.id}; check API_BASE_URL on the server`,
		);
	}

	const bundle = [
		`${client.mcp_instances?.length ?? 0} MCP instance(s)`,
		`${client.skills?.length ?? 0} skill(s)`,
	].join(', ');
	console.log(`Bundle: ${bundle}`);
	if (!client.mcp_instances?.length && !client.skills?.length) {
		console.log(
			'Warning: the bundle is empty — the harness will connect but see no tools.',
		);
	}

	const alias = options.alias ?? mcpAlias('default');
	await runHarnessCommand(
		harness,
		harnessAddArgs(harness, {alias, url: mcpUrl, scope}),
	);
	console.log(`Registered MCP server "${alias}" with ${harness}`);

	const loginArgs = harnessLoginArgs(harness, alias);
	if (loginArgs && options.login !== false) {
		await runHarnessCommand(harness, loginArgs);
	} else if (harness === 'claude') {
		console.log(
			`Authorize it from inside Claude Code: run /mcp and pick "${alias}".`,
		);
	}

	const now = new Date().toISOString();
	const statePath = await saveConnectionState({
		client: harness,
		clientId: client.id,
		clientName: client.name,
		alias,
		scope,
		apiUrl: options.apiUrl.replace(/\/$/, ''),
		mcpUrl,
		auth: 'oauth',
		connectedAt: now,
		updatedAt: now,
	});

	console.log('');
	console.log(
		'Model: harness -> client bundle -> Agentarea policy/router -> hosted MCP instances.',
	);
	console.log(
		'Change what the harness can reach in Agentarea; local config stays put.',
	);
	console.log(`Saved non-secret connection state: ${statePath}`);
	return true;
}
