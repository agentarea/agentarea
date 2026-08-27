import test from 'ava';
import {
	attachMcpInstance,
	codexProjectConfigPath,
	defaultClientName,
	harnessAddArgs,
	harnessLoginArgs,
	mcpAlias,
	resolveMcpInstanceId,
	resolveOrCreateClient,
	upsertCodexServer,
	type ClientApi,
	type ClientRecord,
} from './harness.js';

function api(overrides: Partial<ClientApi> = {}): ClientApi {
	return {
		async list() {
			return [];
		},
		async create() {
			throw new Error('create not stubbed');
		},
		async addMcp() {
			throw new Error('addMcp not stubbed');
		},
		...overrides,
	};
}

test('defaultClientName joins the machine name and the harness', t => {
	t.is(
		defaultClientName('Jamakase-MacBook.local', 'codex'),
		'jamakase-macbook-codex',
	);
	t.is(defaultClientName('box', 'claude'), 'box-claude');
});

test('mcpAlias namespaces non-default targets', t => {
	t.is(mcpAlias('default'), 'agentarea');
	t.is(mcpAlias('tg proxy'), 'agentarea_tg_proxy');
});

test('harnessAddArgs drives codex through its own CLI', t => {
	t.deepEqual(
		harnessAddArgs('codex', {
			alias: 'agentarea_tg',
			url: 'https://api.example.test/client-mcp/abc',
			scope: 'user',
		}),
		[
			'mcp',
			'add',
			'agentarea_tg',
			'--url',
			'https://api.example.test/client-mcp/abc',
		],
	);
});

test('harnessAddArgs drives claude with transport and scope', t => {
	t.deepEqual(
		harnessAddArgs('claude', {
			alias: 'agentarea_tg',
			url: 'https://api.example.test/client-mcp/abc',
			scope: 'user',
		}),
		[
			'mcp',
			'add',
			'--transport',
			'http',
			'--scope',
			'user',
			'agentarea_tg',
			'https://api.example.test/client-mcp/abc',
		],
	);
});

test('harnessLoginArgs is codex-only; claude authorizes from inside the app', t => {
	t.deepEqual(harnessLoginArgs('codex', 'agentarea_tg'), [
		'mcp',
		'login',
		'agentarea_tg',
	]);
	t.is(harnessLoginArgs('claude', 'agentarea_tg'), null);
});

test('resolveOrCreateClient reuses an existing client with the same name', async t => {
	const existing: ClientRecord = {
		id: 'client-1',
		name: 'box-codex',
		kind: 'codex',
	};
	const result = await resolveOrCreateClient(
		api({
			async list() {
				return [existing];
			},
		}),
		{name: 'box-codex', kind: 'codex'},
	);

	t.is(result.client.id, 'client-1');
	t.false(result.created);
});

test('resolveOrCreateClient creates one when the name is unknown', async t => {
	let created: unknown;
	const result = await resolveOrCreateClient(
		api({
			async list() {
				return [{id: 'other', name: 'someone-else', kind: 'codex'}];
			},
			async create(data) {
				created = data;
				return {id: 'client-new', name: data.name, kind: data.kind};
			},
		}),
		{name: 'box-codex', kind: 'codex'},
	);

	t.deepEqual(created, {name: 'box-codex', kind: 'codex'});
	t.is(result.client.id, 'client-new');
	t.true(result.created);
});

test('resolveMcpInstanceId matches by id and by unique name', t => {
	const instances = [
		{id: '659b1561-79bf-424d-b707-7897a4304c98', name: 'telegram'},
		{id: 'other-id', name: 'weather'},
	];

	t.is(
		resolveMcpInstanceId(instances, '659b1561-79bf-424d-b707-7897a4304c98'),
		'659b1561-79bf-424d-b707-7897a4304c98',
	);
	t.is(
		resolveMcpInstanceId(instances, 'telegram'),
		'659b1561-79bf-424d-b707-7897a4304c98',
	);
});

test('resolveMcpInstanceId refuses to guess', t => {
	const instances = [
		{id: 'a', name: 'telegram'},
		{id: 'b', name: 'telegram'},
	];

	t.throws(() => resolveMcpInstanceId(instances, 'telegram'), {
		message: /ambiguous/i,
	});
	t.throws(() => resolveMcpInstanceId(instances, 'nope'), {
		message: /telegram/,
	});
});

test('attachMcpInstance is idempotent against what the client already has', async t => {
	let calls = 0;
	const client: ClientRecord = {
		id: 'client-1',
		name: 'box-codex',
		kind: 'codex',
		mcp_instances: [{id: 'mcp-1', name: 'telegram'}],
	};

	t.is(
		await attachMcpInstance(
			api({
				async addMcp() {
					calls += 1;
				},
			}),
			client,
			'mcp-1',
		),
		'already-attached',
	);
	t.is(calls, 0);

	t.is(
		await attachMcpInstance(
			api({
				async addMcp() {
					calls += 1;
				},
			}),
			client,
			'mcp-2',
		),
		'attached',
	);
	t.is(calls, 1);
});

const PROJECT_URL = 'https://api.example.test/client-mcp/abc';

test('codexProjectConfigPath points at the project-scoped file codex reads', t => {
	t.is(codexProjectConfigPath('/repo'), '/repo/.codex/config.toml');
});

test('upsertCodexServer writes a managed block into an empty file', t => {
	const written = upsertCodexServer('', 'agentarea_tg', PROJECT_URL);

	t.is(
		written,
		[
			'# >>> agentarea-cli managed: agentarea_tg',
			'[mcp_servers.agentarea_tg]',
			`url = "${PROJECT_URL}"`,
			'# <<< agentarea-cli managed: agentarea_tg',
			'',
		].join('\n'),
	);
});

test('upsertCodexServer keeps unrelated config intact', t => {
	const existing = '[mcp_servers.other]\nurl = "https://other.test/mcp"\n';

	const written = upsertCodexServer(existing, 'agentarea_tg', PROJECT_URL);

	t.true(written.startsWith(existing.trimEnd()));
	t.true(written.includes('[mcp_servers.agentarea_tg]'));
	t.true(written.includes('[mcp_servers.other]'));
});

test('upsertCodexServer is idempotent and refreshes the url in place', t => {
	const once = upsertCodexServer('', 'agentarea_tg', PROJECT_URL);

	t.is(upsertCodexServer(once, 'agentarea_tg', PROJECT_URL), once);

	const moved = upsertCodexServer(
		once,
		'agentarea_tg',
		'https://api.example.test/client-mcp/xyz',
	);
	t.true(moved.includes('client-mcp/xyz'));
	t.false(moved.includes('client-mcp/abc'));
	t.is(moved.match(/\[mcp_servers\.agentarea_tg]/g)?.length, 1);
});

test('upsertCodexServer refuses to clobber a hand-written entry', t => {
	const existing =
		'[mcp_servers.agentarea_tg]\nurl = "https://hand.written/mcp"\n';

	t.throws(() => upsertCodexServer(existing, 'agentarea_tg', PROJECT_URL), {
		message: /unmanaged/i,
	});
});
