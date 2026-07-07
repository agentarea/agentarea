import {configureApiClient} from '@agentarea/api-client';
import {configManager} from '../utils/config.js';
import {tokenStorage} from '../utils/storage.js';
import {apiClient} from './apiClient.js';
import {logger} from '../utils/logger.js';

let overrideToken: string | undefined;

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

export function getApiBaseUrl(): string {
	return configManager.get().apiBaseUrl;
}

export function initApiClient(): void {
	configureApiClient({
		baseUrl: getApiBaseUrl(),
		token: () => resolveToken(),
		fetch: globalThis.fetch,
	});
	logger.debug('Shared API client configured');
}
