import {promises as fs} from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {Writable} from 'node:stream';
import {
	analyzeBundleV1BundlesAnalyzePost,
	installBundleV1BundlesInstallPost,
	type SetupField,
} from '@agentarea/api-client';
import {requireWorkspace} from '../services/apiRuntime.js';
import {
	describeApiError,
	formatInstallResult,
	formatPlan,
	hasBlockingIssues,
	parseSetFlags,
	readAgentFolder,
	resolveSetup,
	scaffoldFiles,
	slugifyName,
} from '../services/agentFolder.js';

const interactive = () =>
	Boolean(process.stdin.isTTY) && Boolean(process.stderr.isTTY);

/** Ask on stderr so stdout keeps only the plan and the result. */
async function ask(question: string, hidden = false): Promise<string> {
	let muted = false;
	const output = new Writable({
		write(chunk, encoding, callback) {
			if (!muted) {
				process.stderr.write(chunk, encoding);
			}

			callback();
		},
	});
	const rl = readline.createInterface({
		input: process.stdin,
		output,
		terminal: true,
	});

	return new Promise<string>(resolve => {
		rl.question(question, answer => {
			rl.close();
			if (hidden) {
				process.stderr.write('\n');
			}

			resolve(answer);
		});
		muted = hidden;
	});
}

function setupPrompt(field: SetupField): string {
	const help = field.help ? ` (${field.help})` : '';
	return `${field.label} [${field.key}]${help}: `;
}

/** `agentarea init [dir]` — scaffold agent.yaml + instructions.md. */
export async function runInit(dir: string | undefined): Promise<number> {
	const root = path.resolve(dir ?? '.');
	let files: Record<string, string>;
	try {
		files = scaffoldFiles(slugifyName(path.basename(root)));
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	await fs.mkdir(root, {recursive: true});
	const existing: string[] = [];
	for (const name of Object.keys(files)) {
		// eslint-disable-next-line no-await-in-loop
		const stat = await fs.stat(path.join(root, name)).catch(() => undefined);
		if (stat) {
			existing.push(name);
		}
	}

	if (existing.length > 0) {
		console.error(
			`Refusing to overwrite ${existing.join(
				', ',
			)} in ${root}. Nothing written.`,
		);
		return 1;
	}

	for (const [name, content] of Object.entries(files)) {
		// eslint-disable-next-line no-await-in-loop
		await fs.writeFile(path.join(root, name), content, {flag: 'wx'});
		console.log(`created ${path.join(root, name)}`);
	}

	console.log(
		`\nEdit instructions.md, then run: agentarea deploy ${dir ?? '.'}`,
	);
	return 0;
}

/**
 * `agentarea deploy [dir]` — send the folder to analyze, show the plan,
 * confirm, then install it. A redeploy updates what the last deploy created.
 */
export async function runDeploy(
	dir: string | undefined,
	flags: Record<string, unknown>,
): Promise<number> {
	const root = path.resolve(dir ?? '.');
	const stat = await fs.stat(root).catch(() => undefined);
	if (!stat?.isDirectory()) {
		console.error(`Not a directory: ${root}`);
		return 1;
	}

	let given: Record<string, string>;
	let folder: Awaited<ReturnType<typeof readAgentFolder>>;
	let workspace: string;
	try {
		given = parseSetFlags(flags['set']);
		folder = await readAgentFolder(root);
		workspace = requireWorkspace();
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	for (const relative of folder.skipped) {
		console.error(`warning: skipped ${relative} (binary or not UTF-8)`);
	}

	if (!('agent.yaml' in folder.files)) {
		console.error(
			`No agent.yaml in ${root}. Run \`agentarea init ${
				dir ?? '.'
			}\` to scaffold one.`,
		);
		return 1;
	}

	console.error(`Analyzing ${root} for workspace "${workspace}"...`);
	// Setup values go into analyze too: the plan diffs resolved values, so a
	// changed --set shows up as an update.
	const analyze = async (values: Record<string, unknown>) => {
		const analyzed = await analyzeBundleV1BundlesAnalyzePost({
			body: {files: folder.files, setup_values: values},
		});
		if (analyzed.error ?? !analyzed.data) {
			console.error(`Analyze failed: ${describeApiError(analyzed.error)}`);
			return undefined;
		}

		return analyzed.data;
	};

	let preview = await analyze(given);
	if (!preview) {
		return 1;
	}

	let setup: ReturnType<typeof resolveSetup>;
	try {
		setup = resolveSetup(preview.setup ?? [], given);
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	// Install gets exactly the values the shown plan was made for; the server
	// fills in defaults itself.
	const sent: Record<string, unknown> = {...given};

	if (setup.missing.length > 0 && !flags['dryRun']) {
		if (!interactive()) {
			console.error(
				`Missing required setup values: ${setup.missing
					.map(field => field.key)
					.join(', ')}. Pass them with --set key=value.`,
			);
			return 1;
		}

		for (const field of setup.missing) {
			// eslint-disable-next-line no-await-in-loop
			const value = await ask(setupPrompt(field), field.type === 'secret');
			if (!value.trim()) {
				console.error(`${field.key} is required; nothing was deployed.`);
				return 1;
			}

			sent[field.key] = value;
		}

		preview = await analyze(sent);
		if (!preview) {
			return 1;
		}
	}

	for (const line of formatPlan(preview)) {
		console.log(line);
	}

	if (hasBlockingIssues(preview)) {
		console.error('Blocking issues found; nothing was deployed.');
		return 1;
	}

	if (flags['dryRun']) {
		return 0;
	}

	if (!flags['yes']) {
		if (!interactive()) {
			console.error(
				'Refusing to deploy without confirmation in a non-interactive shell; pass --yes.',
			);
			return 1;
		}

		const answer = await ask(`Deploy to workspace "${workspace}"? [y/N] `);
		if (!/^y(es)?$/i.test(answer.trim())) {
			console.error('Cancelled; nothing was deployed.');
			return 1;
		}
	}

	if (!preview.plan_digest) {
		console.error('The plan cannot be installed; nothing was deployed.');
		return 1;
	}

	const installed = await installBundleV1BundlesInstallPost({
		body: {
			bundle: preview.bundle,
			setup_values: sent,
			plan_digest: preview.plan_digest,
		},
	});
	if (installed.error ?? !installed.data) {
		console.error(`Install failed: ${describeApiError(installed.error)}`);
		return 1;
	}

	for (const line of formatInstallResult(installed.data)) {
		console.log(line);
	}

	return 0;
}
