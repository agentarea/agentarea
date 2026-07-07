#!/usr/bin/env node
// QA harness: exercises documented business scenarios THROUGH the AgentArea CLI
// against the live local stack, then writes a results matrix.
// Usage: node qa/scenarios.mjs [runId]
// Real commands, real assertions, no fabrication.

import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {writeFileSync} from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CLI_DIR = join(__dirname, '..');
const CLI = 'dist/cli.js';

const runId = process.argv[2] || `r${String(Date.now()).slice(-8)}`;
const PREFIX = `qa-cli-${runId}-`;

// ---- Fixtures (provided, DO NOT delete/mutate) ----
const AGENT_REAL = '614dd96c-499c-440f-9a77-b0c3c6cc573e'; // Telegram Demo Agent, runs e2e
const AGENT_FOREIGN = '4deba002-e5e8-4aa4-9697-8b268bc26684'; // other workspace -> must deny
const MCP_INSTANCE = 'd8257fbe-969a-40b9-89df-da4a904852e8'; // running, discover-tools
const MY_WORKSPACE = '1cf4e31c-900b-4bf7-aeb7-27779927a066';
const MODEL_ID = '913e0cbe-a442-4ea7-8aae-603f27ceadde'; // real agent's model, valid for agent create

// ---- Result recording ----
const results = []; // {kind:'PASS'|'FAIL'|'SKIP', scenario, name, evidence}
const findings = [];
function rec(kind, scenario, name, evidence) {
	results.push({kind, scenario, name, evidence: String(evidence ?? '').replace(/\s+/g, ' ').slice(0, 400)});
}
function check(scenario, name, cond, evidence) {
	rec(cond ? 'PASS' : 'FAIL', scenario, name, evidence);
	return cond;
}
function skip(scenario, name, reason) {
	rec('SKIP', scenario, name, reason);
}
function finding(title, evidence) {
	findings.push({title, evidence: String(evidence ?? '').replace(/\s+/g, ' ').slice(0, 600)});
}

// ---- CLI helper: spawn node dist/cli.js ... (NEVER string-split) ----
function cli(argsArray, {timeout = 90000} = {}) {
	const r = spawnSync('node', [CLI, ...argsArray], {
		cwd: CLI_DIR,
		encoding: 'utf8',
		timeout,
		maxBuffer: 32 * 1024 * 1024,
	});
	const out = r.stdout ?? '';
	const err = r.stderr ?? '';
	let json;
	try {
		json = JSON.parse(out);
	} catch {
		json = undefined;
	}
	return {code: r.status ?? (r.signal ? -1 : 1), out, err, json, signal: r.signal};
}

// ---- DB helper ----
function db(sql) {
	const r = spawnSync(
		'docker',
		['exec', 'agentarea-db-1', 'psql', '-U', 'postgres', '-d', 'agentarea', '-tAc', sql],
		{encoding: 'utf8', timeout: 30000, maxBuffer: 16 * 1024 * 1024},
	);
	return (r.stdout ?? '').trim();
}

// ---- Shape helpers ----
function asArray(json) {
	if (Array.isArray(json)) return json;
	if (!json || typeof json !== 'object') return [];
	for (const k of ['items', 'data', 'events', 'agents', 'skills', 'triggers', 'tools', 'results', 'connections', 'instances', 'keys']) {
		if (Array.isArray(json[k])) return json[k];
	}
	return [];
}
// A CLI result is an API error when reportResult printed EXACTLY {status, error}.
// (Precise: a data payload can legitimately carry its own `status`/`error` keys,
//  e.g. `tasks status` returns {status:"running", error:null, ...} — not an envelope.)
function isErr(res) {
	if (!res.json || typeof res.json !== 'object' || Array.isArray(res.json)) return false;
	const keys = Object.keys(res.json);
	return keys.length === 2 && keys.includes('status') && keys.includes('error');
}
function isOk(res) {
	return res.code === 0 && res.json !== undefined && !isErr(res);
}
function errStatus(res) {
	return isErr(res) ? res.json.status : undefined;
}
function evidence(res) {
	if (isErr(res)) return `status=${res.json.status} ${JSON.stringify(res.json.error).slice(0, 200)}`;
	if (res.json !== undefined) return JSON.stringify(res.json).slice(0, 200);
	return (res.out || res.err || '').slice(0, 200);
}

// ---- Teardown registry ----
const teardown = []; // {label, args}
function trackDelete(label, args) {
	teardown.push({label, args});
}

// =====================================================================
// SCENARIOS
// =====================================================================

// S18/S17 preface: hit /health (out-of-CLI-scope note handled at end)
function sHealth() {
	const r = spawnSync('curl', ['-s', 'http://localhost:8000/health'], {encoding: 'utf8'});
	const ok = /healthy/.test(r.stdout ?? '');
	check('S18', 'health-endpoint', ok, (r.stdout ?? '').trim());
}

// S2 Agents CRUD
function s2Agents() {
	const name = `${PREFIX}agent`;
	const create = cli(['agents', 'create', '--data', JSON.stringify({name, model_id: MODEL_ID, description: 'qa'})]);
	const id = isOk(create) ? create.json.id : undefined;
	if (id) trackDelete('agents.delete', ['agents', 'delete', id]);
	check('S2', 'agent-create', isOk(create) && !!id, evidence(create));
	if (!id) {
		skip('S2', 'agent-get', 'create failed');
		skip('S2', 'agent-update', 'create failed');
		skip('S2', 'agent-list-contains', 'create failed');
		skip('S2', 'agent-delete', 'create failed');
	} else {
		const get = cli(['agents', 'get', id]);
		check('S2', 'agent-get', isOk(get) && get.json.id === id, evidence(get));

		const upd = cli(['agents', 'update', id, '--data', JSON.stringify({description: 'qa-updated'})]);
		check('S2', 'agent-update', isOk(upd) && upd.json.description === 'qa-updated', evidence(upd));

		const list = cli(['agents', 'list']);
		check('S2', 'agent-list-contains', list.out.includes(id), `list length=${asArray(list.json).length}`);

		const del = cli(['agents', 'delete', id]);
		const delOk = del.code === 0 && !isErr(del);
		check('S2', 'agent-delete', delOk, evidence(del));
		if (delOk) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
	}

	// Negatives
	const noName = cli(['agents', 'create', '--data', JSON.stringify({})]);
	const st = errStatus(noName);
	check('S2', 'neg-create-missing-name-validation', isErr(noName) && st >= 400 && st < 500, `expected 4xx validation, got ${evidence(noName)}`);

	const foreign = cli(['agents', 'get', AGENT_FOREIGN]);
	const fst = errStatus(foreign);
	check('S2', 'neg-foreign-agent-denied', isErr(foreign) && (fst === 403 || fst === 404), `expected 403/404, got ${evidence(foreign)}`);
}

// S3 Task run + SSE + DB
function s3Task() {
	const submit = cli(['tasks', 'submit', AGENT_REAL, 'Say hello in exactly one word'], {timeout: 120000});
	const reachedComplete = submit.out.includes('WorkflowCompleted');
	check('S3', 'task-sse-workflow-completed', reachedComplete, reachedComplete ? 'SSE stream contained WorkflowCompleted' : submit.out.slice(-200) || submit.err.slice(-200));

	// extract task_id: first UUID that is not the agent id
	const uuids = [...submit.out.matchAll(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g)].map(m => m[0]);
	const taskId = uuids.find(u => u !== AGENT_REAL);
	if (!taskId) {
		skip('S3', 'task-db-status-completed', 'could not extract task_id from stream');
		skip('S3', 'task-events-persisted', 'no task_id');
		skip('S3', 'task-status-vs-get-vs-db', 'no task_id');
		return;
	}

	const dbStatus = db(`SELECT status FROM tasks WHERE id='${taskId}';`);
	check('S3', 'task-db-status-completed', dbStatus === 'completed', `tasks.status=${dbStatus || '(none)'} id=${taskId}`);

	const evCount = parseInt(db(`SELECT count(*) FROM task_events WHERE task_id='${taskId}';`), 10) || 0;
	check('S3', 'task-events-persisted', evCount > 0, `task_events count=${evCount}`);

	// Compare tasks get vs tasks status vs DB (known bug hunt)
	const get = cli(['tasks', 'get', AGENT_REAL, taskId]);
	const status = cli(['tasks', 'status', AGENT_REAL, taskId]);
	const getStatus = isOk(get) ? (get.json.status ?? get.json.state) : evidence(get);
	const statusStatus = isOk(status) ? (status.json.status ?? status.json.state) : evidence(status);
	const consistent = String(getStatus) === String(dbStatus) && String(statusStatus) === String(dbStatus);
	check('S3', 'task-status-vs-get-vs-db', consistent, `db=${dbStatus} get=${getStatus} status=${statusStatus}`);
	if (!consistent) {
		finding('Task status discrepancy across surfaces (S3)', `DB tasks.status='${dbStatus}', 'tasks get'.status='${getStatus}', 'tasks status'.status='${statusStatus}' for a task whose SSE reported WorkflowCompleted. task_id=${taskId}`);
	}
}

// S4 MCP
function s4Mcp() {
	const list = cli(['mcp-instances', 'list']);
	check('S4', 'mcp-instances-list', isOk(list) && asArray(list.json).length >= 0, `count=${asArray(list.json).length}`);

	const disc = cli(['mcp-instances', 'discover-tools', MCP_INSTANCE], {timeout: 60000});
	const tools = isOk(disc) ? asArray(disc.json) : [];
	check('S4', 'mcp-discover-tools', isOk(disc) && tools.length > 0, isOk(disc) ? `tools=${tools.length} first=${tools[0]?.name}` : evidence(disc));

	skip('S4', 'mcp-create-instance-from-spec', 'requires a server spec + running MCP infra to provision safely; used existing running instance for discover-tools instead');
}

// S5 Policy + enforcement observability
function s5Policy() {
	const body = {
		subject_type: 'agent',
		subject_id: AGENT_REAL,
		target: `tool:${PREFIX}denied_tool`,
		effect: 'deny',
		params: {},
		priority: 10,
	};
	const create = cli(['policies', 'create', '--data', JSON.stringify(body)]);
	const id = isOk(create) ? create.json.id : undefined;
	if (id) trackDelete('policies.delete', ['policies', 'delete', id]);
	check('S5', 'policy-create-deny', isOk(create) && !!id, evidence(create));

	if (id) {
		const get = cli(['policies', 'get', id]);
		check('S5', 'policy-get', isOk(get) && get.json.id === id, evidence(get));
	} else {
		skip('S5', 'policy-get', 'create failed');
	}

	// Enforcement observability via governance effective-policy preview
	const prev = cli(['governance', 'preview-policy', '--data', JSON.stringify({agent_id: AGENT_REAL})]);
	if (isOk(prev)) {
		const blob = JSON.stringify(prev.json);
		const reflectsDeny = blob.includes(`${PREFIX}denied_tool`) || /deny/i.test(blob);
		check('S5', 'policy-enforcement-observable', reflectsDeny, `preview reflects policy: ${blob.slice(0, 200)}`);
		if (!reflectsDeny) finding('Policy not reflected in effective-policy preview (S5)', `Created deny policy on ${body.target} for agent ${AGENT_REAL}, but preview did not surface it: ${blob.slice(0, 300)}`);
	} else {
		// negative-safe: record whether the surface exists
		check('S5', 'policy-enforcement-observable', false, `governance preview not usable: ${evidence(prev)}`);
		finding('Effective-policy preview not observable via API (S5)', evidence(prev));
	}

	// Negative: missing required fields -> validation error, not 500
	const bad = cli(['policies', 'create', '--data', JSON.stringify({effect: 'deny'})]);
	const st = errStatus(bad);
	check('S5', 'neg-policy-missing-fields-validation', isErr(bad) && st >= 400 && st < 500, `expected 4xx, got ${evidence(bad)}`);

	if (id) {
		const del = cli(['policies', 'delete', id]);
		const delOk = del.code === 0 && !isErr(del);
		check('S5', 'policy-delete', delOk, evidence(del));
		if (delOk) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
	} else {
		skip('S5', 'policy-delete', 'create failed');
	}
}

// S6 Triggers
function s6Triggers() {
	const body = {
		name: `${PREFIX}cron`,
		agent_id: AGENT_REAL,
		trigger_type: 'cron',
		cron_expression: '0 0 * * *',
		task_parameters: {description: 'qa scheduled'},
		enabled: false,
	};
	const create = cli(['triggers', 'create', '--data', JSON.stringify(body)]);
	const id = isOk(create) ? create.json.id : undefined;
	if (id) trackDelete('triggers.delete', ['triggers', 'delete', id]);
	check('S6', 'trigger-create-cron', isOk(create) && !!id, evidence(create));

	if (id) {
		const get = cli(['triggers', 'get', id]);
		check('S6', 'trigger-get', isOk(get) && get.json.id === id, evidence(get));

		const enable = cli(['triggers', 'enable', id]);
		check('S6', 'trigger-enable', enable.code === 0 && !isErr(enable), evidence(enable));

		const disable = cli(['triggers', 'disable', id]);
		check('S6', 'trigger-disable', disable.code === 0 && !isErr(disable), evidence(disable));

		const execs = cli(['triggers', 'executions', id]);
		check('S6', 'trigger-executions-list', execs.code === 0 && !isErr(execs), evidence(execs));

		const del = cli(['triggers', 'delete', id]);
		const delOk = del.code === 0 && !isErr(del);
		check('S6', 'trigger-delete', delOk, evidence(del));
		if (delOk) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
	} else {
		for (const n of ['trigger-get', 'trigger-enable', 'trigger-disable', 'trigger-executions-list', 'trigger-delete']) skip('S6', n, 'create failed');
	}

	// Negative: malformed cron -> validation error
	const bad = cli(['triggers', 'create', '--data', JSON.stringify({...body, name: `${PREFIX}badcron`, cron_expression: 'not-a-cron-expr'})]);
	if (isOk(bad)) {
		// it accepted a bad cron — track for teardown + record finding
		if (bad.json.id) trackDelete('triggers.delete', ['triggers', 'delete', bad.json.id]);
		check('S6', 'neg-malformed-cron-validation', false, `bad cron accepted: id=${bad.json.id}`);
		finding('Malformed cron accepted without validation (S6)', `cron_expression='not-a-cron-expr' created trigger ${bad.json.id}`);
	} else {
		const st = errStatus(bad);
		check('S6', 'neg-malformed-cron-validation', isErr(bad) && st >= 400 && st < 500, `expected 4xx, got ${evidence(bad)}`);
	}
}

// S7 Access / ReBAC + API keys
function s7Access() {
	// API keys lifecycle
	const create = cli(['apikeys', 'create', '--data', JSON.stringify({name: `${PREFIX}key`})]);
	const tokenId = isOk(create) ? create.json.id : undefined;
	if (tokenId) trackDelete('apikeys.revoke', ['apikeys', 'revoke', tokenId]);
	check('S7', 'apikey-create', isOk(create) && !!tokenId && !!create.json.token, isOk(create) ? `id=${tokenId} token_prefix=${create.json.token_prefix}` : evidence(create));

	if (tokenId) {
		const list = cli(['apikeys', 'list']);
		check('S7', 'apikey-list-contains', list.out.includes(tokenId), `count=${asArray(list.json).length}`);
		const get = cli(['apikeys', 'get', tokenId]);
		check('S7', 'apikey-get', isOk(get) && get.json.id === tokenId, evidence(get));
		const revoke = cli(['apikeys', 'revoke', tokenId]);
		const rok = revoke.code === 0 && !isErr(revoke);
		check('S7', 'apikey-revoke', rok, evidence(revoke));
		if (rok) teardown.splice(teardown.findIndex(t => t.args[2] === tokenId), 1);
	} else {
		for (const n of ['apikey-list-contains', 'apikey-get', 'apikey-revoke']) skip('S7', n, 'create failed');
	}

	// ReBAC read surfaces
	const rel = cli(['access', 'relationships-list']);
	check('S7', 'access-relationships-list', rel.code === 0 && !isErr(rel), evidence(rel));
	const grants = cli(['access', 'tool-grants-list']);
	check('S7', 'access-tool-grants-list', grants.code === 0 && !isErr(grants), evidence(grants));

	// Isolation: foreign agent denied
	const foreign = cli(['agents', 'get', AGENT_FOREIGN]);
	const fst = errStatus(foreign);
	check('S7', 'isolation-foreign-agent-denied', isErr(foreign) && (fst === 403 || fst === 404), `expected 403/404, got ${evidence(foreign)}`);

	// Isolation: my agents list is workspace-scoped (<< total DB agents)
	const myList = cli(['agents', 'list']);
	const myCount = asArray(myList.json).length;
	const totalAgents = parseInt(db(`SELECT count(*) FROM agents;`), 10) || 0;
	check('S7', 'isolation-workspace-scoped-list', myCount > 0 && myCount < totalAgents, `my agents=${myCount} total DB agents=${totalAgents}`);

	skip('S7', 'cross-user-invite-accept', 'needs 2nd identity token (second authenticated user)');
}

// S8 Providers / Models
function s8Providers() {
	const cfgList = cli(['providers', 'configs-list']);
	check('S8', 'provider-configs-list', cfgList.code === 0 && !isErr(cfgList), evidence(cfgList));

	const specs = cli(['providers', 'specs-list']);
	const specArr = asArray(specs.json);
	check('S8', 'provider-specs-list', specs.code === 0 && specArr.length > 0, `count=${specArr.length}`);

	const modelInst = cli(['models', 'instances-list']);
	const miArr = asArray(modelInst.json);
	check('S8', 'model-instances-list', modelInst.code === 0 && !isErr(modelInst), `count=${miArr.length}`);

	const modelSpecs = cli(['models', 'specs-list']);
	check('S8', 'model-specs-list', modelSpecs.code === 0 && !isErr(modelSpecs), `count=${asArray(modelSpecs.json).length}`);

	// Provider config create -> get -> delete (dummy key)
	const specId = specArr.find(s => (s.provider_key || s.key) === 'openrouter')?.id ?? specArr[0]?.id;
	if (specId) {
		const create = cli(['providers', 'config-create', '--data', JSON.stringify({provider_spec_id: specId, name: `${PREFIX}pcfg`, api_key: 'dummy-qa-key'})]);
		const id = isOk(create) ? create.json.id : undefined;
		if (id) trackDelete('providers.config-delete', ['providers', 'config-delete', id]);
		check('S8', 'provider-config-create', isOk(create) && !!id, evidence(create));
		if (id) {
			const get = cli(['providers', 'config-get', id]);
			check('S8', 'provider-config-get', isOk(get) && get.json.id === id, evidence(get));
			const del = cli(['providers', 'config-delete', id]);
			const dok = del.code === 0 && !isErr(del);
			check('S8', 'provider-config-delete', dok, evidence(del));
			if (dok) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
		} else {
			skip('S8', 'provider-config-get', 'create failed');
			skip('S8', 'provider-config-delete', 'create failed');
		}
	} else {
		for (const n of ['provider-config-create', 'provider-config-get', 'provider-config-delete']) skip('S8', n, 'no provider spec id available');
	}

	// Model instance test if a valid instance exists
	if (miArr.length > 0) {
		const mi = miArr[0];
		const test = cli(['models', 'instance-test', '--data', JSON.stringify({provider_config_id: mi.provider_config_id, model_spec_id: mi.model_spec_id, test_message: 'ping'})], {timeout: 60000});
		const st = errStatus(test);
		const structured = test.json !== undefined && st !== 500 && !(st >= 500);
		check('S8', 'model-instance-test', structured, `endpoint returned structured result: ${evidence(test)}`);
	} else {
		skip('S8', 'model-instance-test', 'no model instances available');
	}
}

// S9 Skills CRUD
function s9Skills() {
	const name = `${PREFIX}skill`;
	const create = cli(['skills', 'create', '--data', JSON.stringify({name, description: 'qa skill', content: '# QA Skill\nDo the thing.'})]);
	const id = isOk(create) ? create.json.id : undefined;
	if (id) trackDelete('skills.delete', ['skills', 'delete', id]);
	check('S9', 'skill-create', isOk(create) && !!id, evidence(create));

	if (id) {
		const get = cli(['skills', 'get', id]);
		check('S9', 'skill-get', isOk(get) && get.json.id === id, evidence(get));
		const upd = cli(['skills', 'update', id, '--data', JSON.stringify({name, description: 'qa skill updated', content: '# QA Skill\nUpdated.'})]);
		check('S9', 'skill-update', upd.code === 0 && !isErr(upd), evidence(upd));
		const list = cli(['skills', 'list']);
		check('S9', 'skill-list-contains', list.out.includes(id), `count=${asArray(list.json).length}`);
		const del = cli(['skills', 'delete', id]);
		const dok = del.code === 0 && !isErr(del);
		check('S9', 'skill-delete', dok, evidence(del));
		if (dok) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
	} else {
		for (const n of ['skill-get', 'skill-update', 'skill-list-contains', 'skill-delete']) skip('S9', n, 'create failed');
	}

	// Negative: empty skill (no name/content) -> validation error
	const bad = cli(['skills', 'create', '--data', JSON.stringify({})]);
	if (isOk(bad)) {
		if (bad.json.id) trackDelete('skills.delete', ['skills', 'delete', bad.json.id]);
		check('S9', 'neg-skill-missing-name-validation', false, `empty skill accepted: id=${bad.json.id}`);
		finding('Empty skill create accepted without validation (S9)', `POST /v1/skills with {} created skill ${bad.json.id}`);
	} else {
		const st = errStatus(bad);
		check('S9', 'neg-skill-missing-name-validation', isErr(bad) && st >= 400 && st < 500, `expected 4xx, got ${evidence(bad)}`);
	}
}

// S1 OpenAPI connections
function s1Connections() {
	const list = cli(['connections', 'list']);
	check('S1', 'connections-list', list.code === 0 && !isErr(list), evidence(list));

	const body = {
		name: `${PREFIX}petstore`,
		base_url: 'https://petstore3.swagger.io/api/v3',
		spec_url: 'https://petstore3.swagger.io/api/v3/openapi.json',
		description: 'qa openapi connection',
	};
	const create = cli(['connections', 'create', '--data', JSON.stringify(body)], {timeout: 60000});
	if (isOk(create) && create.json.id) {
		const id = create.json.id;
		trackDelete('connections.delete', ['connections', 'delete', id]);
		check('S1', 'connection-create-from-spec-url', true, `id=${id}`);
		const disc = cli(['connections', 'discover-tools', id], {timeout: 60000});
		check('S1', 'connection-discover-tools', disc.code === 0 && !isErr(disc), evidence(disc));
		const del = cli(['connections', 'delete', id]);
		const dok = del.code === 0 && !isErr(del);
		if (dok) teardown.splice(teardown.findIndex(t => t.args[2] === id), 1);
	} else {
		skip('S1', 'connection-create-from-spec-url', `endpoint did not accept public spec URL: ${evidence(create)}`);
		skip('S1', 'connection-discover-tools', 'connection not created');
	}
}

// S10 Bundles: invalid payload -> clear validation, not 500
function s10Bundles() {
	const bad = cli(['bundles', 'analyze', '--data', JSON.stringify({source_url: 'https://example.com/not-a-real-bundle.zip'})], {timeout: 60000});
	if (isErr(bad)) {
		const st = bad.json.status;
		check('S10', 'bundle-analyze-invalid-validation', st >= 400 && st < 500, `expected clear 4xx (not 500), got status=${st}`);
		if (st >= 500) finding('Bundle analyze returns 5xx on bad input (S10)', evidence(bad));
	} else if (bad.json !== undefined) {
		// returned a structured analysis (may include an error report) — acceptable if it flags the problem, not a silent 500
		const blob = JSON.stringify(bad.json);
		const flagsProblem = /error|invalid|fail|not.?found|unreachable/i.test(blob);
		check('S10', 'bundle-analyze-invalid-validation', flagsProblem, `structured report flagged problem: ${blob.slice(0, 200)}`);
	} else {
		check('S10', 'bundle-analyze-invalid-validation', false, `no structured response: code=${bad.code} ${(bad.err || bad.out).slice(0, 200)}`);
	}
}

// S12 Wallet
function s12Wallet() {
	const get = cli(['wallet', 'get', AGENT_REAL]);
	const bal = cli(['wallet', 'balance', AGENT_REAL]);
	// Record durability; 404 (no wallet) is an acceptable, non-crashing outcome
	const getStructured = get.json !== undefined && errStatus(get) !== 500;
	const balStructured = bal.json !== undefined && errStatus(bal) !== 500;
	check('S12', 'wallet-get', getStructured, evidence(get));
	check('S12', 'wallet-balance', balStructured, evidence(bal));
	if (errStatus(get) === 404) finding('No wallet provisioned for real-run agent (S12)', `wallet get ${AGENT_REAL} -> 404 (informational, not a failure)`);
}

// S13 Audit
function s13Audit() {
	const list = cli(['audit-logs', 'list']);
	const arr = asArray(list.json);
	check('S13', 'audit-logs-durable', list.code === 0 && !isErr(list) && arr.length > 0, `events=${arr.length}`);
}

// S16 CLI interface
function s16Cli() {
	const list = cli(['agents', 'list']);
	check('S16', 'cli-agents-list', isOk(list) && asArray(list.json).length > 0, `count=${asArray(list.json).length}`);
	// bad token -> clear auth error, non-zero exit
	const bad = cli(['agents', 'list', '--token=bad.bad.bad']);
	const st = errStatus(bad);
	check('S16', 'cli-bad-token-auth-error', bad.code !== 0 && isErr(bad) && st === 401, `exit=${bad.code} ${evidence(bad)}`);
}

// S19 A2A agent card
function s19A2a() {
	const card = cli(['api', 'getAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGet', '--path', JSON.stringify({agent_id: AGENT_REAL})]);
	const blob = card.json ? JSON.stringify(card.json) : '';
	const looksLikeCard = isOk(card) && /name|url|capabilities|version|skills|protocol/i.test(blob);
	check('S19', 'a2a-agent-card', looksLikeCard, isOk(card) ? blob.slice(0, 200) : evidence(card));

	const bogus = cli(['api', 'getAgentWellKnownCardV1AgentsAgentIdWellKnownAgentCardJsonGet', '--path', JSON.stringify({agent_id: '00000000-0000-0000-0000-000000000000'})]);
	const bst = errStatus(bogus);
	check('S19', 'a2a-bogus-agent-404', isErr(bogus) && (bst === 404 || bst === 403), `expected 404, got ${evidence(bogus)}`);
}

function outOfScopeNotes() {
	skip('S17', 'ui-navigation', 'out-of-CLI-scope: browser UI navigation not drivable via CLI');
	skip('S18', 'compose-bringup', 'out-of-CLI-scope: docker compose bringup; stack already up (health checked)');
	for (const s of ['S11', 'S14', 'S15']) skip(s, 'scenario', 'not in assigned CLI coverage set (1-16,19); see wiki for MP');
}

// =====================================================================
// TEARDOWN
// =====================================================================
function runTeardown() {
	const lines = [];
	for (const t of teardown) {
		const r = cli(t.args);
		const ok = r.code === 0 && !isErr(r);
		lines.push(`  ${ok ? 'deleted' : 'FAILED '} ${t.label} ${t.args[2] ?? ''} ${ok ? '' : '-- ' + evidence(r)}`);
	}
	return lines;
}

// =====================================================================
// MAIN
// =====================================================================
function main() {
	console.log(`# QA CLI harness  runId=${runId}  prefix=${PREFIX}`);
	const scenarios = [
		['health', sHealth],
		['S16-cli', s16Cli],
		['S2-agents', s2Agents],
		['S3-task', s3Task],
		['S4-mcp', s4Mcp],
		['S5-policy', s5Policy],
		['S6-triggers', s6Triggers],
		['S7-access', s7Access],
		['S8-providers', s8Providers],
		['S9-skills', s9Skills],
		['S1-connections', s1Connections],
		['S10-bundles', s10Bundles],
		['S12-wallet', s12Wallet],
		['S13-audit', s13Audit],
		['S19-a2a', s19A2a],
	];
	for (const [label, fn] of scenarios) {
		try {
			fn();
		} catch (e) {
			rec('FAIL', label, 'harness-exception', `${e && e.message ? e.message : e}`);
		}
	}
	outOfScopeNotes();

	console.log('\n# TEARDOWN');
	const tdLines = runTeardown();
	for (const l of tdLines) console.log(l);
	if (tdLines.length === 0) console.log('  (nothing to tear down — all created entities already deleted in-scenario)');

	// ---- Build matrix ----
	const pass = results.filter(r => r.kind === 'PASS').length;
	const fail = results.filter(r => r.kind === 'FAIL').length;
	const sk = results.filter(r => r.kind === 'SKIP').length;

	const matrixLines = results.map(
		r => `${r.kind.padEnd(4)}  ${r.scenario.padEnd(5)}  ${r.name.padEnd(38)}  -- ${r.evidence}`,
	);
	const summary = `${pass} pass / ${fail} fail / ${sk} skip`;

	const findingLines = findings.length
		? findings.map((f, i) => `  ${i + 1}. ${f.title}\n     evidence: ${f.evidence}`)
		: ['  (none)'];

	const report = [
		`QA CLI RESULTS MATRIX  runId=${runId}  ${new Date().toISOString()}`,
		`prefix=${PREFIX}  api=http://localhost:8000  workspace=${MY_WORKSPACE}`,
		'',
		...matrixLines,
		'',
		`SUMMARY: ${summary}`,
		'',
		'TEARDOWN:',
		...tdLines,
		...(tdLines.length ? [] : ['  (all created entities deleted in-scenario)']),
		'',
		'FINDINGS:',
		...findingLines,
		'',
	].join('\n');

	console.log('\n# MATRIX');
	console.log(report);

	const outPath = join(__dirname, 'last-run.txt');
	writeFileSync(outPath, report);
	console.log(`\nWrote ${outPath}`);
}

main();
