import crypto from 'node:crypto';
import test from 'ava';
import {
	buildAuthorizeUrl,
	createPkcePair,
	discoverAuthServer,
	exchangeCode,
	parseCallback,
	refreshAccessToken,
	registerClient,
	type AuthServerMetadata,
} from './oauth.js';

const METADATA: AuthServerMetadata = {
	issuer: 'https://api.example.test',
	authorization_endpoint: 'https://api.example.test/oauth2/auth',
	token_endpoint: 'https://api.example.test/oauth2/token',
	registration_endpoint: 'https://api.example.test/oauth2/register',
	code_challenge_methods_supported: ['plain', 'S256'],
	token_endpoint_auth_methods_supported: ['client_secret_post', 'none'],
};

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: {'Content-Type': 'application/json'},
	});
}

test('createPkcePair derives an S256 challenge from the verifier', t => {
	const {verifier, challenge} = createPkcePair();

	t.regex(verifier, /^[\w.~-]{43,128}$/);
	const expected = crypto
		.createHash('sha256')
		.update(verifier)
		.digest('base64url');
	t.is(challenge, expected);
});

test('createPkcePair is not deterministic', t => {
	t.not(createPkcePair().verifier, createPkcePair().verifier);
});

test('discoverAuthServer reads RFC 8414 metadata from the API base', async t => {
	const seen: string[] = [];
	const metadata = await discoverAuthServer(
		'https://api.example.test/',
		async url => {
			seen.push(String(url));
			return jsonResponse(METADATA);
		},
	);

	t.deepEqual(seen, [
		'https://api.example.test/.well-known/oauth-authorization-server',
	]);
	t.is(metadata.token_endpoint, METADATA.token_endpoint);
});

test('discoverAuthServer fails loudly when discovery is unavailable', async t => {
	await t.throwsAsync(
		discoverAuthServer('https://api.example.test', async () =>
			jsonResponse({error: 'nope'}, 502),
		),
		{message: /discovery failed.*502/i},
	);
});

test('discoverAuthServer rejects an authorization server without S256', async t => {
	await t.throwsAsync(
		discoverAuthServer('https://api.example.test', async () =>
			jsonResponse({...METADATA, code_challenge_methods_supported: ['plain']}),
		),
		{message: /S256/},
	);
});

test('registerClient registers a public loopback client', async t => {
	let body: Record<string, unknown> = {};
	const clientId = await registerClient(
		{
			metadata: METADATA,
			redirectUri: 'http://127.0.0.1:51789/callback',
			clientName: 'AgentArea CLI',
		},
		async (url, init) => {
			t.is(String(url), METADATA.registration_endpoint);
			body = JSON.parse(String(init?.body)) as Record<string, unknown>;
			return jsonResponse({client_id: 'client-123'});
		},
	);

	t.is(clientId, 'client-123');
	t.is(body['token_endpoint_auth_method'], 'none');
	t.deepEqual(body['redirect_uris'], ['http://127.0.0.1:51789/callback']);
	t.deepEqual(body['grant_types'], ['authorization_code', 'refresh_token']);
	t.deepEqual(body['response_types'], ['code']);
});

test('registerClient fails loudly when the server has no DCR endpoint', async t => {
	await t.throwsAsync(
		registerClient(
			{
				metadata: {...METADATA, registration_endpoint: undefined},
				redirectUri: 'http://127.0.0.1:51789/callback',
				clientName: 'AgentArea CLI',
			},
			async () => jsonResponse({}),
		),
		{message: /registration_endpoint/},
	);
});

test('buildAuthorizeUrl carries PKCE, state and the resource audience', t => {
	const url = new URL(
		buildAuthorizeUrl({
			metadata: METADATA,
			clientId: 'client-123',
			redirectUri: 'http://127.0.0.1:51789/callback',
			challenge: 'challenge-value',
			state: 'state-value',
			audience: 'https://api.example.test',
		}),
	);

	t.is(url.origin + url.pathname, METADATA.authorization_endpoint);
	t.is(url.searchParams.get('response_type'), 'code');
	t.is(url.searchParams.get('client_id'), 'client-123');
	t.is(url.searchParams.get('code_challenge'), 'challenge-value');
	t.is(url.searchParams.get('code_challenge_method'), 'S256');
	t.is(url.searchParams.get('state'), 'state-value');
	t.is(url.searchParams.get('audience'), 'https://api.example.test');
	t.is(url.searchParams.get('scope'), 'offline_access openid');
});

test('parseCallback returns the code when state matches', t => {
	t.is(parseCallback('/callback?code=abc&state=xyz', 'xyz'), 'abc');
});

test('parseCallback rejects a mismatched state', t => {
	t.throws(() => parseCallback('/callback?code=abc&state=other', 'xyz'), {
		message: /state/i,
	});
});

test('parseCallback surfaces the provider error', t => {
	t.throws(
		() =>
			parseCallback(
				'/callback?error=access_denied&error_description=user+said+no&state=xyz',
				'xyz',
			),
		{message: /access_denied.*user said no/},
	);
});

test('exchangeCode posts the PKCE verifier and normalises the token', async t => {
	let form = new URLSearchParams();
	const token = await exchangeCode(
		{
			metadata: METADATA,
			clientId: 'client-123',
			redirectUri: 'http://127.0.0.1:51789/callback',
			code: 'auth-code',
			verifier: 'verifier-value',
		},
		async (url, init) => {
			t.is(String(url), METADATA.token_endpoint);
			form = new URLSearchParams(String(init?.body));
			return jsonResponse({
				access_token: 'at',
				refresh_token: 'rt',
				token_type: 'bearer',
				expires_in: 3600,
			});
		},
	);

	t.is(form.get('grant_type'), 'authorization_code');
	t.is(form.get('code'), 'auth-code');
	t.is(form.get('code_verifier'), 'verifier-value');
	t.is(form.get('client_id'), 'client-123');
	t.is(token.accessToken, 'at');
	t.is(token.refreshToken, 'rt');
	t.true(token.expiresAt instanceof Date);
	t.true(token.expiresAt!.getTime() > Date.now());
});

test('exchangeCode fails loudly on an error response', async t => {
	await t.throwsAsync(
		exchangeCode(
			{
				metadata: METADATA,
				clientId: 'client-123',
				redirectUri: 'http://127.0.0.1:51789/callback',
				code: 'auth-code',
				verifier: 'verifier-value',
			},
			async () =>
				jsonResponse({error: 'invalid_grant', error_description: 'bad'}, 400),
		),
		{message: /invalid_grant.*bad/},
	);
});

test('refreshAccessToken keeps the previous refresh token when none is returned', async t => {
	const token = await refreshAccessToken(
		{
			metadata: METADATA,
			clientId: 'client-123',
			refreshToken: 'rt-old',
		},
		async () =>
			jsonResponse({access_token: 'at2', token_type: 'bearer', expires_in: 60}),
	);

	t.is(token.accessToken, 'at2');
	t.is(token.refreshToken, 'rt-old');
});
