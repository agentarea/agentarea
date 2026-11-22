import path from 'node:path';
import {parse as parseYaml} from 'yaml';
import {scaffoldFiles} from './agentFolder.js';

export const ORG_FILE = 'agentarea.yaml';

export type OrgTeam = {name: string; workspace: string; path: string};
export type OrgLink = {from: string; to: string};
export type OrgShared = {include: string[]; exclude: string[]};
export type Org = {
	name: string;
	teams: OrgTeam[];
	shared?: OrgShared;
	links: OrgLink[];
};

const KEY = /^[a-zA-Z][a-zA-Z\d_-]*$/;
const ORG_KEYS = ['name', 'schema_version', 'teams', 'shared', 'links'];
const BUNDLE_KEYS = [
	'display_name',
	'description',
	'setup',
	'defaults',
	'targets',
	'agents',
	'mcp',
	'skills',
	'openapi',
	'policies',
	'schedules',
	'channels',
	'streams',
	'tasks',
	'projects',
	'workspace',
];

const isMapping = (value: unknown): value is Record<string, unknown> =>
	Boolean(value) && typeof value === 'object' && !Array.isArray(value);

function fail(message: string): never {
	throw new Error(`${ORG_FILE}: ${message}`);
}

function globList(value: unknown, field: string): string[] {
	const list = typeof value === 'string' ? [value] : value;
	if (
		!Array.isArray(list) ||
		list.some(item => typeof item !== 'string' || !item)
	) {
		fail(`${field} must be a glob or a list of globs`);
	}

	for (const glob of list as string[]) {
		try {
			globRegExp(glob);
		} catch (error) {
			fail(`${field} '${glob}' ${(error as Error).message}`);
		}
	}

	return list as string[];
}

function teamPath(team: string, value: unknown): string {
	if (value !== undefined && typeof value !== 'string') {
		fail(`team "${team}": path must be a folder name`);
	}

	const raw = ((value as string | undefined) ?? team)
		.replace(/^\.\//, '')
		.replace(/\/+$/, '');
	const normal = path.posix.normalize(raw);
	if (
		!raw ||
		normal === '.' ||
		normal.startsWith('../') ||
		normal === '..' ||
		path.posix.isAbsolute(normal)
	) {
		fail(
			`team "${team}": path ${String(value)} must be a folder inside the org`,
		);
	}

	return normal;
}

/** An agentarea.yaml with `teams:` describes an organization, not a bundle. */
export function isOrgManifest(text: string): boolean {
	try {
		const raw: unknown = parseYaml(text);
		return isMapping(raw) && 'teams' in raw;
	} catch {
		return false;
	}
}

/** The organization an agentarea.yaml with teams describes; anything it cannot deploy throws. */
export function parseOrg(text: string): Org {
	let raw: unknown;
	try {
		raw = parseYaml(text);
	} catch (error) {
		fail((error as Error).message);
	}

	if (!isMapping(raw)) {
		fail('must be a mapping');
	}

	for (const key of Object.keys(raw)) {
		if (BUNDLE_KEYS.includes(key)) {
			fail(
				`'${key}' belongs to a bundle: a file with teams describes the organization, so put ${key} in a team folder's agentarea.yaml`,
			);
		}

		if (!ORG_KEYS.includes(key)) {
			fail(
				`unknown key '${key}'; an organization takes ${ORG_KEYS.join(', ')}`,
			);
		}
	}

	if (raw['schema_version'] !== undefined && raw['schema_version'] !== 1) {
		fail('schema_version must be 1');
	}

	if (typeof raw['name'] !== 'string' || !raw['name']) {
		fail("name is required: the organization's name");
	}

	if (!isMapping(raw['teams']) || Object.keys(raw['teams']).length === 0) {
		fail('teams must map each team name to {workspace, path}');
	}

	const teams = Object.entries(raw['teams']).map(([name, value]) => {
		if (!KEY.test(name)) {
			fail(`team name '${name}' must match [a-zA-Z][a-zA-Z0-9_-]*`);
		}

		const team = isMapping(value) ? value : {};
		if (typeof team['workspace'] !== 'string' || !team['workspace']) {
			fail(`team "${name}" needs workspace, the slug it deploys to`);
		}

		return {
			name,
			workspace: team['workspace'],
			path: teamPath(name, team['path']),
		};
	});

	for (const a of teams) {
		for (const b of teams) {
			if (a === b) {
				continue;
			}

			if (a.path === b.path) {
				fail(`teams "${a.name}" and "${b.name}" use the same folder ${a.path}`);
			}

			if (b.path.startsWith(`${a.path}/`)) {
				fail(
					`team "${b.name}" (${b.path}) is inside team "${a.name}" (${a.path})`,
				);
			}
		}
	}

	let shared: OrgShared | undefined;
	if (raw['shared'] !== undefined && raw['shared'] !== null) {
		const value = raw['shared'];
		if (!isMapping(value) || value['include'] === undefined) {
			fail('shared must be {include, exclude}');
		}

		shared = {
			include: globList(value['include'], 'shared.include'),
			exclude:
				value['exclude'] === undefined
					? []
					: globList(value['exclude'], 'shared.exclude'),
		};
	}

	const names = new Set(teams.map(team => team.name));
	const rawLinks = raw['links'] ?? [];
	if (!Array.isArray(rawLinks)) {
		fail('links must be a list of {from, to}');
	}

	const links = rawLinks.map((link: unknown) => {
		const item = isMapping(link) ? link : {};
		const ends = [item['from'], item['to']];
		for (const end of ends) {
			if (typeof end !== 'string' || !/^[^/]+\/[^/]+$/.test(end)) {
				fail(
					`a link's from and to are <team>/<agent>, got ${JSON.stringify(end)}`,
				);
			}

			const team = end.split('/')[0]!;
			if (!names.has(team)) {
				fail(`link names team "${team}", which teams does not declare`);
			}
		}

		return {from: ends[0] as string, to: ends[1] as string};
	});

	return {name: raw['name'], teams, ...(shared ? {shared} : {}), links};
}

/** A folder-relative glob, matched the way the server matches includes. */
export function globRegExp(pattern: string): RegExp {
	const trimmed = pattern.replace(/^\.\//, '').replace(/\/$/, '');
	if (!trimmed || trimmed.startsWith('/') || trimmed.includes('\\')) {
		throw new Error('must be a relative path');
	}

	const segments = trimmed.split('/');
	let source = '^';
	for (const [index, segment] of segments.entries()) {
		const last = index === segments.length - 1;
		if (segment === '' || segment === '.' || segment === '..') {
			throw new Error('must stay inside the folder');
		}

		if (segment === '**') {
			source += last ? '.*' : '(?:[^/]+/)*';
			continue;
		}

		for (const char of segment) {
			source +=
				char === '*'
					? '[^/]*'
					: char === '?'
					? '[^/]'
					: char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		}

		if (!last) {
			source += '/';
		}
	}

	return new RegExp(`${source}$`);
}

const matcher = (globs: string[]) => {
	const patterns = globs.map(glob => globRegExp(glob));
	return (file: string) => patterns.some(pattern => pattern.test(file));
};

/** The org-level files shared.include selects, keyed by their path from the org root. */
export function selectShared(
	files: Record<string, string>,
	shared: OrgShared | undefined,
): Record<string, string> {
	if (!shared) {
		return {};
	}

	const included = matcher(shared.include);
	const excluded = matcher(shared.exclude);
	return Object.fromEntries(
		Object.entries(files).filter(
			([file]) => file !== ORG_FILE && included(file) && !excluded(file),
		),
	);
}

const SECTIONS = [
	'agents',
	'mcp',
	'skills',
	'policies',
	'schedules',
	'channels',
] as const;

/**
 * The shared files a team's agentarea.yaml includes, selected the way the
 * server selects them: a file by its path, a skill by its directory.
 */
export function teamSharedFiles(
	manifest: string,
	shared: Record<string, string>,
): Record<string, string> {
	const parsed: unknown = parseYaml(manifest);
	const data = isMapping(parsed) ? parsed : {};
	const picked = new Set<string>();
	for (const section of SECTIONS) {
		const value = data[section];
		if (!isMapping(value) || value['include'] === undefined) {
			continue;
		}

		const included = matcher(globList(value['include'], `${section}.include`));
		const excluded = matcher(
			value['exclude'] === undefined
				? []
				: globList(value['exclude'], `${section}.exclude`),
		);
		for (const file of Object.keys(shared)) {
			if (section !== 'skills') {
				if (included(file) && !excluded(file)) {
					picked.add(file);
				}

				continue;
			}

			if (path.posix.basename(file) !== 'SKILL.md' || !file.includes('/')) {
				continue;
			}

			const dir = path.posix.dirname(file);
			if (
				(included(dir) || included(file)) &&
				!excluded(dir) &&
				!excluded(file)
			) {
				for (const other of Object.keys(shared)) {
					if (other.startsWith(`${dir}/`)) {
						picked.add(other);
					}
				}
			}
		}
	}

	return Object.fromEntries(
		Object.keys(shared)
			.filter(file => picked.has(file))
			.sort()
			.map(file => [file, shared[file]!]),
	);
}

export function mergeShared(
	teamFiles: Record<string, string>,
	shared: Record<string, string>,
): Record<string, string> {
	for (const file of Object.keys(shared)) {
		if (file in teamFiles) {
			throw new Error(
				`${file} is both in the team folder and shared by the org; rename one of them.`,
			);
		}
	}

	return {...teamFiles, ...shared};
}

export function declaredSetupKeys(manifest: string): string[] {
	const parsed: unknown = parseYaml(manifest);
	const setup = isMapping(parsed) ? parsed['setup'] : undefined;
	return isMapping(setup) ? Object.keys(setup) : [];
}

/** Each team's share of the --set values: the keys its manifest declares. */
export function splitSetValues(
	given: Record<string, unknown>,
	teams: Array<{team: string; keys: string[]}>,
): Record<string, Record<string, unknown>> {
	const unknown = Object.keys(given).filter(
		key => !teams.some(team => team.keys.includes(key)),
	);
	if (unknown.length > 0) {
		throw new Error(
			`Unknown setup key(s): ${unknown.join(', ')}. No team declares them.`,
		);
	}

	return Object.fromEntries(
		teams.map(team => [
			team.team,
			Object.fromEntries(
				Object.entries(given).filter(([key]) => team.keys.includes(key)),
			),
		]),
	);
}

export function selectTeams(org: Org, only: string | undefined): OrgTeam[] {
	if (only === undefined) {
		return org.teams;
	}

	const team = org.teams.find(item => item.name === only);
	if (!team) {
		throw new Error(
			`Unknown team "${only}". ${ORG_FILE} declares: ${org.teams
				.map(item => item.name)
				.join(', ')}.`,
		);
	}

	return [team];
}

/** Flags that name one bundle, refused when a deploy covers several teams. */
export function checkOrgFlags(
	flags: Record<string, unknown>,
	bundleIdEnv: string | undefined,
): void {
	if (flags['target'] !== undefined) {
		throw new Error(
			'--target is for a bundle folder; an organization deploys each team to the workspace its teams: entry gives it.',
		);
	}

	if (flags['workspace'] !== undefined) {
		throw new Error(
			'--workspace is for a bundle folder; an organization deploys each team to the workspace its teams: entry gives it.',
		);
	}

	if (flags['onlyTeam'] === undefined) {
		if (flags['into'] !== undefined) {
			throw new Error('--into names one bundle; use it with --only-team.');
		}

		if (bundleIdEnv?.trim()) {
			throw new Error(
				'AGENTAREA_BUNDLE_ID names one bundle; unset it or deploy one team with --only-team.',
			);
		}
	}
}

export function formatTeamHeader(team: OrgTeam): string {
	return `== Team ${team.name}: workspace "${team.workspace}", folder ${team.path}/`;
}

export function formatLinks(links: OrgLink[]): string[] {
	if (links.length === 0) {
		return [];
	}

	return [
		'Links (not applied yet; cross-team links are not deployed):',
		...links.map(link => `  ${link.from} -> ${link.to}`),
	];
}

const MAIN_TEAM = 'main';

export function scaffoldOrgFiles(org: string): Record<string, string> {
	const files: Record<string, string> = {
		[ORG_FILE]: [
			`name: ${org}`,
			'schema_version: 1',
			'teams:',
			`  ${MAIN_TEAM}: {workspace: ${org}}`,
			'# Add a team per workspace, and shared: {include: ./shared/**} once',
			'# teams share MCP servers, skills or policies.',
			'',
		].join('\n'),
	};
	for (const [file, content] of Object.entries(scaffoldFiles(MAIN_TEAM))) {
		files[`${MAIN_TEAM}/${file}`] = content;
	}

	return files;
}
