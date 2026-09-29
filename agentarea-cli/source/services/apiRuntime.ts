import {configureApiClient} from '@agentarea/api-client';
import {configManager} from '../utils/config.js';
import {tokenStorage} from '../utils/storage.js';
import {apiClient} from './apiClient.js';
import {logger} from '../utils/logger.js';
import {ConfigError} from '../utils/error.js';

let overrideToken: string | undefined;
let overrideWorkspace: string | undefined;

export function setRuntimeToken(token: string | undefined): void {
	overrideToken = token;
}

export async function resolveToken(): Promise<string | undefined> {
	if (overrideToken) {
		return overrideToken;
	}

	const inMemory = apiClient.getToken()?.accessToken;
	if (inMemory) {
		return inMemory;
	}

	try {
		const stored = await tokenStorage.getToken();
		return stored?.accessToken;
	} catch {
		return undefined;
	}
}

export function setRuntimeWorkspace(slug: string | undefined): void {
	overrideWorkspace = slug;
}

/**
 * The workspace a workspace-scoped call runs in: `--workspace` wins over the
 * saved `workspace` config value. There is no default.
 */
export function requireWorkspace(): string {
	const slug = overrideWorkspace ?? configManager.get().workspace;
	if (!slug) {
		throw new ConfigError(
			'This command runs inside a workspace. Pass --workspace <slug>, or save one with `agentarea workspace use <slug>`.',
		);
	}

	return slug;
}

export function getApiBaseUrl(): string {
	return configManager.get().apiBaseUrl;
}

export function initApiClient(): void {
	configureApiClient({
		baseUrl: getApiBaseUrl(),
		token: () => resolveToken(),
		fetch: globalThis.fetch,
		workspace: requireWorkspace,
	});
	logger.debug('Shared API client configured');
}
