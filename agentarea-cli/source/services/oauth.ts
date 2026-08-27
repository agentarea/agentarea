import crypto from 'node:crypto';
import {type AuthToken} from '../types/index.js';

/**
 * OAuth 2.1 authorization-code + PKCE against the Agentarea API.
 *
 * The API serves RFC 8414 metadata at `/.well-known/oauth-authorization-server`
 * and proxies Hydra's dynamic client registration, so the CLI registers itself
 * as a public loopback client and never needs a pre-provisioned key.
 */

export interface AuthServerMetadata {
	issuer: string;
	authorization_endpoint: string;
	token_endpoint: string;
	registration_endpoint?: string;
	code_challenge_methods_supported?: string[];
	token_endpoint_auth_methods_supported?: string[];
}

export type FetchLike = (
	url: string | URL,
	init?: RequestInit,
) => Promise<Response>;

export const OAUTH_SCOPE = 'offline_access openid';

interface TokenPayload {
	access_token?: string;
	refresh_token?: string;
	token_type?: string;
	expires_in?: number;
	error?: string;
	error_description?: string;
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
	try {
		return (await response.json()) as Record<string, unknown>;
	} catch {
		return {};
	}
}

function describeError(payload: Record<string, unknown>): string {
	const code = payload['error'];
	const description = payload['error_description'];
	if (code && description) {
		return `${String(code)}: ${String(description)}`;
	}

	return String(code ?? description ?? 'no error detail returned');
}

export function createPkcePair(): {verifier: string; challenge: string} {
	const verifier = crypto.randomBytes(32).toString('base64url');
	const challenge = crypto
		.createHash('sha256')
		.update(verifier)
		.digest('base64url');
	return {verifier, challenge};
}

export function createState(): string {
	return crypto.randomBytes(16).toString('base64url');
}

export async function discoverAuthServer(
	apiUrl: string,
	fetchImpl: FetchLike = fetch,
): Promise<AuthServerMetadata> {
	const base = apiUrl.replace(/\/$/, '');
	const url = `${base}/.well-known/oauth-authorization-server`;
	const response = await fetchImpl(url);

	if (!response.ok) {
		throw new Error(`OAuth discovery failed (${response.status}) at ${url}`);
	}

	const metadata = (await readJson(response)) as unknown as AuthServerMetadata;

	if (!metadata.authorization_endpoint || !metadata.token_endpoint) {
		throw new Error(
			`OAuth discovery at ${url} returned no authorization_endpoint/token_endpoint`,
		);
	}

	if (!(metadata.code_challenge_methods_supported ?? []).includes('S256')) {
		throw new Error(
			`Authorization server ${metadata.issuer} does not advertise PKCE S256; refusing to start a weaker flow`,
		);
	}

	return metadata;
}

export async function registerClient(
	options: {
		metadata: AuthServerMetadata;
		redirectUri: string;
		clientName: string;
	},
	fetchImpl: FetchLike = fetch,
): Promise<string> {
	const endpoint = options.metadata.registration_endpoint;
	if (!endpoint) {
		throw new Error(
			`Authorization server ${options.metadata.issuer} advertises no registration_endpoint; cannot register the CLI as an OAuth client`,
		);
	}

	const response = await fetchImpl(endpoint, {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({
			client_name: options.clientName,
			redirect_uris: [options.redirectUri],
			grant_types: ['authorization_code', 'refresh_token'],
			response_types: ['code'],
			token_endpoint_auth_method: 'none',
			scope: OAUTH_SCOPE,
		}),
	});

	const payload = await readJson(response);
	if (!response.ok) {
		throw new Error(
			`Dynamic client registration failed (${response.status}): ${describeError(
				payload,
			)}`,
		);
	}

	const clientId = payload['client_id'];
	if (typeof clientId !== 'string' || !clientId) {
		throw new Error('Dynamic client registration returned no client_id');
	}

	return clientId;
}

export function buildAuthorizeUrl(options: {
	metadata: AuthServerMetadata;
	clientId: string;
	redirectUri: string;
	challenge: string;
	state: string;
	audience?: string;
}): string {
	const url = new URL(options.metadata.authorization_endpoint);
	url.searchParams.set('response_type', 'code');
	url.searchParams.set('client_id', options.clientId);
	url.searchParams.set('redirect_uri', options.redirectUri);
	url.searchParams.set('scope', OAUTH_SCOPE);
	url.searchParams.set('state', options.state);
	url.searchParams.set('code_challenge', options.challenge);
	url.searchParams.set('code_challenge_method', 'S256');
	if (options.audience) {
		url.searchParams.set('audience', options.audience);
	}

	return url.toString();
}

export function parseCallback(rawUrl: string, expectedState: string): string {
	const url = new URL(rawUrl, 'http://127.0.0.1');
	const error = url.searchParams.get('error');
	if (error) {
		const description = url.searchParams.get('error_description');
		throw new Error(
			description
				? `${error}: ${description}`
				: `Authorization failed: ${error}`,
		);
	}

	if (url.searchParams.get('state') !== expectedState) {
		throw new Error(
			'OAuth state mismatch on the callback; discarding the response',
		);
	}

	const code = url.searchParams.get('code');
	if (!code) {
		throw new Error('Authorization callback carried no code');
	}

	return code;
}

function toAuthToken(
	payload: TokenPayload,
	previousRefresh?: string,
): AuthToken {
	if (!payload.access_token) {
		throw new Error('Token endpoint returned no access_token');
	}

	return {
		accessToken: payload.access_token,
		refreshToken: payload.refresh_token ?? previousRefresh,
		tokenType: payload.token_type ?? 'Bearer',
		expiresAt: payload.expires_in
			? new Date(Date.now() + payload.expires_in * 1000)
			: undefined,
	};
}

async function postToken(
	metadata: AuthServerMetadata,
	form: URLSearchParams,
	fetchImpl: FetchLike,
): Promise<TokenPayload> {
	const response = await fetchImpl(metadata.token_endpoint, {
		method: 'POST',
		headers: {'Content-Type': 'application/x-www-form-urlencoded'},
		body: form.toString(),
	});

	const payload = (await readJson(response)) as TokenPayload;
	if (!response.ok) {
		throw new Error(
			`Token request failed (${response.status}): ${describeError(
				payload as Record<string, unknown>,
			)}`,
		);
	}

	return payload;
}

export async function exchangeCode(
	options: {
		metadata: AuthServerMetadata;
		clientId: string;
		redirectUri: string;
		code: string;
		verifier: string;
	},
	fetchImpl: FetchLike = fetch,
): Promise<AuthToken> {
	const form = new URLSearchParams({
		grant_type: 'authorization_code',
		code: options.code,
		redirect_uri: options.redirectUri,
		client_id: options.clientId,
		code_verifier: options.verifier,
	});

	return toAuthToken(await postToken(options.metadata, form, fetchImpl));
}

export async function refreshAccessToken(
	options: {
		metadata: AuthServerMetadata;
		clientId: string;
		refreshToken: string;
	},
	fetchImpl: FetchLike = fetch,
): Promise<AuthToken> {
	const form = new URLSearchParams({
		grant_type: 'refresh_token',
		refresh_token: options.refreshToken,
		client_id: options.clientId,
		scope: OAUTH_SCOPE,
	});

	return toAuthToken(
		await postToken(options.metadata, form, fetchImpl),
		options.refreshToken,
	);
}
