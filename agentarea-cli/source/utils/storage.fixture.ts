import {type KeyringStore, TokenStorage} from './storage.js';

/** A TokenStorage over an in-memory keychain, for tests. */
export function memoryTokenStorage(seed: Record<string, string> = {}) {
	const entries = new Map(Object.entries(seed));
	const keyring: KeyringStore = {
		async getPassword(_service, account) {
			return entries.get(account) ?? null;
		},
		async setPassword(_service, account, password) {
			entries.set(account, password);
		},
		async deletePassword(_service, account) {
			return entries.delete(account);
		},
		async findCredentials() {
			return [...entries].map(([account, password]) => ({account, password}));
		},
	};
	return {entries, storage: new TokenStorage(async () => keyring)};
}
