import test from 'ava';
import type {BundleAgent, ImportPreview} from '@agentarea/api-client';
import {
	decideExisting,
	folderFormat,
	formatAgentMatrix,
	formatBundleHeader,
	formatBundlePlan,
	isDeployRunning,
	isPlanChanged,
	resolveTarget,
	stripCredentials,
} from './bundle.js';

const agent = (
	key: string,
	access: Partial<Pick<BundleAgent, 'skills' | 'mcps' | 'delegates'>> = {},
): BundleAgent => ({key, name: key, ...access});

const preview = (overrides: Partial<ImportPreview> = {}): ImportPreview => ({
	bundle: {name: 'acme-content', agents: []},
	installable: true,
	entities: [],
	issues: [],
	...overrides,
});

test('folderFormat prefers agentarea.yaml and recognises the legacy agent.yaml', t => {
	t.is(folderFormat({'agentarea.yaml': '', 'agent.yaml': ''}), 'bundle');
	t.is(folderFormat({'agent.yaml': ''}), 'legacy');
	t.is(folderFormat({'agents/a.md': ''}), undefined);
});

const manifest = [
	'name: acme',
	'schema_version: 1',
	'targets:',
	'  dev: {workspace: acme-dev, mode: development}',
	'  prod:',
	'    workspace: acme',
	'    setup: {model: sonnet, region: eu}',
	'',
].join('\n');

test('resolveTarget without --target keeps the workspace flag and --set values', t => {
	t.deepEqual(resolveTarget(manifest, undefined, {model: 'x'}), {
		setup: {model: 'x'},
	});
});

test('resolveTarget takes the target workspace and lets --set win over its setup', t => {
	t.deepEqual(resolveTarget(manifest, 'prod', {model: 'opus'}), {
		workspace: 'acme',
		setup: {model: 'opus', region: 'eu'},
	});
	t.deepEqual(resolveTarget(manifest, 'dev', {}), {
		workspace: 'acme-dev',
		setup: {},
	});
});

test('resolveTarget refuses an unknown target, no targets, or a target without a workspace', t => {
	t.throws(() => resolveTarget(manifest, 'staging', {}), {
		message: /Unknown target "staging".*dev, prod/,
	});
	t.throws(() => resolveTarget('name: acme\n', 'prod', {}), {
		message: /no targets/,
	});
	t.throws(() => resolveTarget('targets:\n  prod: {}\n', 'prod', {}), {
		message: /prod.*workspace/,
	});
	t.throws(() => resolveTarget(undefined, 'prod', {}), {
		message: /agentarea\.yaml/,
	});
	t.throws(() => resolveTarget('targets: [\n', 'prod', {}), {
		message: /agentarea\.yaml/,
	});
});

test('formatBundleHeader names the install it updates, who deployed it and from where', t => {
	t.is(
		formatBundleHeader(
			preview({
				install: {
					id: 'inst-1',
					name: 'acme-content',
					updated_by: 'ann@acme.io',
					updated_at: '2026-11-20T10:00:00Z',
					origin: {
						git_remote: 'git@github.com:acme/agents.git',
						git_commit: 'abcdef1234567890', // pragma: allowlist secret
					},
				},
			}),
		),
		'Updates bundle acme-content (inst-1), last deployed by ann@acme.io 2026-11-20T10:00:00Z from git@github.com:acme/agents.git@abcdef1',
	);
	t.is(
		formatBundleHeader(
			preview({
				install: {
					id: 'inst-1',
					name: 'old-name',
					updated_by: 'ann@acme.io',
					updated_at: '2026-11-20T10:00:00Z',
				},
			}),
		),
		'Updates bundle old-name (inst-1), last deployed by ann@acme.io 2026-11-20T10:00:00Z',
	);
	t.is(formatBundleHeader(preview()), 'Creates bundle acme-content');
});

test('formatAgentMatrix lists every agent with its skills, MCP servers and delegates', t => {
	t.deepEqual(
		formatAgentMatrix([
			agent('lead', {mcps: ['telegram'], delegates: ['researcher', 'writer']}),
			agent('writer', {skills: ['brand-voice', 'pricing'], mcps: ['sheets']}),
		]),
		[
			'Agents:',
			'  agent   skills                mcp       delegates',
			'  lead    none                  telegram  researcher, writer',
			'  writer  brand-voice, pricing  sheets    none',
		],
	);
	t.deepEqual(formatAgentMatrix([]), []);
});

test('formatAgentMatrix marks what changed against the previous bundle', t => {
	t.deepEqual(
		formatAgentMatrix(
			[
				agent('writer', {skills: ['brand-voice', 'pricing'], mcps: ['sheets']}),
				agent('publisher', {mcps: ['telegram']}),
			],
			[agent('writer', {skills: ['brand-voice'], mcps: ['sheets', 'crm']})],
		),
		[
			'Agents:',
			'  agent       skills                 mcp           delegates',
			'  writer      brand-voice, +pricing  sheets, -crm  none',
			'  +publisher  none                   telegram      none',
		],
	);
});

test('formatBundlePlan puts the header and the matrix before the entity plan', t => {
	const lines = formatBundlePlan(
		preview({
			bundle: {name: 'acme-content', agents: [agent('lead')]},
			entities: [
				{kind: 'agent', key: 'lead', name: 'lead', status: 'will_create'},
			],
		}),
	);

	t.deepEqual(lines, [
		'Creates bundle acme-content',
		'Agents:',
		'  agent  skills  mcp   delegates',
		'  lead   none    none  none',
		'Create:',
		'  agent       lead',
	]);
});

const exists = preview({
	installable: false,
	issues: [
		{
			severity: 'block',
			code: 'bundle_exists',
			message: 'bundle "acme-content" already exists',
		},
	],
	existing_install: {
		id: 'inst-9',
		name: 'acme-content',
		created_by: 'bob@acme.io',
		updated_by: 'ann@acme.io',
		updated_at: '2026-11-20T10:00:00Z',
	},
});

test('decideExisting goes on when the plan has no install conflict', t => {
	t.deepEqual(
		decideExisting(preview(), {workspace: 'acme', interactive: true}),
		{action: 'continue'},
	);
});

test('decideExisting asks a terminal whether to deploy into the existing bundle', t => {
	t.deepEqual(decideExisting(exists, {workspace: 'acme', interactive: true}), {
		action: 'confirm_into',
		into: 'inst-9',
		question:
			'Bundle "acme-content" already exists in workspace "acme" (last deployed by ann@acme.io, 2026-11-20T10:00:00Z). Deploy into it? [y/N] ',
	});
});

test('decideExisting names the creator when nobody redeployed the bundle', t => {
	const created = {
		...exists,
		existing_install: {...exists.existing_install!, updated_by: null},
	};

	const step = decideExisting(created, {workspace: 'acme', interactive: true});

	t.true(
		step.action === 'confirm_into' &&
			step.question.includes('last deployed by bob@acme.io,'),
	);
});

test('decideExisting fails a non-interactive run until --into is passed', t => {
	const step = decideExisting(exists, {workspace: 'acme', interactive: false});

	t.is(step.action, 'fail');
	t.true(
		step.action === 'fail' &&
			step.message.includes('--into acme-content') &&
			step.message.includes('already exists in workspace "acme"'),
	);
});

const gone = preview({
	installable: false,
	issues: [
		{
			severity: 'block',
			code: 'bundle_install_not_found',
			message: 'bundle install inst-1 not found',
		},
	],
});

test('decideExisting offers a terminal to create a deleted bundle again', t => {
	t.deepEqual(
		decideExisting(gone, {
			workspace: 'acme',
			interactive: true,
			into: 'inst-1',
		}),
		{
			action: 'confirm_recreate',
			question:
				'The bundle this folder deploys into (inst-1) no longer exists in workspace "acme". Create it again? [y/N] ',
		},
	);
});

test('decideExisting fails a non-interactive run when the bundle was deleted', t => {
	const step = decideExisting(gone, {
		workspace: 'acme',
		interactive: false,
		into: 'inst-1',
	});

	t.true(
		step.action === 'fail' &&
			step.message.includes('(inst-1) no longer exists in workspace "acme"'),
	);
});

test('stripCredentials drops user info from URL remotes and keeps scp-style ones', t => {
	t.is(
		stripCredentials('https://x-access-token:ghs_abc@github.com/acme/a.git'), // pragma: allowlist secret
		'https://github.com/acme/a.git',
	);
	t.is(
		stripCredentials('https://token@gitlab.com/acme/a.git'),
		'https://gitlab.com/acme/a.git',
	);
	t.is(
		stripCredentials('git@github.com:acme/a.git'),
		'git@github.com:acme/a.git',
	);
	t.is(
		stripCredentials('https://github.com/acme/a.git'),
		'https://github.com/acme/a.git',
	);
});

test('decideExisting fails when the rename collides with another bundle', t => {
	const step = decideExisting(exists, {
		workspace: 'acme',
		interactive: true,
		into: 'inst-1',
	});

	t.true(
		step.action === 'fail' &&
			step.message.includes('already exists in workspace "acme"') &&
			step.message.includes('choose another name'),
	);
});

test('decideExisting fails on an --into name that matches several bundles', t => {
	const step = decideExisting(
		preview({
			installable: false,
			issues: [
				{
					severity: 'block',
					code: 'bundle_install_ambiguous',
					message: 'bundle name "team" matches installs a, b',
				},
			],
		}),
		{workspace: 'acme', interactive: true, into: 'team'},
	);

	t.deepEqual(step, {
		action: 'fail',
		message:
			'bundle name "team" matches installs a, b. Pass --into <install id>; nothing was deployed.',
	});
});

test('isPlanChanged recognises only the 409 bundle_plan_changed problem', t => {
	t.true(
		isPlanChanged({status: 409, code: 'bundle_plan_changed', detail: 'x'}),
	);
	t.false(isPlanChanged({status: 409, code: 'conflict'}));
	t.false(isPlanChanged(undefined));
	t.false(isPlanChanged(new Error('network')));
});

test('isDeployRunning recognises only the 409 bundle_deploy_running problem', t => {
	t.true(
		isDeployRunning({status: 409, code: 'bundle_deploy_running', detail: 'x'}),
	);
	t.false(isDeployRunning({status: 409, code: 'bundle_plan_changed'}));
	t.false(isDeployRunning(undefined));
});

test('formatBundlePlan prints the rename the server reports for an entity', t => {
	const lines = formatBundlePlan(
		preview({
			install: {
				id: 'inst-1',
				name: 'acme-content',
				updated_at: '2026-11-20T10:00:00Z',
			},
			entities: [
				{
					kind: 'agent',
					key: 'copywriter',
					name: 'copywriter',
					status: 'will_update',
					detail: 'renamed writer → copywriter',
				},
			],
		}),
	);

	t.true(
		lines.includes('  agent       copywriter  (renamed writer → copywriter)'),
	);
});
