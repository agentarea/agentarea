import test from 'ava';
import {tokenStorage} from '../utils/storage.js';
import {memoryTokenStorage} from '../utils/storage.fixture.js';
import {type AuthToken} from '../types/index.js';
import {loadAccessToken} from './login.js';

async function storeToken(token: AuthToken | null): Promise<void> {
	const {storage} = memoryTokenStorage();
	if (token) {
		await storage.saveToken(token);
	}

	tokenStorage.getTokenFor = async apiUrl => storage.getTokenFor(apiUrl);
}

const ISSUED_FOR_GOOD: AuthToken = {
	accessToken: 'TOKEN-ISSUED-FOR-GOOD',
	tokenType: 'Bearer',
	apiUrl: 'https://good.example',
	expiresAt: new Date(Date.now() + 60 * 60 * 1000),
};

test.serial(
	'loadAccessToken does not send a token to another host',
	async t => {
		await storeToken(ISSUED_FOR_GOOD);

		t.is(await loadAccessToken('http://127.0.0.1:8000'), null);
		t.is(await loadAccessToken('https://evil.example'), null);
		t.is(await loadAccessToken('http://good.example'), null);
		t.is(await loadAccessToken('https://good.example:8443'), null);
	},
);

test.serial(
	'loadAccessToken returns the token for the host it was issued for',
	async t => {
		await storeToken(ISSUED_FOR_GOOD);

		t.is(
			await loadAccessToken('https://good.example'),
			'TOKEN-ISSUED-FOR-GOOD',
		);
		t.is(
			await loadAccessToken('https://GOOD.example:443/'),
			'TOKEN-ISSUED-FOR-GOOD',
		);
	},
);

test.serial('loadAccessToken returns null when nothing is stored', async t => {
	await storeToken(null);

	t.is(await loadAccessToken('https://good.example'), null);
});
