import {promises as fs} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'ava';
import {
	DEPLOYMENTS_FILE,
	type Deployment,
	findDeployment,
	formatDeployments,
	parseDeployments,
	readDeployments,
	removeDeployment,
	resolveInto,
	upsertDeployment,
	writeDeployments,
} from './deployments.js';

const entry = (overrides: Partial<Deployment> = {}): Deployment => ({
	api_url: 'https://api.agentarea.ai',
	workspace: 'acme',
	install_id: 'inst-1',
	name: 'acme-content',
	deployed_at: '2026-11-22T10:00:00.000Z',
	...overrides,
});

test('parseDeployments reads no file as no deployments', t => {
	t.deepEqual(parseDeployments(undefined), {version: 1, deployments: []});
});

test('parseDeployments refuses broken JSON, another version and malformed entries', t => {
	t.throws(() => parseDeployments('{'), {message: /deployments\.json/});
	t.throws(() => parseDeployments('{"version": 2, "deployments": []}'), {
		message: /version 2/,
	});
	t.throws(
		() =>
			parseDeployments(
				'{"version": 1, "deployments": [{"api_url": "x", "workspace": "w"}]}',
			),
		{message: /install_id/},
	);
});

test('findDeployment matches api_url and workspace, ignoring a trailing slash', t => {
	const file = {
		version: 1 as const,
		deployments: [entry(), entry({workspace: 'acme-dev', install_id: 'dev'})],
	};

	t.is(
		findDeployment(file, 'https://api.agentarea.ai/', 'acme-dev')?.install_id,
		'dev',
	);
	t.is(findDeployment(file, 'http://localhost:8000', 'acme'), undefined);
});

test('upsertDeployment replaces the entry for the same api_url and workspace', t => {
	const first = upsertDeployment(parseDeployments(undefined), entry());
	const local = upsertDeployment(
		first,
		entry({api_url: 'http://localhost:8000', install_id: 'local'}),
	);
	const updated = upsertDeployment(
		local,
		entry({install_id: 'inst-1', name: 'renamed', deployed_at: 'later'}),
	);

	t.deepEqual(
		updated.deployments.map(d => [d.api_url, d.install_id, d.name]),
		[
			['http://localhost:8000', 'local', 'acme-content'],
			['https://api.agentarea.ai', 'inst-1', 'renamed'],
		],
	);
});

test('removeDeployment drops only the matching entry', t => {
	const file = upsertDeployment(
		upsertDeployment(parseDeployments(undefined), entry()),
		entry({workspace: 'other'}),
	);

	t.deepEqual(
		removeDeployment(file, 'https://api.agentarea.ai', 'acme').deployments.map(
			d => d.workspace,
		),
		['other'],
	);
});

test('formatDeployments is 2-space JSON with a trailing newline and a fixed key order', t => {
	const text = formatDeployments(
		upsertDeployment(parseDeployments(undefined), {
			deployed_at: 'when',
			name: 'n',
			install_id: 'i',
			workspace: 'w',
			api_url: 'u',
		}),
	);

	t.is(
		text,
		[
			'{',
			'  "version": 1,',
			'  "deployments": [',
			'    {',
			'      "api_url": "u",',
			'      "workspace": "w",',
			'      "install_id": "i",',
			'      "name": "n",',
			'      "deployed_at": "when"',
			'    }',
			'  ]',
			'}',
			'',
		].join('\n'),
	);
});

test('readDeployments and writeDeployments round-trip through .agentarea/', async t => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), 'aa-deployments-'));

	t.deepEqual(await readDeployments(root), {version: 1, deployments: []});

	const file = upsertDeployment(parseDeployments(undefined), entry());
	await writeDeployments(root, file);

	t.deepEqual(await readDeployments(root), file);
	t.is(
		await fs.readFile(path.join(root, DEPLOYMENTS_FILE), 'utf8'),
		formatDeployments(file),
	);
});

test('resolveInto: --into wins over the env, the env over the file', t => {
	const deployed = entry({install_id: 'from-file'});

	t.deepEqual(resolveInto({flag: 'flag', env: 'env', deployed}), {
		into: 'flag',
		source: 'flag',
	});
	t.deepEqual(resolveInto({env: 'env', deployed}), {
		into: 'env',
		source: 'env',
	});
	t.deepEqual(resolveInto({deployed}), {into: 'from-file', source: 'file'});
	t.deepEqual(resolveInto({}), {});
});

test('resolveInto treats an empty env as unset and refuses an empty --into', t => {
	t.deepEqual(resolveInto({env: '  '}), {});
	t.throws(() => resolveInto({flag: ''}), {message: /--into/});
	t.throws(() => resolveInto({flag: true}), {message: /--into/});
});
