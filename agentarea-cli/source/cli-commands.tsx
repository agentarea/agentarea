import {apiClient} from './services/apiClient.js';
import {initApiClient, setRuntimeToken} from './services/apiRuntime.js';
import {configManager} from './utils/config.js';
import {logger} from './utils/logger.js';
import {connectClient} from './commands/connect.js';
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
	// Initialize config with provided API URL if specified
	if (options.apiUrl) {
		process.env['API_URL'] = options.apiUrl;
		configManager.reinitialize();
		apiClient.reinitialize();
	}

	// Configure the shared API client (base URL + lazy token provider).
	initApiClient();

	const apiUrl = options.apiUrl || 'http://localhost:8000';

	// Browser sign-in has to run before any token is required.
	if (command === 'login') {
		return runLogin({apiUrl});
	}

	if (command === 'logout') {
		return runLogout();
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
