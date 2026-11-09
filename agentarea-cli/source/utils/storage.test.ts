import test from 'ava';
import {type AuthToken} from '../types/index.js';
import {memoryTokenStorage} from './storage.fixture.js';

const LEGACY_KEY = 'auth_token';

function token(apiUrl: string | undefined, accessToken: string): AuthToken {
	return {
		accessToken,
		tokenType: 'Bearer',
		apiUrl,
		expiresAt: new Date(Date.now() + 60 * 60 * 1000),
	};
}

test('a sign-in to one host does not replace another host’s', async t => {
	const {storage} = memoryTokenStorage();

	await storage.saveToken(token('http://localhost:8000', 'LOCAL'));
	await storage.saveToken(token('https://api.example.test', 'REMOTE'));

	t.is(
		(await storage.getTokenFor('http://localhost:8000/'))?.accessToken,
		'LOCAL',
	);
	t.is(
		(await storage.getTokenFor('https://API.example.test:443'))?.accessToken,
		'REMOTE',
	);
	t.is(await storage.getTokenFor('https://other.example.test'), null);
});

test('each host’s sign-in is stored under its origin', async t => {
	const {entries, storage} = memoryTokenStorage();

	await storage.saveToken(token('https://api.example.test/v1/', 'REMOTE'));

	t.deepEqual([...entries.keys()], ['https://api.example.test']);
});

test('a token with no recorded host is refused, not stored', async t => {
	const {entries, storage} = memoryTokenStorage();

	await t.throwsAsync(storage.saveToken(token(undefined, 'NOWHERE')));
	t.is(entries.size, 0);
});

test('clearToken signs out of that host only', async t => {
	const {storage} = memoryTokenStorage();
	await storage.saveToken(token('http://localhost:8000', 'LOCAL'));
	await storage.saveToken(token('https://api.example.test', 'REMOTE'));

	await storage.clearToken('https://api.example.test');

	t.is(await storage.getTokenFor('https://api.example.test'), null);
	t.is(
		(await storage.getTokenFor('http://localhost:8000'))?.accessToken,
		'LOCAL',
	);
});

test('clearAllTokens signs out of every host', async t => {
	const {entries, storage} = memoryTokenStorage();
	await storage.saveToken(token('http://localhost:8000', 'LOCAL'));
	await storage.saveToken(token('https://api.example.test', 'REMOTE'));

	t.deepEqual((await storage.clearAllTokens()).sort(), [
		'http://localhost:8000',
		'https://api.example.test',
	]);
	t.is(entries.size, 0);
});

test('the single legacy sign-in moves to its host’s slot once', async t => {
	const {entries, storage} = memoryTokenStorage({
		[LEGACY_KEY]: JSON.stringify(token('https://api.example.test', 'OLD')),
	});

	t.is(
		(await storage.getTokenFor('https://api.example.test'))?.accessToken,
		'OLD',
	);
	t.false(entries.has(LEGACY_KEY));
	t.true(entries.has('https://api.example.test'));
	t.is(await storage.getTokenFor('http://localhost:8000'), null);
});

test('the legacy sign-in does not overwrite a host already signed in', async t => {
	const {entries, storage} = memoryTokenStorage({
		[LEGACY_KEY]: JSON.stringify(token('https://api.example.test', 'OLD')),
		'https://api.example.test': JSON.stringify(
			token('https://api.example.test', 'NEW'),
		),
	});

	t.is(
		(await storage.getTokenFor('https://api.example.test'))?.accessToken,
		'NEW',
	);
	t.false(entries.has(LEGACY_KEY));
});

test('a legacy sign-in with no recorded host is never sent anywhere', async t => {
	const {entries, storage} = memoryTokenStorage({
		[LEGACY_KEY]: JSON.stringify(token(undefined, 'UNBOUND')),
	});

	t.is(await storage.getTokenFor('http://localhost:8000'), null);
	t.is(await storage.getTokenFor('https://api.example.test'), null);
	t.true(entries.has(LEGACY_KEY));
});

test('signing in again drops an unbound legacy sign-in', async t => {
	const {entries, storage} = memoryTokenStorage({
		[LEGACY_KEY]: JSON.stringify(token(undefined, 'UNBOUND')),
	});

	await storage.saveToken(token('http://localhost:8000', 'LOCAL'));

	t.false(entries.has(LEGACY_KEY));
});
