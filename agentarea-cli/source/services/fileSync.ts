import {createHash} from 'node:crypto';
import {createReadStream, promises as fs} from 'node:fs';
import path from 'node:path';

export const DEFAULT_EXCLUDES = ['.git', 'node_modules', '.DS_Store'];

export type LocalFile = {
	relative: string;
	absolute: string;
	sha256: string;
};

export type PlannedUpload = {
	path: string;
	status: 'unchanged' | 'upload' | 'error';
	upload_url?: string | undefined;
	method?: string | undefined;
	headers?: Record<string, string> | undefined;
	error?: string | undefined;
};

async function sha256Of(file: string): Promise<string> {
	const hash = createHash('sha256');
	for await (const chunk of createReadStream(file)) {
		hash.update(chunk as Uint8Array);
	}

	return hash.digest('hex');
}

function isExcluded(relative: string, name: string, excludes: string[]) {
	return excludes.some(
		exclude =>
			exclude === name ||
			exclude === relative ||
			relative.startsWith(`${exclude}/`),
	);
}

/**
 * Every regular file under `root`, hashed, in a stable order. Symlinks are
 * skipped so a sync never follows a link out of the folder it was pointed at.
 */
export async function collectFiles(
	root: string,
	excludes: string[] = DEFAULT_EXCLUDES,
): Promise<LocalFile[]> {
	const found: LocalFile[] = [];

	async function walk(dir: string): Promise<void> {
		const entries = await fs.readdir(dir, {withFileTypes: true});
		for (const entry of entries) {
			const absolute = path.join(dir, entry.name);
			const relative = path.relative(root, absolute).split(path.sep).join('/');
			if (isExcluded(relative, entry.name, excludes)) {
				continue;
			}

			if (entry.isDirectory()) {
				// eslint-disable-next-line no-await-in-loop
				await walk(absolute);
			} else if (entry.isFile()) {
				// eslint-disable-next-line no-await-in-loop
				found.push({relative, absolute, sha256: await sha256Of(absolute)});
			}
		}
	}

	await walk(root);
	return found.sort((a, b) => a.relative.localeCompare(b.relative));
}

export function remotePath(prefix: string, relative: string): string {
	const clean = prefix.replace(/^\/+|\/+$/g, '');
	return clean ? `${clean}/${relative}` : relative;
}

export function chunk<T>(items: T[], size: number): T[][] {
	const batches: T[][] = [];
	for (let index = 0; index < items.length; index += size) {
		batches.push(items.slice(index, index + size));
	}

	return batches;
}

export type SyncSummary = {
	uploaded: number;
	unchanged: number;
	failed: Array<{path: string; error: string}>;
};

export function summarize(summary: SyncSummary): string {
	const parts = [
		`${summary.uploaded} uploaded`,
		`${summary.unchanged} unchanged`,
	];
	if (summary.failed.length > 0) {
		parts.push(`${summary.failed.length} failed`);
	}

	return parts.join(', ');
}

/** Run `task` over `items` with at most `limit` in flight. */
export async function mapLimit<T>(
	items: T[],
	limit: number,
	task: (item: T) => Promise<void>,
): Promise<void> {
	let next = 0;
	const workers = Array.from(
		{length: Math.min(limit, items.length)},
		async () => {
			while (next < items.length) {
				const item = items[next++] as T;
				// eslint-disable-next-line no-await-in-loop
				await task(item);
			}
		},
	);
	await Promise.all(workers);
}
