import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {
	buildAuthorizeUrl,
	createPkcePair,
	createState,
	discoverAuthServer,
	exchangeCode,
	parseCallback,
	refreshAccessToken,
	registerClient,
} from '../services/oauth.js';
import {tokenStorage} from '../utils/storage.js';
import {logger} from '../utils/logger.js';
import {type AuthToken} from '../types/index.js';

/**
 * `agentarea login` — browser authorization-code + PKCE against the API's own
 * OAuth surface. The CLI registers itself as a public loopback client (RFC 7591)
 * so nothing has to be provisioned by hand, and the resulting Hydra token is
 * accepted by every edge: REST, /mcp and /client-mcp.
 */

const CALLBACK_PORTS = [51789, 51790, 51791];
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000;
const CLIENT_NAME = 'AgentArea CLI';

const SUCCESS_PAGE = `<!doctype html><meta charset="utf-8"><title>AgentArea</title>
<body style="font-family:system-ui;padding:3rem">
<h2>Signed in to AgentArea</h2><p>You can close this tab and return to the terminal.</p>`;

function clientCachePath(): string {
	return path.join(os.homedir(), '.agentarea', 'oauth-clients.json');
}

async function readClientCache(): Promise<Record<string, string>> {
	try {
		return JSON.parse(await fs.readFile(clientCachePath(), 'utf8')) as Record<
			string,
			string
		>;
	} catch (error: unknown) {
		if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
			return {};
		}

		throw error;
	}
}

async function cacheClientId(key: string, clientId: string): Promise<void> {
	const cache = await readClientCache();
	cache[key] = clientId;
	await fs.mkdir(path.dirname(clientCachePath()), {
		recursive: true,
		mode: 0o700,
	});
	await fs.writeFile(clientCachePath(), `${JSON.stringify(cache, null, 2)}\n`, {
		mode: 0o600,
	});
}

function openBrowser(url: string): void {
	const [bin, ...args] =
		process.platform === 'darwin'
			? ['open', url]
			: process.platform === 'win32'
			? ['cmd', '/c', 'start', '', url]
			: ['xdg-open', url];

	const child = spawn(bin!, args, {stdio: 'ignore', detached: true});
	child.on('error', () => {
		console.log(
			'Could not launch a browser automatically — open the URL above.',
		);
	});
	child.unref();
}

interface Callback {
	server: http.Server;
	port: number;
	waitForCode: (state: string) => Promise<string>;
}

async function listenOnLoopback(): Promise<Callback> {
	let pending:
		| {resolve: (code: string) => void; reject: (error: Error) => void}
		| undefined;
	let expectedState = '';

	const server = http.createServer((request, response) => {
		if (!request.url?.startsWith('/callback')) {
			response.writeHead(404).end();
			return;
		}

		try {
			const code = parseCallback(request.url, expectedState);
			response.writeHead(200, {'Content-Type': 'text/html'}).end(SUCCESS_PAGE);
			pending?.resolve(code);
		} catch (error) {
			response
				.writeHead(400, {'Content-Type': 'text/plain'})
				.end(String((error as Error).message));
			pending?.reject(error as Error);
		}
	});

	for (const port of CALLBACK_PORTS) {
		const bound = await new Promise<boolean>(resolve => {
			const onError = (error: NodeJS.ErrnoException) => {
				if (error.code === 'EADDRINUSE') {
					resolve(false);
					return;
				}

				throw error;
			};

			server.once('error', onError);
			server.listen(port, '127.0.0.1', () => {
				server.removeListener('error', onError);
				resolve(true);
			});
		});

		if (bound) {
			return {
				server,
				port,
				async waitForCode(state: string) {
					expectedState = state;
					return new Promise<string>((resolve, reject) => {
						pending = {resolve, reject};
						setTimeout(() => {
							reject(new Error('Timed out waiting for the browser callback'));
						}, LOGIN_TIMEOUT_MS).unref();
					});
				},
			};
		}
	}

	throw new Error(
		`No free loopback port for the OAuth callback (tried ${CALLBACK_PORTS.join(
			', ',
		)}); free one and retry`,
	);
}

export async function runLogin(options: {apiUrl: string}): Promise<boolean> {
	const apiUrl = options.apiUrl.replace(/\/$/, '');
	const metadata = await discoverAuthServer(apiUrl);
	const callback = await listenOnLoopback();
	const redirectUri = `http://127.0.0.1:${callback.port}/callback`;

	try {
		const cacheKey = `${apiUrl}|${redirectUri}`;
		const cache = await readClientCache();
		let clientId = cache[cacheKey];

		if (clientId) {
			logger.debug(`Reusing registered OAuth client ${clientId}`);
		} else {
			clientId = await registerClient({
				metadata,
				redirectUri,
				clientName: CLIENT_NAME,
			});
			await cacheClientId(cacheKey, clientId);
		}

		const {verifier, challenge} = createPkcePair();
		const state = createState();
		const authorizeUrl = buildAuthorizeUrl({
			metadata,
			clientId,
			redirectUri,
			challenge,
			state,
			audience: apiUrl,
		});

		console.log(`Opening ${authorizeUrl}`);
		console.log('Waiting for the browser to complete sign-in...');
		openBrowser(authorizeUrl);

		const code = await callback.waitForCode(state);
		const token = await exchangeCode({
			metadata,
			clientId,
			redirectUri,
			code,
			verifier,
		});

		await tokenStorage.saveToken({...token, clientId, apiUrl});
		console.log(`Signed in to ${apiUrl}`);
		if (token.expiresAt) {
			console.log(`Access token valid until ${token.expiresAt.toISOString()}`);
		}

		if (!token.refreshToken) {
			console.log(
				'No refresh token was issued — you will have to run `agentarea login` again when it expires.',
			);
		}

		return true;
	} finally {
		callback.server.close();
	}
}

export async function runLogout(): Promise<boolean> {
	await tokenStorage.clearToken();
	console.log('Signed out (local token cleared).');
	return true;
}

/**
 * Return a usable access token for *apiUrl*, refreshing it when it is expiring
 * and a refresh token is available. Returns null when there is nothing stored.
 */
export async function loadAccessToken(apiUrl: string): Promise<string | null> {
	let stored: AuthToken | null = null;
	try {
		stored = await tokenStorage.getToken();
	} catch (error) {
		logger.warn(`Could not read the stored token: ${String(error)}`);
		return null;
	}

	if (!stored) {
		return null;
	}

	if (!tokenStorage.isTokenExpired(stored)) {
		return stored.accessToken;
	}

	if (!stored.refreshToken || !stored.clientId) {
		logger.warn(
			'Stored token is expired and cannot be refreshed; run `agentarea login`',
		);
		return stored.accessToken;
	}

	const metadata = await discoverAuthServer(stored.apiUrl ?? apiUrl);
	const refreshed = await refreshAccessToken({
		metadata,
		clientId: stored.clientId,
		refreshToken: stored.refreshToken,
	});
	await tokenStorage.saveToken({
		...refreshed,
		clientId: stored.clientId,
		apiUrl: stored.apiUrl ?? apiUrl,
	});
	return refreshed.accessToken;
}
