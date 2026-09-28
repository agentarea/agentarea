import {createHash} from 'node:crypto';
import {promises as fs} from 'node:fs';
import http from 'node:http';
import {type AddressInfo} from 'node:net';
import os from 'node:os';
import path from 'node:path';
import test from 'ava';
import {
	chunk,
	collectFiles,
	mapLimit,
	putFile,
	remotePath,
	summarize,
} from './fileSync.js';

async function tree(files: Record<string, string>): Promise<string> {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), 'aa-sync-'));
	for (const [relative, content] of Object.entries(files)) {
		const absolute = path.join(root, relative);
		// eslint-disable-next-line no-await-in-loop
		await fs.mkdir(path.dirname(absolute), {recursive: true});
		// eslint-disable-next-line no-await-in-loop
		await fs.writeFile(absolute, content);
	}

	return root;
}

const sha = (text: string) => createHash('sha256').update(text).digest('hex');

test('collects nested files with posix paths and content digests', async t => {
	const root = await tree({'b.md': 'b', 'wiki/api/auth.md': 'auth'});

	const files = await collectFiles(root);

	t.deepEqual(
		files.map(f => [f.relative, f.sha256]),
		[
			['b.md', sha('b')],
			['wiki/api/auth.md', sha('auth')],
		],
	);
});

test('skips .git and caller excludes, by name or by path', async t => {
	const root = await tree({
		'.git/HEAD': 'ref',
		'data/state.db': 'x',
		'wiki/data/keep.md': 'keep',
		'wiki/.DS_Store': 'x',
		'outputs/big.html': 'x',
	});

	const files = await collectFiles(root, [
		'.git',
		'.DS_Store',
		'data/state.db',
		'outputs',
	]);

	t.deepEqual(
		files.map(f => f.relative),
		['wiki/data/keep.md'],
	);
});

test('does not follow symlinks out of the folder', async t => {
	const outside = await tree({'secret.txt': 's'});
	const root = await tree({'a.md': 'a'});
	await fs.symlink(outside, path.join(root, 'link'));

	const files = await collectFiles(root);

	t.deepEqual(
		files.map(f => f.relative),
		['a.md'],
	);
});

test('remote paths join the prefix without doubled slashes', t => {
	t.is(remotePath('wiki', 'a/b.md'), 'wiki/a/b.md');
	t.is(remotePath('/wiki/', 'b.md'), 'wiki/b.md');
	t.is(remotePath('', 'b.md'), 'b.md');
});

test('chunks into batches no larger than the limit', t => {
	t.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
	t.deepEqual(chunk([], 100), []);
});

test('the summary names failures only when there are some', t => {
	t.is(
		summarize({uploaded: 3, unchanged: 5, failed: []}),
		'3 uploaded, 5 unchanged',
	);
	t.is(
		summarize({uploaded: 0, unchanged: 1, failed: [{path: 'a', error: 'x'}]}),
		'0 uploaded, 1 unchanged, 1 failed',
	);
});

test('putFile streams the file with the signed headers and a length', async t => {
	const root = await tree({'a.bin': 'payload'});
	let seen: {method?: string; headers: http.IncomingHttpHeaders; body: string} =
		{headers: {}, body: ''};
	const server = http.createServer((request, response) => {
		let body = '';
		request.on('data', (part: Uint8Array) => {
			body += Buffer.from(part).toString();
		});
		request.on('end', () => {
			seen = {method: request.method, headers: request.headers, body};
			response.writeHead(200).end();
		});
	});
	await new Promise<void>(resolve => {
		server.listen(0, '127.0.0.1', resolve);
	});
	const {port} = server.address() as AddressInfo;

	const status = await putFile(
		`http://127.0.0.1:${port}/bucket/a.bin?X-Amz-Signature=x`,
		'PUT',
		{'x-amz-meta-sha256': sha('payload')},
		path.join(root, 'a.bin'),
	);
	server.close();

	t.is(status, 200);
	t.is(seen.method, 'PUT');
	t.is(seen.body, 'payload');
	t.is(seen.headers['content-length'], '7');
	t.is(seen.headers['x-amz-meta-sha256'], sha('payload'));
});

test('putFile reports the status of a rejected upload', async t => {
	const root = await tree({'a.bin': 'x'});
	const server = http.createServer((_request, response) => {
		response.writeHead(403).end('SignatureDoesNotMatch');
	});
	await new Promise<void>(resolve => {
		server.listen(0, '127.0.0.1', resolve);
	});
	const {port} = server.address() as AddressInfo;

	const status = await putFile(
		`http://127.0.0.1:${port}/a.bin`,
		'PUT',
		{},
		path.join(root, 'a.bin'),
	);
	server.close();

	t.is(status, 403);
});

test('mapLimit runs every item and never exceeds the limit', async t => {
	let inFlight = 0;
	let peak = 0;
	const seen: number[] = [];

	await mapLimit([1, 2, 3, 4, 5, 6, 7], 3, async item => {
		inFlight++;
		peak = Math.max(peak, inFlight);
		await new Promise(resolve => {
			setTimeout(resolve, 5);
		});
		seen.push(item);
		inFlight--;
	});

	t.deepEqual(
		seen.sort((a, b) => a - b),
		[1, 2, 3, 4, 5, 6, 7],
	);
	t.true(peak <= 3);
});
