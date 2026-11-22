import {promises as fs} from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {Writable} from 'node:stream';
import {
	analyzeBundleV1BundlesAnalyzePost,
	installBundleV1BundlesInstallPost,
	type AnalyzeRequest,
	type InstallRequest,
	type SetupField,
} from '@agentarea/api-client';
import {
	getApiBaseUrl,
	requireWorkspace,
	setRuntimeWorkspace,
} from '../services/apiRuntime.js';
import {
	LEGACY_MANIFEST_FILE,
	MANIFEST_FILE,
	decideExisting,
	folderFormat,
	formatBundlePlan,
	isDeployRunning,
	isPlanChanged,
	DEPLOY_RUNNING_MESSAGE,
	PLAN_CHANGED_MESSAGE,
	readGitOrigin,
	resolveTarget,
} from '../services/bundle.js';
import {
	DEPLOYMENTS_FILE,
	type DeploymentsFile,
	type IntoSource,
	findDeployment,
	readDeployments,
	removeDeployment,
	resolveInto,
	upsertDeployment,
	writeDeployments,
} from '../services/deployments.js';
import {
	describeApiError,
	formatInstallResult,
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

const confirmed = (answer: string) => /^y(es)?$/i.test(answer.trim());

/** `agentarea init [dir]` — scaffold agentarea.yaml + one agent file. */
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
	for (const name of [...Object.keys(files), LEGACY_MANIFEST_FILE]) {
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
		const target = path.join(root, name);
		// eslint-disable-next-line no-await-in-loop
		await fs.mkdir(path.dirname(target), {recursive: true});
		// eslint-disable-next-line no-await-in-loop
		await fs.writeFile(target, content, {flag: 'wx'});
		console.log(`created ${target}`);
	}

	const agentFile = Object.keys(files).find(name => name.startsWith('agents/'));
	console.log(`\nEdit ${agentFile}, then run: agentarea deploy ${dir ?? '.'}`);
	console.log(
		`After the first deploy, commit ${DEPLOYMENTS_FILE} if your team and CI should deploy into the same bundle.`,
	);
	return 0;
}

/**
 * `agentarea deploy [dir]` — send the folder to analyze, show the plan,
 * confirm, then install it. A redeploy updates the install recorded in
 * .agentarea/deployments.json for this API and workspace.
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

	const planJson = Boolean(flags['planJson']);
	const dryRun = planJson || Boolean(flags['dryRun']);
	const apiUrl = getApiBaseUrl();
	let given: Record<string, unknown>;
	let folder: Awaited<ReturnType<typeof readAgentFolder>>;
	let workspace: string;
	let deployments: DeploymentsFile;
	let into: string | undefined;
	let intoSource: IntoSource | undefined;
	try {
		const sets = parseSetFlags(flags['set']);
		folder = await readAgentFolder(root);
		const format = folderFormat(folder.files);
		if (!format) {
			throw new Error(
				`No ${MANIFEST_FILE} in ${root}. Run \`agentarea init ${
					dir ?? '.'
				}\` to scaffold one.`,
			);
		}

		if (format === 'legacy') {
			console.error(
				`warning: ${LEGACY_MANIFEST_FILE} is the old one-agent layout and will stop being read; move the folder to ${MANIFEST_FILE} (see \`agentarea init\`).`,
			);
		}

		const target =
			typeof flags['target'] === 'string' ? flags['target'] : undefined;
		const resolved = resolveTarget(folder.files[MANIFEST_FILE], target, sets);
		if (resolved.workspace) {
			const flagged = flags['workspace'];
			if (typeof flagged === 'string' && flagged !== resolved.workspace) {
				throw new Error(
					`--workspace ${flagged} conflicts with target "${target}", which deploys to ${resolved.workspace}.`,
				);
			}

			setRuntimeWorkspace(resolved.workspace);
		}

		given = resolved.setup;
		workspace = requireWorkspace();
		deployments = await readDeployments(root);
		({into, source: intoSource} = resolveInto({
			flag: flags['into'],
			env: process.env['AGENTAREA_BUNDLE_ID'],
			deployed: findDeployment(deployments, apiUrl, workspace),
		}));
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	for (const relative of folder.skipped) {
		console.error(`warning: skipped ${relative} (binary or not UTF-8)`);
	}

	const origin = await readGitOrigin(root);

	console.error(
		`Analyzing ${root} for workspace "${workspace}"${
			into ? ` into ${into} (from ${intoSource})` : ''
		}...`,
	);
	// Setup values go into analyze too: the plan diffs resolved values, so a
	// changed --set shows up as an update.
	const analyze = async (values: Record<string, unknown>) => {
		const body: AnalyzeRequest = {
			files: folder.files,
			setup_values: values,
			...(into ? {into} : {}),
			...(origin ? {origin} : {}),
		};
		const analyzed = await analyzeBundleV1BundlesAnalyzePost({body});
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

	if (planJson) {
		console.log(JSON.stringify(preview, null, 2));
		return hasBlockingIssues(preview) ? 1 : 0;
	}

	for (;;) {
		const step = decideExisting(preview, {
			workspace,
			interactive: interactive(),
			into,
		});
		if (step.action === 'continue') {
			break;
		}

		if (step.action === 'fail') {
			console.error(step.message);
			return 1;
		}

		// eslint-disable-next-line no-await-in-loop
		if (!confirmed(await ask(step.question))) {
			console.error('Cancelled; nothing was deployed.');
			return 1;
		}

		if (step.action === 'confirm_into') {
			into = step.into;
			intoSource = undefined;
		} else {
			if (intoSource === 'file') {
				deployments = removeDeployment(deployments, apiUrl, workspace);
				// eslint-disable-next-line no-await-in-loop
				await writeDeployments(root, deployments);
			}

			into = undefined;
			intoSource = undefined;
		}

		// eslint-disable-next-line no-await-in-loop
		preview = await analyze(given);
		if (!preview) {
			return 1;
		}
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

	if (setup.missing.length > 0 && !dryRun) {
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

	for (const line of formatBundlePlan(preview)) {
		console.log(line);
	}

	if (hasBlockingIssues(preview)) {
		console.error('Blocking issues found; nothing was deployed.');
		return 1;
	}

	if (dryRun) {
		return 0;
	}

	if (!flags['yes']) {
		if (!interactive()) {
			console.error(
				'Refusing to deploy without confirmation in a non-interactive shell; pass --yes.',
			);
			return 1;
		}

		if (!confirmed(await ask(`Deploy to workspace "${workspace}"? [y/N] `))) {
			console.error('Cancelled; nothing was deployed.');
			return 1;
		}
	}

	if (!preview.plan_digest) {
		console.error('The plan cannot be installed; nothing was deployed.');
		return 1;
	}

	const body: InstallRequest = {
		bundle: preview.bundle,
		setup_values: sent,
		plan_digest: preview.plan_digest,
		...(preview.install ? {install_id: preview.install.id} : {}),
		...(origin ? {origin} : {}),
	};
	const installed = await installBundleV1BundlesInstallPost({body});
	if (isPlanChanged(installed.error)) {
		console.error(PLAN_CHANGED_MESSAGE);
		return 1;
	}

	if (isDeployRunning(installed.error)) {
		console.error(DEPLOY_RUNNING_MESSAGE);
		return 1;
	}

	if (installed.error ?? !installed.data) {
		console.error(`Install failed: ${describeApiError(installed.error)}`);
		return 1;
	}

	const result = installed.data;
	for (const line of formatInstallResult(result)) {
		console.log(line);
	}

	if (!result.install_id) {
		console.error(
			`The server did not return the install id; ${DEPLOYMENTS_FILE} was not updated.`,
		);
		return 1;
	}

	await writeDeployments(
		root,
		upsertDeployment(deployments, {
			api_url: apiUrl,
			workspace,
			install_id: result.install_id,
			name: result.bundle_name,
			deployed_at: new Date().toISOString(),
		}),
	);
	console.error(`Recorded the install in ${DEPLOYMENTS_FILE}.`);
	return 0;
}
