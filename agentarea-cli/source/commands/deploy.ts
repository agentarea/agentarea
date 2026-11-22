import {promises as fs} from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {Writable} from 'node:stream';
import {
	analyzeBundleV1BundlesAnalyzePost,
	installBundleV1BundlesInstallPost,
	type AnalyzeRequest,
	type BundleOrigin,
	type ImportPreview,
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
import {
	ORG_FILE,
	isOrgManifest,
	checkOrgFlags,
	declaredSetupKeys,
	formatLinks,
	formatTeamHeader,
	mergeShared,
	parseOrg,
	scaffoldOrgFiles,
	selectShared,
	selectTeams,
	splitSetValues,
	teamSharedFiles,
} from '../services/org.js';

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

function setupPrompt(field: SetupField, team?: string): string {
	const help = field.help ? ` (${field.help})` : '';
	return `${team ? `[${team}] ` : ''}${field.label} [${field.key}]${help}: `;
}

const confirmed = (answer: string) => /^y(es)?$/i.test(answer.trim());

/**
 * `agentarea init [dir]` — scaffold agentarea.yaml + one agent file;
 * `--org` scaffolds an organization agentarea.yaml (teams:) + one team folder instead.
 */
export async function runInit(
	dir: string | undefined,
	org = false,
): Promise<number> {
	const root = path.resolve(dir ?? '.');
	let files: Record<string, string>;
	try {
		const name = slugifyName(path.basename(root));
		files = org ? scaffoldOrgFiles(name) : scaffoldFiles(name);
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	await fs.mkdir(root, {recursive: true});
	const existing: string[] = [];
	const guarded = [...Object.keys(files), LEGACY_MANIFEST_FILE];
	for (const name of guarded) {
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

	const agentFile = Object.keys(files).find(name => name.includes('agents/'));
	const sections =
		'Add sections to agentarea.yaml as the bundle grows, each with its own include: mcp, skills, openapi, policies, schedules, channels, streams, tasks, projects, and workspace.policies (rules for the whole workspace; a workspace admin deploys those).';
	if (org) {
		console.log(
			`\nSet each team's workspace under teams: in ${ORG_FILE}, edit ${agentFile}, then run: agentarea deploy ${
				dir ?? '.'
			}`,
		);
		console.log(sections);
		console.log(
			`Each team folder keeps its own ${DEPLOYMENTS_FILE}; commit them if your team and CI should deploy into the same bundles.`,
		);
		return 0;
	}

	console.log(`\nEdit ${agentFile}, then run: agentarea deploy ${dir ?? '.'}`);
	console.log(sections);
	console.log(
		`After the first deploy, commit ${DEPLOYMENTS_FILE} if your team and CI should deploy into the same bundle.`,
	);
	return 0;
}

type BundleTarget = {
	root: string;
	files: Record<string, string>;
	workspace: string;
	given: Record<string, unknown>;
	deployments: DeploymentsFile;
	into?: string;
	intoSource?: IntoSource;
	team?: string;
};

type Prepared = BundleTarget & {
	preview: ImportPreview;
	sent: Record<string, unknown>;
	origin?: BundleOrigin;
};

/**
 * Analyze one bundle until it has a plan to show: settle a collision with an
 * existing install and ask for missing setup values. A number is the exit
 * code to stop with.
 */
async function prepare(
	target: BundleTarget,
	options: {apiUrl: string; dryRun: boolean; planJson: boolean},
): Promise<Prepared | number> {
	const {root, workspace, given, team} = target;
	let {deployments, into, intoSource} = target;
	const origin = await readGitOrigin(root);
	console.error(
		`Analyzing ${
			team ? `team ${team} (${root})` : root
		} for workspace "${workspace}"${
			into ? ` into ${into} (from ${intoSource})` : ''
		}...`,
	);
	// Setup values go into analyze too: the plan diffs resolved values, so a
	// changed --set shows up as an update.
	const analyze = async (values: Record<string, unknown>) => {
		setRuntimeWorkspace(workspace);
		const body: AnalyzeRequest = {
			files: target.files,
			setup_values: values,
			...(into ? {into} : {}),
			...(origin ? {origin} : {}),
		};
		const analyzed = await analyzeBundleV1BundlesAnalyzePost({body});
		if (analyzed.error ?? !analyzed.data) {
			console.error(
				`${team ? `Team ${team}: a` : 'A'}nalyze failed: ${describeApiError(
					analyzed.error,
				)}`,
			);
			return undefined;
		}

		return analyzed.data;
	};

	let preview = await analyze(given);
	if (!preview) {
		return 1;
	}

	const done = (sent: Record<string, unknown>, plan: ImportPreview) => ({
		...target,
		deployments,
		into,
		intoSource,
		preview: plan,
		sent,
		...(origin ? {origin} : {}),
	});

	if (options.planJson) {
		return done(given, preview);
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
			console.error(team ? `Team ${team}: ${step.message}` : step.message);
			return 1;
		}

		// eslint-disable-next-line no-await-in-loop
		if (
			!confirmed(await ask(team ? `[${team}] ${step.question}` : step.question))
		) {
			console.error('Cancelled; nothing was deployed.');
			return 1;
		}

		if (step.action === 'confirm_into') {
			into = step.into;
			intoSource = undefined;
		} else {
			if (intoSource === 'file') {
				deployments = removeDeployment(deployments, options.apiUrl, workspace);
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
		console.error(
			team
				? `Team ${team}: ${(error as Error).message}`
				: (error as Error).message,
		);
		return 1;
	}

	// Install gets exactly the values the shown plan was made for; the server
	// fills in defaults itself.
	const sent: Record<string, unknown> = {...given};
	if (setup.missing.length === 0 || options.dryRun) {
		return done(sent, preview);
	}

	if (!interactive()) {
		console.error(
			`${
				team ? `Team ${team}: m` : 'M'
			}issing required setup values: ${setup.missing
				.map(field => field.key)
				.join(', ')}. Pass them with --set key=value.`,
		);
		return 1;
	}

	for (const field of setup.missing) {
		// eslint-disable-next-line no-await-in-loop
		const value = await ask(setupPrompt(field, team), field.type === 'secret');
		if (!value.trim()) {
			console.error(`${field.key} is required; nothing was deployed.`);
			return 1;
		}

		sent[field.key] = value;
	}

	preview = await analyze(sent);
	return preview ? done(sent, preview) : 1;
}

/** Install a prepared plan and record the install in the folder. */
async function install(prepared: Prepared, apiUrl: string): Promise<number> {
	const {preview, workspace, root} = prepared;
	if (!preview.plan_digest) {
		console.error('The plan cannot be installed; nothing was deployed.');
		return 1;
	}

	setRuntimeWorkspace(workspace);
	const body: InstallRequest = {
		bundle: preview.bundle,
		setup_values: prepared.sent,
		plan_digest: preview.plan_digest,
		...(preview.install ? {install_id: preview.install.id} : {}),
		...(prepared.origin ? {origin: prepared.origin} : {}),
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
		upsertDeployment(prepared.deployments, {
			api_url: apiUrl,
			workspace,
			install_id: result.install_id,
			name: result.bundle_name,
			deployed_at: new Date().toISOString(),
		}),
	);
	console.error(
		`Recorded the install in ${path.join(root, DEPLOYMENTS_FILE)}.`,
	);
	return 0;
}

async function confirmDeploy(question: string, flags: Record<string, unknown>) {
	if (flags['yes']) {
		return true;
	}

	if (!interactive()) {
		console.error(
			'Refusing to deploy without confirmation in a non-interactive shell; pass --yes.',
		);
		return false;
	}

	if (!confirmed(await ask(question))) {
		console.error('Cancelled; nothing was deployed.');
		return false;
	}

	return true;
}

/**
 * `agentarea deploy [dir]` — send the folder to analyze, show the plan,
 * confirm, then install it. A redeploy updates the install recorded in
 * .agentarea/deployments.json for this API and workspace. A folder whose
 * agentarea.yaml has teams: deploys each of its teams.
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

	const manifest = await fs
		.readFile(path.join(root, ORG_FILE), 'utf8')
		.catch(() => undefined);
	if (manifest !== undefined && isOrgManifest(manifest)) {
		return runOrgDeploy(root, manifest, flags);
	}

	if (flags['onlyTeam'] !== undefined) {
		console.error(
			`--only-team needs an organization folder: an ${ORG_FILE} with teams:.`,
		);
		return 1;
	}

	const planJson = Boolean(flags['planJson']);
	const dryRun = planJson || Boolean(flags['dryRun']);
	const apiUrl = getApiBaseUrl();
	let target: BundleTarget;
	let skipped: string[];
	try {
		const sets = parseSetFlags(flags['set']);
		const folder = await readAgentFolder(root);
		skipped = folder.skipped;
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

		const targetName =
			typeof flags['target'] === 'string' ? flags['target'] : undefined;
		const resolved = resolveTarget(
			folder.files[MANIFEST_FILE],
			targetName,
			sets,
		);
		if (resolved.workspace) {
			const flagged = flags['workspace'];
			if (typeof flagged === 'string' && flagged !== resolved.workspace) {
				throw new Error(
					`--workspace ${flagged} conflicts with target "${targetName}", which deploys to ${resolved.workspace}.`,
				);
			}

			setRuntimeWorkspace(resolved.workspace);
		}

		const workspace = requireWorkspace();
		const deployments = await readDeployments(root);
		const {into, source} = resolveInto({
			flag: flags['into'],
			env: process.env['AGENTAREA_BUNDLE_ID'],
			deployed: findDeployment(deployments, apiUrl, workspace),
		});
		target = {
			root,
			files: folder.files,
			workspace,
			given: resolved.setup,
			deployments,
			...(into ? {into} : {}),
			...(source ? {intoSource: source} : {}),
		};
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	for (const relative of skipped) {
		console.error(`warning: skipped ${relative} (binary or not UTF-8)`);
	}

	const prepared = await prepare(target, {apiUrl, dryRun, planJson});
	if (typeof prepared === 'number') {
		return prepared;
	}

	if (planJson) {
		console.log(JSON.stringify(prepared.preview, null, 2));
		return hasBlockingIssues(prepared.preview) ? 1 : 0;
	}

	for (const line of formatBundlePlan(prepared.preview)) {
		console.log(line);
	}

	if (hasBlockingIssues(prepared.preview)) {
		console.error('Blocking issues found; nothing was deployed.');
		return 1;
	}

	if (dryRun) {
		return 0;
	}

	if (
		!(await confirmDeploy(
			`Deploy to workspace "${prepared.workspace}"? [y/N] `,
			flags,
		))
	) {
		return 1;
	}

	return install(prepared, apiUrl);
}

/**
 * Deploy an organization: one plan per team against its workspace, shown
 * together, one confirmation, then installed team by team.
 */
async function runOrgDeploy(
	root: string,
	orgText: string,
	flags: Record<string, unknown>,
): Promise<number> {
	const planJson = Boolean(flags['planJson']);
	const dryRun = planJson || Boolean(flags['dryRun']);
	const apiUrl = getApiBaseUrl();
	let org: ReturnType<typeof parseOrg>;
	const targets: BundleTarget[] = [];
	try {
		org = parseOrg(orgText);
		const bundleIdEnv = process.env['AGENTAREA_BUNDLE_ID'];
		checkOrgFlags(flags, bundleIdEnv);
		const teams = selectTeams(
			org,
			typeof flags['onlyTeam'] === 'string' ? flags['onlyTeam'] : undefined,
		);
		const inTeam = (relative: string) =>
			org.teams.some(
				team => relative === team.path || relative.startsWith(`${team.path}/`),
			);
		const orgFolder = await readAgentFolder(root, inTeam);
		for (const relative of orgFolder.skipped) {
			console.error(`warning: skipped ${relative} (binary or not UTF-8)`);
		}

		const shared = selectShared(orgFolder.files, org.shared);
		const folders = [];
		for (const team of teams) {
			const teamRoot = path.join(root, team.path);
			// eslint-disable-next-line no-await-in-loop
			const folder = await readAgentFolder(teamRoot);
			for (const relative of folder.skipped) {
				console.error(
					`warning: skipped ${team.path}/${relative} (binary or not UTF-8)`,
				);
			}

			const manifest = folder.files[MANIFEST_FILE];
			if (manifest === undefined) {
				throw new Error(
					`Team ${team.name}: no ${MANIFEST_FILE} in ${teamRoot}.`,
				);
			}

			const files = mergeShared(
				folder.files,
				teamSharedFiles(manifest, shared),
			);
			folders.push({team, teamRoot, files, keys: declaredSetupKeys(manifest)});
		}

		const split = splitSetValues(
			parseSetFlags(flags['set']),
			folders.map(item => ({team: item.team.name, keys: item.keys})),
		);
		for (const {team, teamRoot, files} of folders) {
			// eslint-disable-next-line no-await-in-loop
			const deployments = await readDeployments(teamRoot);
			const {into, source} = resolveInto({
				flag: flags['into'],
				env: bundleIdEnv,
				deployed: findDeployment(deployments, apiUrl, team.workspace),
			});
			targets.push({
				root: teamRoot,
				files,
				workspace: team.workspace,
				given: split[team.name] ?? {},
				deployments,
				team: team.name,
				...(into ? {into} : {}),
				...(source ? {intoSource: source} : {}),
			});
		}
	} catch (error) {
		console.error((error as Error).message);
		return 1;
	}

	const prepared: Prepared[] = [];
	for (const target of targets) {
		// eslint-disable-next-line no-await-in-loop
		const result = await prepare(target, {apiUrl, dryRun, planJson});
		if (typeof result === 'number') {
			return result;
		}

		prepared.push(result);
	}

	const blocked = prepared.filter(item => hasBlockingIssues(item.preview));
	if (planJson) {
		console.log(
			JSON.stringify(
				Object.fromEntries(prepared.map(item => [item.team, item.preview])),
				null,
				2,
			),
		);
		return blocked.length > 0 ? 1 : 0;
	}

	for (const item of prepared) {
		const team = org.teams.find(entry => entry.name === item.team)!;
		console.log(formatTeamHeader(team));
		for (const line of formatBundlePlan(item.preview)) {
			console.log(line);
		}

		console.log('');
	}

	for (const line of formatLinks(org.links)) {
		console.log(line);
	}

	if (blocked.length > 0) {
		console.error(
			`Blocking issues in team ${blocked
				.map(item => item.team)
				.join(', ')}; nothing was deployed.`,
		);
		return 1;
	}

	if (dryRun) {
		return 0;
	}

	const summary = prepared
		.map(item => `${item.team} -> ${item.workspace}`)
		.join(', ');
	if (
		!(await confirmDeploy(
			`Deploy ${prepared.length} team(s) (${summary})? [y/N] `,
			flags,
		))
	) {
		return 1;
	}

	const installed: string[] = [];
	for (const [index, item] of prepared.entries()) {
		console.error(`Installing team ${item.team} into "${item.workspace}"...`);
		// eslint-disable-next-line no-await-in-loop
		const code = await install(item, apiUrl);
		if (code !== 0) {
			const rest = prepared.slice(index + 1).map(next => next.team);
			console.error(
				`Team ${item.team} failed. Installed: ${
					installed.join(', ') || 'none'
				}. Not installed: ${[item.team, ...rest].join(', ')}.`,
			);
			return code;
		}

		installed.push(item.team!);
	}

	console.error(
		`Deployed ${installed.length} team(s): ${installed.join(', ')}.`,
	);
	return 0;
}
