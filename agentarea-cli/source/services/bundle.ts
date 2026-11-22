import {execFile} from 'node:child_process';
import {promises as fs} from 'node:fs';
import path from 'node:path';
import {promisify} from 'node:util';
import {parse as parseYaml} from 'yaml';
import type {
	BundleAgent,
	BundleOrigin,
	ImportPreview,
} from '@agentarea/api-client';
import {formatPlan} from './agentFolder.js';

export const MANIFEST_FILE = 'agentarea.yaml';
export const LEGACY_MANIFEST_FILE = 'agent.yaml';

export function folderFormat(
	files: Record<string, string>,
): 'bundle' | 'legacy' | undefined {
	if (MANIFEST_FILE in files) {
		return 'bundle';
	}

	return LEGACY_MANIFEST_FILE in files ? 'legacy' : undefined;
}

/**
 * The workspace and setup values `--target <name>` selects from the manifest's
 * `targets:`; `--set` values win over the target's `setup`.
 */
export function resolveTarget(
	manifest: string | undefined,
	target: string | undefined,
	given: Record<string, unknown>,
): {workspace?: string; setup: Record<string, unknown>} {
	if (target === undefined) {
		return {setup: given};
	}

	if (manifest === undefined) {
		throw new Error(`--target needs ${MANIFEST_FILE} with a targets section.`);
	}

	let parsed: unknown;
	try {
		parsed = parseYaml(manifest);
	} catch (error) {
		throw new Error(`${MANIFEST_FILE}: ${(error as Error).message}`);
	}

	const targets = (parsed as {targets?: unknown} | undefined)?.targets;
	if (!targets || typeof targets !== 'object' || Array.isArray(targets)) {
		throw new Error(
			`--target ${target} given, but ${MANIFEST_FILE} has no targets.`,
		);
	}

	const names = Object.keys(targets);
	const chosen = (targets as Record<string, unknown>)[target] as
		| {workspace?: unknown; setup?: unknown}
		| undefined;
	if (!names.includes(target)) {
		throw new Error(
			`Unknown target "${target}". ${MANIFEST_FILE} declares: ${names.join(
				', ',
			)}.`,
		);
	}

	if (typeof chosen?.workspace !== 'string' || !chosen.workspace) {
		throw new Error(`Target "${target}" in ${MANIFEST_FILE} has no workspace.`);
	}

	const setup =
		chosen.setup && typeof chosen.setup === 'object'
			? (chosen.setup as Record<string, unknown>)
			: {};
	return {workspace: chosen.workspace, setup: {...setup, ...given}};
}

export function formatBundleHeader(
	preview: Pick<ImportPreview, 'bundle' | 'install'>,
): string {
	const {install} = preview;
	if (!install) {
		return `Creates bundle ${preview.bundle.name}`;
	}

	let line = `Updates bundle ${install.name} (${install.id})`;
	const last = [install.updated_by, install.updated_at].filter(Boolean);
	if (last.length > 0) {
		line += `, last deployed by ${last.join(' ')}`;
	}

	const remote = install.origin?.git_remote;
	if (remote) {
		const commit = install.origin?.git_commit;
		line += ` from ${remote}${commit ? `@${commit.slice(0, 7)}` : ''}`;
	}

	return line;
}

function accessCell(current: string[], previous: string[] | undefined) {
	const cells =
		previous === undefined
			? current
			: [
					...current.map(item => (previous.includes(item) ? item : `+${item}`)),
					...previous
						.filter(item => !current.includes(item))
						.map(item => `-${item}`),
			  ];
	return cells.length > 0 ? cells.join(', ') : 'none';
}

/**
 * Per agent: the skills, MCP servers and delegates it reaches. Given the
 * previous bundle's agents, additions are marked `+`, removals `-`.
 */
export function formatAgentMatrix(
	agents: BundleAgent[],
	previous?: BundleAgent[],
): string[] {
	if (agents.length === 0) {
		return [];
	}

	const rows = agents.map(agent => {
		const before = previous?.find(item => item.key === agent.key);
		const known = previous === undefined || before !== undefined;
		const cell = (pick: (a: BundleAgent) => string[] | undefined) =>
			accessCell(
				pick(agent) ?? [],
				known && previous ? pick(before!) ?? [] : undefined,
			);
		return [
			known ? agent.key : `+${agent.key}`,
			cell(a => a.skills),
			cell(a => a.mcps),
			cell(a => a.delegates),
		];
	});
	const table = [['agent', 'skills', 'mcp', 'delegates'], ...rows];
	const widths = [0, 1, 2].map(column =>
		Math.max(...table.map(row => row[column]!.length)),
	);
	return [
		'Agents:',
		...table.map(row =>
			`  ${row
				.map((cell, column) => cell.padEnd(widths[column] ?? 0))
				.join('  ')}`.trimEnd(),
		),
	];
}

export function formatBundlePlan(
	preview: ImportPreview,
	previous?: BundleAgent[],
): string[] {
	return [
		formatBundleHeader(preview),
		...formatAgentMatrix(preview.bundle.agents ?? [], previous),
		...formatPlan(preview),
	];
}

export type ExistingStep =
	| {action: 'continue'}
	| {action: 'confirm_into'; into: string; question: string}
	| {action: 'confirm_recreate'; question: string}
	| {action: 'fail'; message: string};

export const BUNDLE_EXISTS = 'bundle_exists';
export const INSTALL_NOT_FOUND = 'bundle_install_not_found';
export const INSTALL_AMBIGUOUS = 'bundle_install_ambiguous';

/**
 * What to do when the plan collides with an install: a bundle of this name
 * already exists, or the install `into` named is gone. A terminal is asked;
 * anything else fails instead of deploying over someone's bundle.
 */
export function decideExisting(
	preview: Pick<ImportPreview, 'issues' | 'existing_install'>,
	context: {workspace: string; interactive: boolean; into?: string},
): ExistingStep {
	const issue = (code: string) =>
		(preview.issues ?? []).find(item => item.code === code);
	const ambiguous = issue(INSTALL_AMBIGUOUS);
	if (ambiguous) {
		return {
			action: 'fail',
			message: `${ambiguous.message}. Pass --into <install id>; nothing was deployed.`,
		};
	}

	const existing = preview.existing_install;
	if (issue(BUNDLE_EXISTS) && existing) {
		const who = existing.updated_by ?? existing.created_by;
		const last = [who, existing.updated_at].filter(Boolean).join(', ');
		const conflict = `Bundle "${existing.name}" already exists in workspace "${
			context.workspace
		}"${last ? ` (last deployed by ${last})` : ''}.`;
		if (context.into) {
			return {
				action: 'fail',
				message: `${conflict} Deploying into ${context.into} would rename it to that name; choose another name in agentarea.yaml. Nothing was deployed.`,
			};
		}

		return context.interactive
			? {
					action: 'confirm_into',
					into: existing.id,
					question: `${conflict} Deploy into it? [y/N] `,
			  }
			: {
					action: 'fail',
					message: `${conflict} Pass --into ${existing.name} to deploy into it; nothing was deployed.`,
			  };
	}

	if (issue(INSTALL_NOT_FOUND)) {
		const gone = `The bundle this folder deploys into (${
			context.into ?? 'unknown'
		}) no longer exists in workspace "${context.workspace}".`;
		return context.interactive
			? {
					action: 'confirm_recreate',
					question: `${gone} Create it again? [y/N] `,
			  }
			: {
					action: 'fail',
					message: `${gone} Pass --into <bundle> for another bundle, or remove its entry from .agentarea/deployments.json to create it again; nothing was deployed.`,
			  };
	}

	return {action: 'continue'};
}

export const PLAN_CHANGED_MESSAGE =
	'Someone deployed this bundle after the plan was made; run deploy again to see the new plan.';

/** Install's 409: the plan it was given is no longer the one it would carry out. */
export function isPlanChanged(error: unknown): boolean {
	return (
		(error as {code?: unknown} | undefined)?.code === 'bundle_plan_changed'
	);
}

export const DEPLOY_RUNNING_MESSAGE =
	'A deploy of this bundle is running; try again when it finishes. Nothing was deployed.';

/** Install's 409: another deploy of the same bundle holds it right now. */
export function isDeployRunning(error: unknown): boolean {
	return (
		(error as {code?: unknown} | undefined)?.code === 'bundle_deploy_running'
	);
}

/** A remote URL without the user name or token it may carry. */
export function stripCredentials(remote: string): string {
	let url: URL;
	try {
		url = new URL(remote);
	} catch {
		return remote;
	}

	url.username = '';
	url.password = '';
	return url.toString();
}

const run = promisify(execFile);

async function git(cwd: string, ...args: string[]): Promise<string> {
	const {stdout} = await run('git', args, {cwd, timeout: 3000});
	return stdout.trim();
}

/** Where the folder comes from in git, shown in the plan; undefined outside a repository. */
export async function readGitOrigin(
	root: string,
): Promise<BundleOrigin | undefined> {
	let top: string;
	try {
		top = await git(root, 'rev-parse', '--show-toplevel');
	} catch {
		return undefined;
	}

	const origin: BundleOrigin = {};
	const remote = await git(root, 'remote', 'get-url', 'origin').catch(() => '');
	if (remote) {
		origin.git_remote = stripCredentials(remote);
	}

	const commit = await git(root, 'rev-parse', 'HEAD').catch(() => '');
	if (commit) {
		origin.git_commit = commit;
	}

	const relative = path.relative(
		await fs.realpath(top),
		await fs.realpath(root),
	);
	origin.path = relative ? relative.split(path.sep).join('/') : '.';
	return origin;
}
