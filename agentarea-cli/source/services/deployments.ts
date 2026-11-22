import {promises as fs} from 'node:fs';
import path from 'node:path';
import {normalizeApiUrl} from '../utils/apiUrl.js';

export const DEPLOYMENTS_FILE = '.agentarea/deployments.json';

export type Deployment = {
	api_url: string;
	workspace: string;
	install_id: string;
	name: string;
	deployed_at: string;
};

export type DeploymentsFile = {
	version: 1;
	deployments: Deployment[];
};

const FIELDS = [
	'api_url',
	'workspace',
	'install_id',
	'name',
	'deployed_at',
] as const;

/** The file's deployments; no file is none. Anything else unreadable throws. */
export function parseDeployments(text: string | undefined): DeploymentsFile {
	if (text === undefined) {
		return {version: 1, deployments: []};
	}

	let raw: unknown;
	try {
		raw = JSON.parse(text);
	} catch (error) {
		throw new Error(
			`${DEPLOYMENTS_FILE} is not valid JSON: ${(error as Error).message}`,
		);
	}

	const file = raw as {version?: unknown; deployments?: unknown};
	if (file?.version !== 1) {
		throw new Error(
			`${DEPLOYMENTS_FILE} has version ${String(
				file?.version,
			)}; this CLI reads version 1.`,
		);
	}

	if (!Array.isArray(file.deployments)) {
		throw new TypeError(`${DEPLOYMENTS_FILE}: "deployments" is not a list.`);
	}

	const deployments = file.deployments.map((item: unknown, index) => {
		const record = (item ?? {}) as Record<string, unknown>;
		for (const field of FIELDS) {
			if (typeof record[field] !== 'string' || record[field] === '') {
				throw new Error(
					`${DEPLOYMENTS_FILE}: deployments[${index}] has no ${field}.`,
				);
			}
		}

		return pick(record as Deployment);
	});
	return {version: 1, deployments};
}

function pick(deployment: Deployment): Deployment {
	return {
		api_url: deployment.api_url,
		workspace: deployment.workspace,
		install_id: deployment.install_id,
		name: deployment.name,
		deployed_at: deployment.deployed_at,
	};
}

const sameTarget = (
	deployment: Deployment,
	apiUrl: string,
	workspace: string,
) =>
	normalizeApiUrl(deployment.api_url) === normalizeApiUrl(apiUrl) &&
	deployment.workspace === workspace;

export function findDeployment(
	file: DeploymentsFile,
	apiUrl: string,
	workspace: string,
): Deployment | undefined {
	return file.deployments.find(deployment =>
		sameTarget(deployment, apiUrl, workspace),
	);
}

export function removeDeployment(
	file: DeploymentsFile,
	apiUrl: string,
	workspace: string,
): DeploymentsFile {
	return {
		version: 1,
		deployments: file.deployments.filter(
			deployment => !sameTarget(deployment, apiUrl, workspace),
		),
	};
}

/** One entry per (api_url, workspace), sorted so the file diffs cleanly. */
export function upsertDeployment(
	file: DeploymentsFile,
	deployment: Deployment,
): DeploymentsFile {
	const rest = removeDeployment(file, deployment.api_url, deployment.workspace);
	const deployments = [...rest.deployments, pick(deployment)].sort(
		(a, b) =>
			a.api_url.localeCompare(b.api_url) ||
			a.workspace.localeCompare(b.workspace),
	);
	return {version: 1, deployments};
}

export function formatDeployments(file: DeploymentsFile): string {
	return `${JSON.stringify(
		{version: 1, deployments: file.deployments.map(pick)},
		null,
		2,
	)}\n`;
}

export async function readDeployments(root: string): Promise<DeploymentsFile> {
	const text = await fs
		.readFile(path.join(root, DEPLOYMENTS_FILE), 'utf8')
		.catch((error: NodeJS.ErrnoException) => {
			if (error.code === 'ENOENT') {
				return undefined;
			}

			throw error;
		});
	return parseDeployments(text);
}

export async function writeDeployments(
	root: string,
	file: DeploymentsFile,
): Promise<void> {
	const target = path.join(root, DEPLOYMENTS_FILE);
	await fs.mkdir(path.dirname(target), {recursive: true});
	await fs.writeFile(target, formatDeployments(file));
}

export type IntoSource = 'flag' | 'env' | 'file';

/** The install to deploy into: `--into`, else AGENTAREA_BUNDLE_ID, else the deployments file. */
export function resolveInto(input: {
	flag?: unknown;
	env?: string;
	deployed?: Deployment;
}): {into?: string; source?: IntoSource} {
	if (input.flag !== undefined) {
		if (typeof input.flag !== 'string' || input.flag.trim() === '') {
			throw new Error('--into expects a bundle id or name.');
		}

		return {into: input.flag.trim(), source: 'flag'};
	}

	if (input.env?.trim()) {
		return {into: input.env.trim(), source: 'env'};
	}

	if (input.deployed) {
		return {into: input.deployed.install_id, source: 'file'};
	}

	return {};
}
