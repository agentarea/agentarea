import test from 'ava';
import {
	assertAlias,
	assertMcpUrl,
	attachMcpInstance,
	codexProjectConfigPath,
	defaultClientName,
	harnessAddArgs,
	harnessLoginArgs,
	mcpAlias,
	resolveMcpInstanceId,
	resolveOrCreateClient,
	tomlString,
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
			'startup_timeout_sec = 60',
			'tool_timeout_sec = 120',
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

test('upsertCodexServer budgets for a bundle that aggregates its members', t => {
	// Codex drops a server that misses its 10s startup budget, silently: no
	// tools, no error. A bundle's tools/list fans out to every member MCP.
	const written = upsertCodexServer('', 'agentarea_tg', PROJECT_URL);

	t.true(written.includes('startup_timeout_sec = 60'));
	t.true(written.includes('tool_timeout_sec = 120'));
});

test('upsertCodexServer refuses a URL that would break out of its TOML string', t => {
	// The url is the server's mcp_endpoint_url: a quote plus a newline would
	// otherwise add a codex MCP server that runs an arbitrary command.
	const injected =
		'https://api.example/client-mcp/x"\n[mcp_servers.pwn]\ncommand = "sh"\nargs = ["-c", "id > /tmp/pwned"]\n#';

	t.throws(() => upsertCodexServer('', 'agentarea', injected), {
		message: /control characters/,
	});
});

test('upsertCodexServer escapes quotes and backslashes in the url', t => {
	const written = upsertCodexServer(
		'',
		'agentarea',
		String.raw`https://api.example/client-mcp/x"y\z`,
	);

	t.true(
		written.includes(
			String.raw`url = "https://api.example/client-mcp/x\"y\\z"`,
		),
	);
	t.is(written.match(/^\[/gm)?.length, 1);
});

test('upsertCodexServer keeps $ patterns in a url literal when replacing', t => {
	const once = upsertCodexServer('', 'agentarea', PROJECT_URL);
	const existing = `[other]\nkey = 1\n\n${once}\n[tail]\nkey = 2\n`;

	const written = upsertCodexServer(
		existing,
		'agentarea',
		"https://api.example/x$'$&",
	);

	t.true(written.includes(`url = "https://api.example/x$'$&"`));
	t.is(written.match(/\[tail]/g)?.length, 1);
});

test('assertMcpUrl only accepts http(s) URLs without control characters', t => {
	t.is(assertMcpUrl(PROJECT_URL), PROJECT_URL);
	t.is(assertMcpUrl('http://localhost:8000/mcp'), 'http://localhost:8000/mcp');

	for (const bad of [
		'file:///etc/passwd',
		'javascript:alert(1)',
		'--url=https://evil.example',
		'not a url',
		'https://api.example/a\tb',
		'https://api.example/a\u007Fb',
	]) {
		t.throws(() => assertMcpUrl(bad), undefined, bad);
	}
});

test('harnessAddArgs refuses an injected url or alias before spawning', t => {
	t.throws(() =>
		harnessAddArgs('codex', {
			alias: 'agentarea',
			url: 'file:///etc/passwd',
			scope: 'user',
		}),
	);
	t.throws(() =>
		harnessAddArgs('claude', {
			alias: '--scope=user',
			url: PROJECT_URL,
			scope: 'user',
		}),
	);
});

test('assertAlias accepts TOML bare keys only', t => {
	t.is(assertAlias('agentarea_tg-proxy'), 'agentarea_tg-proxy');
	for (const bad of ['', 'a.b', 'a]\n[b', 'a b', '-x', 'a"b']) {
		t.throws(() => assertAlias(bad), undefined, bad);
	}

	t.throws(() => upsertCodexServer('', 'x]\n[mcp_servers.pwn', PROJECT_URL));
});

test('tomlString escapes backslash and quote and refuses control characters', t => {
	t.is(tomlString(String.raw`a\b"c`), String.raw`"a\\b\"c"`);
	t.throws(() => tomlString('a\nb'));
	t.throws(() => tomlString('a\u0000b'));
});
