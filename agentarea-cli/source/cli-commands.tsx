import {apiClient} from './services/apiClient.js';
import {
	applyApiUrlFlag,
	getApiBaseUrl,
	initApiClient,
	setRuntimeToken,
} from './services/apiRuntime.js';
import {configManager} from './utils/config.js';
import {logger} from './utils/logger.js';
import {connectClient} from './commands/connect.js';
import {
	defaultRunnerRoot,
	loadRunnerConfig,
	ACP_COMMANDS,
	CODEX_REQUIREMENTS_FILE,
	isRunnerHarness,
	registerRunner,
	runRunner,
	setupCodexRequirements,
} from './commands/runner.js';
import {loadAccessToken, runLogin, runLogout} from './commands/login.js';
import {
	printOperationList,
	runApiPassthrough,
	runTasksSubmit,
	runTasksWatch,
} from './commands/api.js';
import {
	runRegistryCommand,
	printNounHelp,
	printRootHelp,
	verbsFor,
} from './commands/router.js';
import {flushAndExit} from './commands/output.js';
import {runFilesSync} from './commands/filesSync.js';
import {runDeploy, runInit} from './commands/deploy.js';

interface CliOptions {
	token?: string;
	apiUrl?: string;
	scope?: string;
	name?: string;
	alias?: string;
	mcp?: string;
	login?: boolean;
	client?: string;
	target?: string;
	data?: string;
	query?: string;
	path?: string;
	list?: boolean;
	args?: string[];
	rawFlags?: Record<string, unknown>;
}

export async function handleCliCommand(
	command: string | undefined,
	subcommand: string | undefined,
	options: CliOptions,
): Promise<boolean> {
	// `--api-url` outranks AGENTAREA_API_URL and the saved config; login,
	// connect and every SDK call then resolve the same URL.
	applyApiUrlFlag(options.apiUrl);

	// Configure the shared API client (base URL + lazy token provider).
	initApiClient();

	const apiUrl = getApiBaseUrl();

	// Browser sign-in has to run before any token is required.
	if (command === 'login') {
		return runLogin({apiUrl});
	}

	if (command === 'logout') {
		return runLogout({apiUrl, all: options.rawFlags?.['all'] === true});
	}

	if (command === 'init') {
		await flushAndExit(await runInit(subcommand));
	}

	if (command === 'workspace' && subcommand === 'use') {
		const slug = options.args?.[2];
		if (!slug) {
			console.error('Usage: agentarea workspace use <slug>');
			await flushAndExit(1);
		}

		configManager.set('workspace', slug);
		console.error(`Workspace-scoped commands now run in "${slug}".`);
		await flushAndExit(0);
	}

	// A runner holds its client's runner key, never a person's session.
	if (command === 'runner') {
		const rawFlags = options.rawFlags ?? {};
		const root =
			typeof rawFlags['root'] === 'string'
				? rawFlags['root']
				: defaultRunnerRoot();
		if (subcommand === 'register') {
			const key =
				typeof rawFlags['key'] === 'string' ? rawFlags['key'] : undefined;
			if (!key) {
				console.error(
					'Usage: agentarea runner register --api-url <url> --key <key> [--root <dir>]',
				);
				return false;
			}

			const config = await registerRunner(apiUrl, key, root);
			console.error(
				`Registered as the ${config.kind} runner of client ${config.client_id} in ${config.workspace}; key stored in ${root}`,
			);
			await flushAndExit(0);
		}

		if (subcommand === 'setup') {
			const result = setupCodexRequirements();
			console.error(
				result === 'already'
					? `${CODEX_REQUIREMENTS_FILE} already turns on Codex's managed network proxy`
					: `Turned on Codex's managed network proxy in ${CODEX_REQUIREMENTS_FILE}`,
			);
			await flushAndExit(0);
		}

		if (rawFlags['sandbox'] !== undefined) {
			console.error(
				"--sandbox is gone: whether a runner's turns run sandboxed is the client's setting, on its Runner tab.",
			);
			return false;
		}

		if (!isRunnerHarness(subcommand)) {
			console.error(
				`Usage: agentarea runner codex|claude|${Object.keys(ACP_COMMANDS).join(
					'|',
				)}|acp [--root <dir>] [--login-from <dir>] [--allow-domain <host,...>] [--capacity <turns>] [--command "<acp command>"] [--pass-env <NAME,...>]\n       agentarea runner setup`,
			);
			return false;
		}

		const config = loadRunnerConfig(root);
		if (config.kind !== subcommand) {
			console.error(
				`This runner is registered for a ${config.kind} client; run \`agentarea runner ${config.kind}\`.`,
			);
			return false;
		}

		const loginFrom =
			typeof rawFlags['loginFrom'] === 'string'
				? rawFlags['loginFrom']
				: subcommand === 'codex'
				? `${process.env['HOME']}/.codex`
				: undefined;
		return runRunner({
			config,
			harness: subcommand,
			root,
			loginFrom,
			allowDomains: ([] as unknown[])
				.concat(rawFlags['allowDomain'] ?? [])
				.flatMap(value => String(value).split(','))
				.map(host => host.trim())
				.filter(Boolean),
			capacity:
				rawFlags['capacity'] === undefined ? 2 : Number(rawFlags['capacity']),
			...(typeof rawFlags['command'] === 'string'
				? {command: rawFlags['command'].trim().split(/\s+/)}
				: {}),
			passEnv: ([] as unknown[])
				.concat(rawFlags['passEnv'] ?? [])
				.flatMap(value => String(value).split(','))
				.map(name => name.trim())
				.filter(Boolean),
		});
	}

	// Load token from CLI flag, environment, or the stored OAuth session
	// (refreshed on the spot when it is about to expire).
	let loadedToken = options.token || process.env['AGENTAREA_TOKEN'];
	if (!loadedToken) {
		try {
			loadedToken = (await loadAccessToken(apiUrl)) ?? undefined;
		} catch (error) {
			logger.warn(`Failed to load stored token: ${String(error)}`);
		}
	}

	const authToken = {
		accessToken: loadedToken ?? '',
		tokenType: 'Bearer',
		expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000),
	};

	if (loadedToken) {
		apiClient.setToken(authToken);
		setRuntimeToken(loadedToken);
	}

	const args = options.args ?? [];
	const rawFlags = options.rawFlags ?? {};
	const pathArgs = args.slice(2);

	// --- Bespoke commands (richer UX than a plain SDK call) ---
	// Interactive browsing is the no-argument TUI (`agentarea`); `agents list`
	// stays a scriptable JSON command handled by the registry router below.

	// Hidden escape hatch: call any operation by its raw operationId.
	if (command === 'api') {
		if (options.list) {
			printOperationList();
			await flushAndExit(0);
		}

		const code = await runApiPassthrough(subcommand, {
			data: options.data,
			query: options.query,
			path: options.path,
		});
		await flushAndExit(code);
	}

	// Task submit/watch wrap streaming + SSE, not a plain request/response.
	if (command === 'tasks' && subcommand === 'submit') {
		await flushAndExit(
			await runTasksSubmit(pathArgs[0], pathArgs[1], options.data),
		);
	}

	if (command === 'tasks' && subcommand === 'watch') {
		await flushAndExit(await runTasksWatch(pathArgs[0], pathArgs[1]));
	}

	if (command === 'files' && subcommand === 'sync') {
		if (!loadedToken) {
			console.error(
				'Not signed in. Run `agentarea login --api-url=<api>` first (or pass --token).',
			);
			await flushAndExit(1);
		}

		await flushAndExit(await runFilesSync(pathArgs[0], pathArgs[1], rawFlags));
	}

	if (command === 'deploy') {
		if (!loadedToken) {
			console.error(
				'Not signed in. Run `agentarea login --api-url=<api>` first (or pass --token).',
			);
			await flushAndExit(1);
		}

		await flushAndExit(await runDeploy(subcommand, rawFlags));
	}

	if (command === 'connect' || (command === 'mcp' && subcommand === 'sync')) {
		if (!loadedToken) {
			console.error(
				'Not signed in. Run `agentarea login --api-url=<api>` first (or pass --token).',
			);
			return false;
		}

		const harness =
			command === 'connect' ? subcommand : options.target || 'codex';

		return connectClient(harness, {
			apiUrl,
			scope: options.scope,
			name: options.name,
			alias: options.alias,
			mcp: options.mcp,
			login: options.login,
			clientId: options.client,
		});
	}

	// --- Registry router: generic <noun> <verb> over the generated SDK ---
	if (command) {
		if (!subcommand) {
			printNounHelp(command);
			await flushAndExit(verbsFor(command).length > 0 ? 0 : 1);
		}

		const code = await runRegistryCommand(
			command,
			subcommand,
			pathArgs,
			rawFlags,
		);
		if (code !== -1) {
			await flushAndExit(code);
		}

		console.error(`Unknown command: ${command} ${subcommand}`);
		printNounHelp(command);
		await flushAndExit(1);
	}

	// No command at all
	printRootHelp();
	return false;
}
