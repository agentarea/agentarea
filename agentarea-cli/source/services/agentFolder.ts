import {promises as fs} from 'node:fs';
import path from 'node:path';
import type {
	EntityStatus,
	ImportPreview,
	InstallResult,
	PreviewEntity,
	SetupField,
} from '@agentarea/api-client';

// Same ceiling the API enforces on `files`: paths plus contents, UTF-8 bytes.
export const MAX_FOLDER_BYTES = 5 * 1024 * 1024;

const SKIPPED_NAMES = new Set(['node_modules']);

export function isSkipped(name: string): boolean {
	return name.startsWith('.') || SKIPPED_NAMES.has(name);
}

const utf8 = new TextDecoder('utf-8', {fatal: true});

/** The file's text, or undefined for binary (NUL bytes) or non-UTF-8 content. */
export function decodeText(bytes: Uint8Array): string | undefined {
	if (bytes.includes(0)) {
		return undefined;
	}

	try {
		return utf8.decode(bytes);
	} catch {
		return undefined;
	}
}

/** A NUL byte anywhere in the sample is a reliable binary signal. */
export function looksBinary(sample: Uint8Array): boolean {
	return sample.includes(0);
}

// Big enough to catch a NUL near the start of real binaries (images,
// archives, ...) without reading past it on a huge file.
const BINARY_PROBE_BYTES = 8192;

/** Peek at a file's first bytes to flag it as binary without reading it fully. */
async function isBinaryFile(absolute: string): Promise<boolean> {
	const handle = await fs.open(absolute, 'r');
	try {
		const buffer = Buffer.alloc(BINARY_PROBE_BYTES);
		const {bytesRead} = await handle.read(buffer, 0, BINARY_PROBE_BYTES, 0);
		return looksBinary(buffer.subarray(0, bytesRead));
	} finally {
		await handle.close();
	}
}

/** Whether the whole file decodes as text, checked in chunks so a huge file is never held in memory. */
async function isTextFile(absolute: string): Promise<boolean> {
	const decoder = new TextDecoder('utf-8', {fatal: true});
	const handle = await fs.open(absolute, 'r');
	try {
		const buffer = Buffer.alloc(64 * 1024);
		for (;;) {
			// eslint-disable-next-line no-await-in-loop
			const {bytesRead} = await handle.read(buffer, 0, buffer.length, null);
			if (bytesRead === 0) {
				decoder.decode();
				return true;
			}

			const chunk = buffer.subarray(0, bytesRead);
			if (chunk.includes(0)) {
				return false;
			}

			decoder.decode(chunk, {stream: true});
		}
	} catch (error) {
		if (error instanceof TypeError) {
			return false;
		}

		throw error;
	} finally {
		await handle.close();
	}
}

export function payloadBytes(files: Record<string, string>): number {
	let total = 0;
	for (const [relative, text] of Object.entries(files)) {
		total += Buffer.byteLength(relative) + Buffer.byteLength(text);
	}

	return total;
}

function megabytes(bytes: number): string {
	return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export type AgentFolder = {
	files: Record<string, string>;
	skipped: string[];
};

/**
 * Every text file under `root` keyed by its POSIX path. Dotfiles, dot
 * directories and node_modules are left out; symlinks are not followed;
 * binary or non-UTF-8 files come back in `skipped`.
 */
export async function readAgentFolder(root: string): Promise<AgentFolder> {
	const files: Record<string, string> = {};
	const skipped: string[] = [];
	let total = 0;

	async function walk(dir: string): Promise<void> {
		const entries = await fs.readdir(dir, {withFileTypes: true});
		entries.sort((a, b) => a.name.localeCompare(b.name));
		for (const entry of entries) {
			if (isSkipped(entry.name)) {
				continue;
			}

			const absolute = path.join(dir, entry.name);
			const relative = path.relative(root, absolute).split(path.sep).join('/');
			if (entry.isDirectory()) {
				// eslint-disable-next-line no-await-in-loop
				await walk(absolute);
				continue;
			}

			if (!entry.isFile()) {
				continue;
			}

			// eslint-disable-next-line no-await-in-loop
			const stats = await fs.stat(absolute);

			// eslint-disable-next-line no-await-in-loop
			if (await isBinaryFile(absolute)) {
				skipped.push(relative);
				continue;
			}

			// The file's on-disk size is the exact UTF-8 byte count once decoded
			// (decoding and re-encoding valid UTF-8 round-trips byte for byte), so
			// the cap can be enforced from `stats.size` before reading the file.
			if (total + Buffer.byteLength(relative) + stats.size > MAX_FOLDER_BYTES) {
				// A file that would not have been sent cannot be what crosses the cap.
				// eslint-disable-next-line no-await-in-loop
				if (!(await isTextFile(absolute))) {
					skipped.push(relative);
					continue;
				}

				throw new Error(
					`Agent folder is over the ${megabytes(
						MAX_FOLDER_BYTES,
					)} limit (reached at ${relative}). Move large files out of ${root}.`,
				);
			}

			// eslint-disable-next-line no-await-in-loop
			const text = decodeText(await fs.readFile(absolute));
			if (text === undefined) {
				skipped.push(relative);
				continue;
			}

			total += Buffer.byteLength(relative) + Buffer.byteLength(text);
			files[relative] = text;
		}
	}

	await walk(root);
	return {files, skipped};
}

/** `--set key=value` occurrences as a map; malformed or repeated keys throw. */
export function parseSetFlags(raw: unknown): Record<string, string> {
	if (raw === undefined) {
		return {};
	}

	const items = Array.isArray(raw) ? raw : [raw];
	const values: Record<string, string> = {};
	for (const item of items) {
		if (typeof item !== 'string') {
			throw new TypeError(`--set expects key=value, got ${String(item)}`);
		}

		const index = item.indexOf('=');
		if (index <= 0) {
			throw new Error(`--set expects key=value, got "${item}"`);
		}

		const key = item.slice(0, index).trim();
		if (key in values) {
			throw new Error(`--set ${key} is given more than once`);
		}

		values[key] = item.slice(index + 1);
	}

	return values;
}

function hasValue(value: unknown): boolean {
	return (
		value !== undefined &&
		value !== null &&
		!(typeof value === 'string' && value.trim() === '')
	);
}

export type ResolvedSetup = {
	values: Record<string, unknown>;
	missing: SetupField[];
};

/**
 * Declared defaults overlaid with `--set` values. Keys the folder does not
 * declare throw; required fields still without a value come back in `missing`.
 */
export function resolveSetup(
	fields: SetupField[],
	given: Record<string, string>,
): ResolvedSetup {
	const declared = new Set(fields.map(field => field.key));
	const unknown = Object.keys(given).filter(key => !declared.has(key));
	if (unknown.length > 0) {
		const known = fields.length > 0 ? [...declared].join(', ') : 'none';
		throw new Error(
			`Unknown setup key(s): ${unknown.join(
				', ',
			)}. This folder declares: ${known}.`,
		);
	}

	const values: Record<string, unknown> = {};
	for (const field of fields) {
		if (hasValue(field.default)) {
			values[field.key] = field.default;
		}
	}

	Object.assign(values, given);
	const missing = fields.filter(
		field => field.required && !hasValue(values[field.key]),
	);
	return {values, missing};
}

const STATUS_LABELS: Array<[EntityStatus, string]> = [
	['will_create', 'Create'],
	['will_update', 'Update'],
	['unchanged', 'Unchanged'],
	['orphaned', 'Orphaned (no longer in the folder; kept, not deleted)'],
	['changes_not_applied', 'Not applied (changes are not deployed yet)'],
	['already_exists', 'Already exists (reused as is, not updated)'],
	['unsupported', 'Unsupported (skipped)'],
];

export type PlanGroup = {
	status: string;
	label: string;
	entities: PreviewEntity[];
};

/** Entities grouped by status in a fixed order; empty groups are dropped. */
export function groupPlan(entities: PreviewEntity[]): PlanGroup[] {
	const known = new Map<string, string>(STATUS_LABELS);
	const order = [
		...STATUS_LABELS.map(([status]) => status as string),
		...new Set(
			entities.map(entity => entity.status).filter(s => !known.has(s)),
		),
	];
	return order
		.map(status => ({
			status,
			label: known.get(status) ?? status,
			entities: entities.filter(entity => entity.status === status),
		}))
		.filter(group => group.entities.length > 0);
}

function entityLine(kind: string, name: string, detail?: string | null) {
	const line = `  ${kind.padEnd(11)} ${name}`;
	return detail ? `${line}  (${detail})` : line;
}

export function formatPlan(
	preview: Pick<ImportPreview, 'entities' | 'issues'>,
): string[] {
	const lines: string[] = [];
	for (const group of groupPlan(preview.entities ?? [])) {
		lines.push(`${group.label}:`);
		for (const entity of group.entities) {
			lines.push(entityLine(entity.kind, entity.name, entity.detail));
		}
	}

	const issues = preview.issues ?? [];
	if (issues.length > 0) {
		lines.push('Issues:');
		for (const issue of issues) {
			lines.push(
				`  ${issue.severity.toUpperCase().padEnd(5)} ${issue.message}`,
			);
		}
	}

	return lines;
}

export function hasBlockingIssues(
	preview: Pick<ImportPreview, 'installable' | 'issues'>,
): boolean {
	return (
		!preview.installable ||
		(preview.issues ?? []).some(issue => issue.severity === 'block')
	);
}

export function formatInstallResult(result: InstallResult): string[] {
	const entities = result.entities ?? [];
	const lines = entities.map(
		entity =>
			`  ${entity.action.padEnd(9)}${entityLine(
				entity.kind,
				entity.name,
				entity.detail,
			)}`,
	);
	const counts = new Map<string, number>();
	for (const entity of entities) {
		counts.set(entity.action, (counts.get(entity.action) ?? 0) + 1);
	}

	const summary = [...counts].map(([action, n]) => `${n} ${action}`).join(', ');
	lines.push(`Deployed ${result.bundle_name}: ${summary || 'nothing to do'}`);
	return lines;
}

const fieldError = (item: {loc?: unknown[]; msg?: string}) =>
	item.loc ? `${item.loc.join('.')}: ${item.msg}` : String(item.msg);

/** Turn an SDK error (an Error, or a problem+json / FastAPI `detail` body) into one message. */
export function describeApiError(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}

	const body = error as
		| {
				detail?: unknown;
				issues?: Array<{message: string}>;
				errors?: Array<{loc?: unknown[]; msg?: string}>;
		  }
		| undefined;
	const detail = body?.detail;
	if (typeof detail === 'string') {
		return [
			detail,
			...(body?.issues ?? []).map(issue => `  ${issue.message}`),
			...(body?.errors ?? []).map(item => `  ${fieldError(item)}`),
		].join('\n');
	}

	if (Array.isArray(detail)) {
		return detail.map(fieldError).join('; ');
	}

	if (detail && typeof detail === 'object') {
		const {message, issues} = detail as {
			message?: string;
			issues?: Array<{message: string}>;
		};
		const parts = [message ?? JSON.stringify(detail)];
		for (const issue of issues ?? []) {
			parts.push(`  ${issue.message}`);
		}

		return parts.join('\n');
	}

	return JSON.stringify(error);
}

/** A bundle name from a directory name: lowercase, dash-separated. */
export function slugifyName(base: string): string {
	const slug = base
		.toLowerCase()
		.replace(/[^a-z\d]+/g, '-')
		.replace(/^-+|-+$/g, '');
	if (!slug) {
		throw new Error(
			`Cannot derive an agent name from "${base}"; use a directory whose name has letters or digits.`,
		);
	}

	return slug;
}

export function scaffoldFiles(name: string): Record<string, string> {
	return {
		'agent.yaml': [
			`name: ${name}`,
			'description: ""',
			'# A model instance id (agentarea models instances-list). Write the id here',
			'# and drop the setup entry below to stop deploy from asking for it.',
			'model: ${setup.model}',
			'toolsets: []',
			'setup:',
			'  - key: model',
			'    label: Model instance id',
			'    required: true',
			'    help: Run `agentarea models instances-list` to find one.',
			'',
		].join('\n'),
		'instructions.md': `You are ${name}. Describe what this agent does and how it should work.\n`,
	};
}
