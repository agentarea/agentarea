import test from 'ava';
import {configManager} from '../utils/config.js';
import {tokenStorage} from '../utils/storage.js';
import {type AuthToken} from '../types/index.js';
import {apiClient} from './apiClient.js';
import {
	applyApiUrlFlag,
	getApiBaseUrl,
	resolveToken,
	setRuntimeToken,
} from './apiRuntime.js';

const ISSUED_FOR_GOOD: AuthToken = {
	accessToken: 'TOKEN-ISSUED-FOR-GOOD',
	tokenType: 'Bearer',
	apiUrl: 'https://good.example',
	expiresAt: new Date(Date.now() + 60 * 60 * 1000),
};

function targetApi(url: string): void {
	// Env only: configManager.reinitialize reads, it never writes the saved config.
	process.env['AGENTAREA_API_URL'] = url;
	configManager.reinitialize();
}

test.beforeEach(() => {
	tokenStorage.getToken = async () => ISSUED_FOR_GOOD;
	setRuntimeToken(undefined);
	apiClient.clearToken();
});

test.serial(
	'resolveToken does not hand the stored token to another host',
	async t => {
		targetApi('http://127.0.0.1:9');

		t.is(await resolveToken(), undefined);
	},
);

test.serial(
	'resolveToken sends the stored token to the host it was issued for',
	async t => {
		targetApi('https://good.example/');

		t.is(await resolveToken(), 'TOKEN-ISSUED-FOR-GOOD');
	},
);

test.serial(
	'an explicit --token is the caller’s choice and is not host-bound',
	async t => {
		targetApi('http://127.0.0.1:9');
		setRuntimeToken('EXPLICIT');

		t.is(await resolveToken(), 'EXPLICIT');
	},
);

test.serial(
	'getApiBaseUrl honours AGENTAREA_API_URL, and --api-url outranks it',
	t => {
		targetApi('https://env.example/');
		t.is(getApiBaseUrl(), 'https://env.example');

		applyApiUrlFlag(undefined);
		t.is(getApiBaseUrl(), 'https://env.example');

		applyApiUrlFlag('https://flag.example');
		t.is(getApiBaseUrl(), 'https://flag.example');
	},
);
