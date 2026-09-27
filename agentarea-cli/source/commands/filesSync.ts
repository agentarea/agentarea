import {promises as fs} from 'node:fs';
import path from 'node:path';
import {planWorkspaceUploadsV1FilesUploadUrlsPost} from '@agentarea/api-client';
import {
	DEFAULT_EXCLUDES,
	type PlannedUpload,
	type SyncSummary,
	chunk,
	collectFiles,
	mapLimit,
	remotePath,
	summarize,
} from '../services/fileSync.js';

// The server plans at most this many files per request.
const PLAN_BATCH = 100;
const UPLOAD_CONCURRENCY = 8;

function parseExcludes(raw: unknown): string[] {
	const extra =
		typeof raw === 'string'
			? raw
					.split(',')
					.map(item => item.trim())
					.filter(Boolean)
			: [];
	return [...DEFAULT_EXCLUDES, ...extra];
}

/**
 * `agentarea files sync <dir> [prefix]` — mirror a local folder into
 * workspace storage the way Vercel/Netlify deploys do: hash locally, ask the
 * server which digests it lacks, PUT only those straight to the object store.
 */
export async function runFilesSync(
	dir: string | undefined,
	prefix: string | undefined,
	flags: Record<string, unknown>,
): Promise<number> {
	if (!dir) {
		console.error(
			'Usage: agentarea files sync <dir> [remote-prefix] [--exclude=a,b] --workspace <slug>',
		);
		return 1;
	}

	const root = path.resolve(dir);
	const stat = await fs.stat(root).catch(() => undefined);
	if (!stat?.isDirectory()) {
		console.error(`Not a directory: ${root}`);
		return 1;
	}

	const files = await collectFiles(root, parseExcludes(flags['exclude']));
	const byRemote = new Map(
		files.map(file => [remotePath(prefix ?? '', file.relative), file]),
	);
	const summary: SyncSummary = {uploaded: 0, unchanged: 0, failed: []};

	for (const batch of chunk([...byRemote.entries()], PLAN_BATCH)) {
		// eslint-disable-next-line no-await-in-loop
		const {data, error} = await planWorkspaceUploadsV1FilesUploadUrlsPost({
			body: {
				files: batch.map(([remote, file]) => ({
					path: remote,
					sha256: file.sha256,
				})),
			},
		});
		if (error ?? !data) {
			console.error(`Upload plan failed: ${JSON.stringify(error)}`);
			return 1;
		}

		const uploads = data.uploads as PlannedUpload[];
		const toSend: PlannedUpload[] = [];
		for (const planned of uploads) {
			if (planned.status === 'unchanged') {
				summary.unchanged++;
			} else if (planned.status === 'upload' && planned.upload_url) {
				toSend.push(planned);
			} else {
				summary.failed.push({
					path: planned.path,
					error: planned.error ?? 'no upload URL',
				});
			}
		}

		// eslint-disable-next-line no-await-in-loop
		await mapLimit(toSend, UPLOAD_CONCURRENCY, async planned => {
			const file = byRemote.get(planned.path);
			if (!file) {
				summary.failed.push({path: planned.path, error: 'not in the manifest'});
				return;
			}

			const response = await fetch(planned.upload_url!, {
				method: planned.method ?? 'PUT',
				headers: planned.headers ?? {},
				body: await fs.readFile(file.absolute),
			});
			if (response.ok) {
				summary.uploaded++;
			} else {
				summary.failed.push({
					path: planned.path,
					error: `store answered ${response.status}`,
				});
			}
		});
	}

	for (const failure of summary.failed) {
		console.error(`  ${failure.path}: ${failure.error}`);
	}

	console.log(summarize(summary));
	return summary.failed.length > 0 ? 1 : 0;
}
