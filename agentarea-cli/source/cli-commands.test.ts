import http from 'node:http';
import {type AddressInfo} from 'node:net';
import test from 'ava';
import {configManager} from './utils/config.js';
import {handleCliCommand} from './cli-commands.js';

test('login targets AGENTAREA_API_URL when --api-url is not passed', async t => {
	const seen: string[] = [];
	const server = http.createServer((request, response) => {
		seen.push(request.url ?? '');
		// No metadata: login stops at discovery, before any browser or listener.
		response.writeHead(404).end();
	});
	await new Promise<void>(resolve => {
		server.listen(0, '127.0.0.1', resolve);
	});
	t.teardown(() => server.close());

	const api = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
	// Env only: configManager.reinitialize reads, it never writes the saved config.
	process.env['AGENTAREA_API_URL'] = api;
	configManager.reinitialize();

	await t.throwsAsync(handleCliCommand('login', undefined, {args: ['login']}), {
		message: new RegExp(`OAuth discovery failed \\(404\\) at ${api}/`),
	});
	t.deepEqual(seen, ['/.well-known/oauth-authorization-server']);
});
