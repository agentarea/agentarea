import * as sdk from '@agentarea/api-client';
import {registry} from './registry.js';
import {type CommandSpec} from './types.js';
import {reportResult, type SdkResult} from './output.js';

type SdkFn = (options?: unknown) => Promise<SdkResult>;

// Flags consumed by the CLI shell itself; never forwarded as query/body fields.
const RESERVED = new Set([
	'token',
	'apiUrl',
	'scope',
	'name',
	'client',
	'target',
	'data',
	'query',
	'path',
	'list',
	'output',
	'as',
	'workspace',
	'help',
	'version',
]);

export function findSpec(noun: string, verb: string): CommandSpec | undefined {
	return registry.find(
		spec =>
			spec.noun === noun &&
			(spec.verb === verb || (spec.aliases?.includes(verb) ?? false)),
	);
}

export function listNouns(): string[] {
	return [...new Set(registry.map(spec => spec.noun))].sort();
}

export function verbsFor(noun: string): CommandSpec[] {
	return registry.filter(spec => spec.noun === noun);
}

function coerce(value: unknown): unknown {
	if (typeof value !== 'string') {
		return value;
	}

	try {
		return JSON.parse(value);
	} catch {
		return value;
	}
}

function parseJsonFlag(raw: unknown, label: string): Record<string, unknown> {
	if (typeof raw !== 'string') {
		return {};
	}

	try {
		return JSON.parse(raw) as Record<string, unknown>;
	} catch (error) {
		throw new Error(`Invalid JSON in --${label}: ${(error as Error).message}`);
	}
}

/**
 * Dispatch a `<noun> <verb>` command against the generated SDK.
 * Returns an exit code, or -1 if no matching spec exists (caller falls through).
 */
export async function runRegistryCommand(
	noun: string,
	verb: string,
	pathArgs: string[],
	flags: Record<string, unknown>,
): Promise<number> {
	const spec = findSpec(noun, verb);
	if (!spec) {
		return -1;
	}

	const fn = (sdk as Record<string, unknown>)[spec.fn];
	if (typeof fn !== 'function') {
		console.error(`SDK is missing operation ${spec.fn} for ${noun} ${verb}`);
		return 1;
	}

	if (pathArgs.length < spec.pathParams.length) {
		const usage = spec.pathParams.map(name => `<${name}>`).join(' ');
		console.error(`Usage: agentarea ${noun} ${verb} ${usage}`.trimEnd());
		return 1;
	}

	const options: Record<string, unknown> = {};

	if (spec.pathParams.length > 0) {
		const pathObj: Record<string, string> = {};
		spec.pathParams.forEach((name, index) => {
			pathObj[name] = pathArgs[index] as string;
		});
		options['path'] = pathObj;
	}

	const extra: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(flags)) {
		if (!RESERVED.has(key) && value !== undefined) {
			extra[key] = coerce(value);
		}
	}

	try {
		if (spec.method === 'GET') {
			const query = {...extra, ...parseJsonFlag(flags['query'], 'query')};
			if (Object.keys(query).length > 0) {
				options['query'] = query;
			}
		} else {
			if (spec.body) {
				const body = {...extra, ...parseJsonFlag(flags['data'], 'data')};
				if (Object.keys(body).length > 0) {
					options['body'] = body;
				}
			}

			const query = parseJsonFlag(flags['query'], 'query');
			if (Object.keys(query).length > 0) {
				options['query'] = query;
			}
		}
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	const result = await (fn as SdkFn)(options);
	return reportResult(result);
}

export function printNounHelp(noun: string): void {
	const specs = verbsFor(noun);
	if (specs.length === 0) {
		console.error(`Unknown resource: ${noun}`);
		console.error(`Resources: ${listNouns().join(', ')}`);
		return;
	}

	console.log(`Usage: agentarea ${noun} <verb> [args] [flags]\n`);
	for (const spec of specs) {
		const params = spec.pathParams.map(name => `<${name}>`).join(' ');
		console.log(`  ${spec.verb.padEnd(22)} ${params}`.trimEnd());
		if (spec.summary) {
			console.log(`  ${' '.repeat(22)} ${spec.summary}`);
		}
	}
}

export function printRootHelp(): void {
	console.log('Usage: agentarea <resource> <verb> [args] [flags]\n');
	console.log('Resources:');
	console.log(`  ${listNouns().join(', ')}\n`);
	console.log('Run "agentarea <resource>" to list its verbs.');
	console.log('Escape hatch: "agentarea api --list" for raw operationIds.');
}
