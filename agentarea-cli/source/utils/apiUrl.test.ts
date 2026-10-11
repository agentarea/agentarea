import test from 'ava';
import {apiOrigin, isSameApiOrigin, normalizeApiUrl} from './apiUrl.js';

test('apiOrigin is scheme + host + port, normalised', t => {
	t.is(apiOrigin('https://API.Example.test/v1/'), 'https://api.example.test');
	t.is(apiOrigin('https://api.example.test:443'), 'https://api.example.test');
	t.is(apiOrigin('http://localhost:8000/'), 'http://localhost:8000');
	t.is(apiOrigin('ftp://api.example.test'), null);
	t.is(apiOrigin('not a url'), null);
	t.is(apiOrigin(undefined), null);
});

test('isSameApiOrigin binds a token to the host it was issued for', t => {
	t.true(isSameApiOrigin('https://good.example', 'https://GOOD.example:443/'));
	t.false(isSameApiOrigin('https://good.example', 'http://good.example'));
	t.false(isSameApiOrigin('https://good.example', 'https://good.example:8443'));
	t.false(isSameApiOrigin('https://good.example', 'https://evil.example'));
	t.false(isSameApiOrigin(undefined, 'https://good.example'));
});

test('normalizeApiUrl drops trailing slashes', t => {
	t.is(
		normalizeApiUrl(' https://api.example.test// '),
		'https://api.example.test',
	);
});
