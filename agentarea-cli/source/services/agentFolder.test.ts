import {promises as fs} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'ava';
import type {PreviewEntity, SetupField} from '@agentarea/api-client';
import {
	MAX_FOLDER_BYTES,
	decodeText,
	describeApiError,
	formatInstallResult,
	formatPlan,
	groupPlan,
	hasBlockingIssues,
	looksBinary,
	parseSetFlags,
	payloadBytes,
	readAgentFolder,
	resolveSetup,
	scaffoldFiles,
	slugifyName,
} from './agentFolder.js';

async function tree(files: Record<string, string | Uint8Array>) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), 'aa-folder-'));
	for (const [relative, content] of Object.entries(files)) {
		const absolute = path.join(root, relative);
		// eslint-disable-next-line no-await-in-loop
		await fs.mkdir(path.dirname(absolute), {recursive: true});
		// eslint-disable-next-line no-await-in-loop
		await fs.writeFile(absolute, content);
	}

	return root;
}

const entity = (
	status: PreviewEntity['status'],
	name: string,
	kind: PreviewEntity['kind'] = 'agent',
): PreviewEntity => ({kind, key: name, name, status});

test('readAgentFolder keeps text files under posix paths', async t => {
	const root = await tree({
		'agent.yaml': 'name: a\n',
		'skills/research/SKILL.md': '# research',
		'schedules/daily.md': '---\ncron: "0 9 * * *"\n---\nreport',
	});

	const {files, skipped} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), [
		'agent.yaml',
		'schedules/daily.md',
		'skills/research/SKILL.md',
	]);
	t.is(files['skills/research/SKILL.md'], '# research');
	t.deepEqual(skipped, []);
});

test('readAgentFolder skips dotfiles, dot directories and node_modules', async t => {
	const root = await tree({
		'agent.yaml': 'name: a\n',
		'.env': 'SECRET=1',
		'.git/HEAD': 'ref',
		'node_modules/x/index.js': 'x',
		'skills/.cache/y': 'y',
	});

	const {files} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), ['agent.yaml']);
});

test('readAgentFolder reports binary and non-UTF-8 files instead of sending them', async t => {
	const root = await tree({
		'agent.yaml': 'name: a\n',
		'logo.png': new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01]),
		'latin1.txt': new Uint8Array([0x63, 0x61, 0x66, 0xe9]),
	});

	const {files, skipped} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), ['agent.yaml']);
	t.deepEqual(skipped, ['latin1.txt', 'logo.png']);
});

test('readAgentFolder refuses a folder over the API size cap', async t => {
	const root = await tree({
		'agent.yaml': 'name: a\n',
		'big.md': 'x'.repeat(MAX_FOLDER_BYTES),
	});

	await t.throwsAsync(readAgentFolder(root), {
		message: /5\.0MB limit.*big\.md/,
	});
});

test('readAgentFolder skips an oversized binary file instead of hitting the size cap', async t => {
	// Bigger than the cap, but it never reaches the cap check or a full read:
	// the NUL near the start is caught by the small prefix probe.
	const binary = new Uint8Array(MAX_FOLDER_BYTES + 1024).fill(0x61);
	binary[0] = 0x89;
	binary[1] = 0;

	const root = await tree({
		'agent.yaml': 'name: a\n',
		'huge.bin': binary,
	});

	const {files, skipped} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), ['agent.yaml']);
	t.deepEqual(skipped, ['huge.bin']);
});

test('readAgentFolder skips an oversized non-UTF-8 file instead of hitting the size cap', async t => {
	// No NUL byte, so only decoding tells it apart from text; the bad byte is last.
	const size = MAX_FOLDER_BYTES + 1024;
	const latin1 = new Uint8Array(size).fill(0x61);
	latin1[size - 1] = 0xe9;

	const root = await tree({
		'agent.yaml': 'name: a\n',
		'dump.txt': latin1,
	});

	const {files, skipped} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), ['agent.yaml']);
	t.deepEqual(skipped, ['dump.txt']);
});

test('readAgentFolder still catches a NUL byte past the binary probe window', async t => {
	// Well past any reasonably small prefix probe, so this only gets caught by
	// decoding the full file after the size cap check passes.
	const size = 256 * 1024;
	const bytes = new Uint8Array(size).fill(0x61);
	bytes[size - 1] = 0;

	const root = await tree({
		'agent.yaml': 'name: a\n',
		'late-nul.bin': bytes,
	});

	const {files, skipped} = await readAgentFolder(root);

	t.deepEqual(Object.keys(files), ['agent.yaml']);
	t.deepEqual(skipped, ['late-nul.bin']);
});

test('payloadBytes counts paths and contents as UTF-8 bytes', t => {
	t.is(payloadBytes({'a.md': 'é'}), 4 + 2);
});

test('decodeText rejects NUL bytes and invalid UTF-8', t => {
	t.is(decodeText(new TextEncoder().encode('héllo')), 'héllo');
	t.is(decodeText(new Uint8Array([0x61, 0x00])), undefined);
	t.is(decodeText(new Uint8Array([0xff, 0xfe, 0x41])), undefined);
});

test('looksBinary flags only a sample with a NUL byte', t => {
	t.true(looksBinary(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01])));
	t.false(looksBinary(new TextEncoder().encode('plain text')));
	t.false(looksBinary(new Uint8Array()));
});

test('parseSetFlags splits on the first = and keeps the rest of the value', t => {
	t.deepEqual(parseSetFlags(undefined), {});
	t.deepEqual(parseSetFlags('token=a=b'), {token: 'a=b'});
	t.deepEqual(parseSetFlags(['a=1', 'b=']), {a: '1', b: ''});
});

test('parseSetFlags rejects malformed and repeated keys', t => {
	t.throws(() => parseSetFlags(['novalue']), {message: /key=value/});
	t.throws(() => parseSetFlags(['=x']), {message: /key=value/});
	t.throws(() => parseSetFlags(['a=1', 'a=2']), {message: /more than once/});
});

const fields: SetupField[] = [
	{key: 'model', label: 'Model', required: true},
	{key: 'token', label: 'Token', required: true, type: 'secret'},
	{key: 'region', label: 'Region', required: true, default: 'eu'},
	{key: 'note', label: 'Note'},
];

test('resolveSetup overlays --set values on declared defaults', t => {
	const {values, missing} = resolveSetup(fields, {model: 'm-1', token: 't'});

	t.deepEqual(values, {region: 'eu', model: 'm-1', token: 't'});
	t.deepEqual(missing, []);
});

test('resolveSetup lists required fields still without a value', t => {
	const {missing} = resolveSetup(fields, {model: '  '});

	t.deepEqual(
		missing.map(field => field.key),
		['model', 'token'],
	);
});

test('resolveSetup rejects keys the folder does not declare', t => {
	t.throws(() => resolveSetup(fields, {modle: 'x'}), {
		message: /modle.*declares: model, token, region, note/,
	});
	t.throws(() => resolveSetup([], {a: '1'}), {message: /declares: none/});
});

test('groupPlan orders by status and drops empty groups', t => {
	const groups = groupPlan([
		entity('unchanged', 'c'),
		entity('will_create', 'a'),
		entity('orphaned', 'd'),
		entity('will_update', 'b'),
	]);

	t.deepEqual(
		groups.map(group => [group.status, group.entities.map(e => e.name)]),
		[
			['will_create', ['a']],
			['will_update', ['b']],
			['unchanged', ['c']],
			['orphaned', ['d']],
		],
	);
});

test('groupPlan keeps a status it does not know instead of hiding it', t => {
	const groups = groupPlan([
		entity('will_create', 'a'),
		{...entity('will_create', 'b'), status: 'brand_new' as never},
	]);

	t.deepEqual(
		groups.map(group => group.label),
		['Create', 'brand_new'],
	);
});

test('formatPlan prints groups, details and issues', t => {
	const lines = formatPlan({
		entities: [
			entity('will_create', 'helper'),
			{...entity('changes_not_applied', 'github', 'mcp'), detail: 'json_spec'},
		],
		issues: [{severity: 'warn', message: 'notes.txt: not part of the layout'}],
	});

	t.deepEqual(lines, [
		'Create:',
		'  agent       helper',
		'Not applied (changes are not deployed yet):',
		'  mcp         github  (json_spec)',
		'Issues:',
		'  WARN  notes.txt: not part of the layout',
	]);
});

test('hasBlockingIssues trusts both installable and block issues', t => {
	t.false(hasBlockingIssues({installable: true, issues: []}));
	t.true(hasBlockingIssues({installable: false, issues: []}));
	t.true(
		hasBlockingIssues({
			installable: true,
			issues: [{severity: 'block', message: 'no model'}],
		}),
	);
});

test('formatInstallResult lists entities and counts actions', t => {
	const lines = formatInstallResult({
		bundle_name: 'helper',
		entities: [
			{kind: 'agent', key: 'agent', name: 'helper', action: 'updated'},
			{kind: 'skill', key: 'r', name: 'research', action: 'created'},
			{kind: 'automation', key: 'd', name: 'daily', action: 'created'},
		],
	});

	t.deepEqual(lines, [
		'  updated    agent       helper',
		'  created    skill       research',
		'  created    automation  daily',
		'Deployed helper: 1 updated, 2 created',
	]);
});

test('describeApiError reads every FastAPI detail shape', t => {
	t.is(describeApiError(new Error('no workspace')), 'no workspace');
	t.is(
		describeApiError({detail: 'agent.yaml: missing'}),
		'agent.yaml: missing',
	);
	t.is(
		describeApiError({
			detail: [{loc: ['body', 'files'], msg: 'agent folder exceeds 5MB limit'}],
		}),
		'body.files: agent folder exceeds 5MB limit',
	);
	t.is(
		describeApiError({
			detail: {
				message: 'missing required setup',
				issues: [{message: "required setup field 'model' is missing"}],
			},
		}),
		"missing required setup\n  required setup field 'model' is missing",
	);
	t.is(
		describeApiError({
			detail: 'package is not installable',
			issues: [{message: "model 'x' does not exist"}],
		}),
		"package is not installable\n  model 'x' does not exist",
	);
	t.is(
		describeApiError({
			detail: 'Request validation failed',
			errors: [{loc: ['body', 'files'], msg: 'agent folder exceeds 5MB limit'}],
		}),
		'Request validation failed\n  body.files: agent folder exceeds 5MB limit',
	);
});

test('slugifyName derives a bundle name from a directory name', t => {
	t.is(slugifyName('My Agent_v2'), 'my-agent-v2');
	t.throws(() => slugifyName('___'), {message: /Cannot derive/});
});

test('scaffoldFiles writes a folder whose model comes from setup', t => {
	const files = scaffoldFiles('helper');

	t.deepEqual(Object.keys(files), ['agent.yaml', 'instructions.md']);
	t.true(files['agent.yaml']!.startsWith('name: helper\n'));
	t.true(files['agent.yaml']!.includes('model: ${setup.model}'));
	t.true(files['agent.yaml']!.includes('  - key: model\n'));
});
