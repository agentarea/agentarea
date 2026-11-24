import test from 'ava';
import {
	checkOrgFlags,
	declaredSetupKeys,
	formatLinks,
	formatTeamHeader,
	globRegExp,
	isOrgManifest,
	mergeShared,
	parseOrg,
	scaffoldOrgFiles,
	selectShared,
	selectTeams,
	splitSetValues,
	teamSharedFiles,
} from './org.js';

const orgYaml = [
	'name: acme',
	'teams:',
	'  marketing: {workspace: acme-marketing}',
	'  sales: {workspace: acme-sales, path: teams/sales}',
	'shared: {include: ./shared/**}',
	'links:',
	'  - {from: sales/closer, to: marketing/writer}',
	'',
].join('\n');

test('parseOrg reads teams in order with their folder, shared globs and links', t => {
	t.deepEqual(parseOrg(orgYaml), {
		name: 'acme',
		teams: [
			{name: 'marketing', workspace: 'acme-marketing', path: 'marketing'},
			{name: 'sales', workspace: 'acme-sales', path: 'teams/sales'},
		],
		shared: {include: ['./shared/**'], exclude: []},
		links: [{from: 'sales/closer', to: 'marketing/writer'}],
	});
});

test('parseOrg refuses what it cannot deploy', t => {
	const fails = (text: string, message: RegExp) => {
		t.throws(() => parseOrg(text), {message});
	};

	fails('teams: {a: {workspace: w}}\n', /name is required/);
	fails('name: acme\n', /teams/);
	fails('name: acme\nteams: {}\n', /teams/);
	fails('name: acme\nteams: {a: {}}\n', /team "a".*workspace/);
	fails('name: acme\nteams: {a: {workspace: w, path: ../x}}\n', /inside/);
	fails('name: acme\nteams: {a: {workspace: w, path: .}}\n', /inside/);
	fails(
		'name: acme\nteams: {a: {workspace: w, path: x}, b: {workspace: v, path: x}}\n',
		/same folder/,
	);
	fails(
		'name: acme\nteams: {a: {workspace: w, path: x}, b: {workspace: v, path: x/y}}\n',
		/inside/,
	);
	fails('name: acme\nteams: {a: {workspace: w}}\nowners: []\n', /owners/);
	fails('name: acme\nteams: {"1a": {workspace: w}}\n', /1a/);
	fails(
		'name: acme\nteams: {a: {workspace: w}}\nlinks: [{from: a, to: a/x}]\n',
		/<team>\/<agent>/,
	);
	fails(
		'name: acme\nteams: {a: {workspace: w}}\nlinks: [{from: a/x, to: b/y}]\n',
		/team "b"/,
	);
	fails('name: [\n', /agentarea\.yaml/);
	fails(
		'name: acme\nteams: {a: {workspace: w}}\nagents: {include: ./agents/*.md}\n',
		/agents.*team folder/,
	);
});

test('isOrgManifest: agentarea.yaml with teams is an organization, with bundle sections a bundle', t => {
	t.true(isOrgManifest(orgYaml));
	t.true(
		isOrgManifest(
			'name: acme\nschema_version: 1\nteams: {a: {workspace: w}}\n',
		),
	);
	t.false(
		isOrgManifest(
			'name: team\nschema_version: 1\nagents: {include: ./agents/*.md}\n',
		),
	);
	t.false(isOrgManifest('name: [\n'));
	t.false(isOrgManifest('- a\n'));
});

test('parseOrg takes an optional schema_version', t => {
	t.is(
		parseOrg('name: acme\nschema_version: 1\nteams: {a: {workspace: w}}\n')
			.name,
		'acme',
	);
	t.throws(
		() =>
			parseOrg('name: acme\nschema_version: 2\nteams: {a: {workspace: w}}\n'),
		{message: /schema_version/},
	);
});

test('globRegExp follows the server: * and ? in a segment, ** across, inside the folder', t => {
	t.true(globRegExp('./shared/mcp/*.yaml').test('shared/mcp/telegram.yaml'));
	t.false(globRegExp('./shared/mcp/*.yaml').test('shared/mcp/x/telegram.yaml'));
	t.true(globRegExp('shared/**').test('shared/skills/voice/SKILL.md'));
	t.true(globRegExp('shared/**/SKILL.md').test('shared/SKILL.md'));
	t.true(globRegExp('./skills/*/').test('skills/voice'));
	t.true(globRegExp('a?.md').test('ab.md'));
	t.throws(() => globRegExp('../shared/*'), {message: /inside the folder/});
	t.throws(() => globRegExp('/abs/*'), {message: /relative/});
});

const orgFiles = {
	'agentarea.yaml': orgYaml,
	'shared/mcp/telegram.yaml': 'name: telegram\n',
	'shared/mcp/sheets.yaml': 'name: sheets\n',
	'shared/skills/voice/SKILL.md': '---\nname: voice\n---\n',
	'shared/skills/voice/examples.md': 'x',
	'notes.md': 'not shared',
};

test('selectShared keeps the org files the shared globs select', t => {
	t.deepEqual(
		Object.keys(
			selectShared(orgFiles, {
				include: ['./shared/**'],
				exclude: ['./shared/mcp/sheets.yaml'],
			}),
		),
		[
			'shared/mcp/telegram.yaml',
			'shared/skills/voice/SKILL.md',
			'shared/skills/voice/examples.md',
		],
	);
	t.deepEqual(selectShared(orgFiles, undefined), {});
});

test('teamSharedFiles copies only what the team includes, a skill with its whole directory', t => {
	const shared = selectShared(orgFiles, {include: ['shared/**'], exclude: []});
	const manifest = [
		'name: sales',
		'schema_version: 1',
		'agents: {include: ./agents/*.md}',
		'mcp: {include: [./mcp/*.yaml, ./shared/mcp/telegram.yaml]}',
		'skills: {include: ./shared/skills/*/}',
		'',
	].join('\n');

	t.deepEqual(Object.keys(teamSharedFiles(manifest, shared)), [
		'shared/mcp/telegram.yaml',
		'shared/skills/voice/SKILL.md',
		'shared/skills/voice/examples.md',
	]);
	t.deepEqual(
		teamSharedFiles(
			'name: s\nmcp: {include: ./shared/**, exclude: ./shared/mcp/*}\n',
			shared,
		),
		{
			'shared/skills/voice/SKILL.md': '---\nname: voice\n---\n',
			'shared/skills/voice/examples.md': 'x',
		},
	);
});

test('mergeShared adds shared files and refuses one the team folder already has', t => {
	t.deepEqual(mergeShared({'agentarea.yaml': 'a'}, {'shared/x.yaml': 'x'}), {
		'agentarea.yaml': 'a',
		'shared/x.yaml': 'x',
	});
	t.throws(
		() => mergeShared({'shared/x.yaml': 'mine'}, {'shared/x.yaml': 'org'}),
		{message: /shared\/x\.yaml/},
	);
});

test('declaredSetupKeys lists the setup keys a team manifest declares', t => {
	t.deepEqual(
		declaredSetupKeys(
			'name: a\nsetup:\n  model: {label: M}\n  token: {label: T}\n',
		),
		['model', 'token'],
	);
	t.deepEqual(declaredSetupKeys('name: a\n'), []);
});

test('splitSetValues gives each team the --set values it declares and refuses a key no team has', t => {
	t.deepEqual(
		splitSetValues({model: 'm', token: 't'}, [
			{team: 'marketing', keys: ['model']},
			{team: 'sales', keys: ['model', 'token']},
		]),
		{marketing: {model: 'm'}, sales: {model: 'm', token: 't'}},
	);
	t.throws(
		() => splitSetValues({modle: 'x'}, [{team: 'sales', keys: ['model']}]),
		{message: /modle/},
	);
});

test('selectTeams takes every team, or the one --only-team names', t => {
	const org = parseOrg(orgYaml);

	t.deepEqual(
		selectTeams(org, undefined).map(team => team.name),
		['marketing', 'sales'],
	);
	t.deepEqual(
		selectTeams(org, 'sales').map(team => team.name),
		['sales'],
	);
	t.throws(() => selectTeams(org, 'finance'), {
		message: /Unknown team "finance".*marketing, sales/,
	});
});

test('checkOrgFlags refuses one-bundle flags for a whole organization', t => {
	t.notThrows(() => {
		checkOrgFlags({}, undefined);
	});
	t.throws(
		() => {
			checkOrgFlags({target: 'prod'}, undefined);
		},
		{message: /--target/},
	);
	t.throws(
		() => {
			checkOrgFlags({workspace: 'acme'}, undefined);
		},
		{message: /--workspace/},
	);
	t.throws(
		() => {
			checkOrgFlags({into: 'x'}, undefined);
		},
		{message: /--only-team/},
	);
	t.throws(
		() => {
			checkOrgFlags({}, 'x');
		},
		{message: /AGENTAREA_BUNDLE_ID/},
	);
	t.notThrows(() => {
		checkOrgFlags({into: 'x', onlyTeam: 'sales'}, 'y');
	});
});

test('formatTeamHeader and formatLinks', t => {
	t.is(
		formatTeamHeader({
			name: 'sales',
			workspace: 'acme-sales',
			path: 'teams/sales',
		}),
		'== Team sales: workspace "acme-sales", folder teams/sales/',
	);
	t.deepEqual(formatLinks([{from: 'sales/closer', to: 'marketing/writer'}]), [
		'Links (not applied yet; cross-team links are not deployed):',
		'  sales/closer -> marketing/writer',
	]);
	t.deepEqual(formatLinks([]), []);
});

test('scaffoldOrgFiles writes the organization agentarea.yaml and one team bundle that parse', t => {
	const files = scaffoldOrgFiles('acme');

	t.deepEqual(Object.keys(files), [
		'agentarea.yaml',
		'main/agentarea.yaml',
		'main/agents/main.md',
	]);
	t.deepEqual(parseOrg(files['agentarea.yaml']!).teams, [
		{name: 'main', workspace: 'acme', path: 'main'},
	]);
});
