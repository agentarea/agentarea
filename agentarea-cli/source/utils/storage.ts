import {logger} from './logger.js';
import {StorageError} from './error.js';
import {type AuthToken} from '../types/index.js';
import {apiOrigin} from './apiUrl.js';

const SERVICE_NAME = 'agentarea-cli';
// Before sign-ins were kept per host, the one sign-in lived under this account.
const LEGACY_TOKEN_KEY = 'auth_token';

// Load the native OS keychain addon lazily on first token operation rather than
// at module import. The dependency is still required — a broken load throws
// here as it always would — but merely importing this module (e.g. from a
// unit test or a headless environment) no longer forces the native binding.
type Keyring = typeof import('@zowe/secrets-for-zowe-sdk')['keyring'];
export type KeyringStore = Pick<
	Keyring,
	'getPassword' | 'setPassword' | 'deletePassword' | 'findCredentials'
>;
let keyringPromise: Promise<Keyring> | undefined;
async function getKeyring(): Promise<Keyring> {
	keyringPromise ??= import('@zowe/secrets-for-zowe-sdk').then(m => m.keyring);
	return keyringPromise;
}

/**
 * The keychain account a sign-in lives under: the origin of the API it was
 * issued for, so each host keeps its own and signing in to one never replaces
 * another's.
 */
function accountFor(apiUrl: string | undefined): string {
	const origin = apiOrigin(apiUrl);
	if (!origin) {
		throw new StorageError(
			`A sign-in must belong to an http(s) API, got ${apiUrl ?? 'none'}`,
		);
	}

	return origin;
}

function legacyTokenOrigin(legacy: string): string | null {
	try {
		return apiOrigin((JSON.parse(legacy) as AuthToken).apiUrl);
	} catch (error) {
		logger.warn('The stored sign-in is not readable:', error);
		return null;
	}
}

export class TokenStorage {
	private migration: Promise<void> | undefined;
	private warnedUnboundLegacy = false;

	private readonly keyring: () => Promise<KeyringStore>;

	constructor(keyring: () => Promise<KeyringStore> = getKeyring) {
		this.keyring = keyring;
	}

	async saveToken(token: AuthToken): Promise<void> {
		const account = accountFor(token.apiUrl);
		try {
			await this.migrateLegacyToken();
			const keyring = await this.keyring();
			await keyring.setPassword(SERVICE_NAME, account, JSON.stringify(token));
			// Whatever is still under the legacy account has no recorded host and
			// was never sent; this sign-in is what its warning asked for.
			await keyring.deletePassword(SERVICE_NAME, LEGACY_TOKEN_KEY);
			logger.debug(`Token for ${account} saved to keychain`);
		} catch (error) {
			logger.error('Failed to save token:', error);
			throw new StorageError(`Failed to save authentication token: ${error}`);
		}
	}

	/** The sign-in stored for *apiUrl*'s origin, or null when there is none. */
	async getTokenFor(apiUrl: string): Promise<AuthToken | null> {
		const account = accountFor(apiUrl);
		try {
			await this.migrateLegacyToken();
			const keyring = await this.keyring();
			const tokenString = await keyring.getPassword(SERVICE_NAME, account);
			if (!tokenString) {
				logger.debug(`No stored token for ${account}`);
				return null;
			}

			const token = JSON.parse(tokenString) as AuthToken;
			if (apiOrigin(token.apiUrl) !== account) {
				logger.warn(
					`Not sending the sign-in stored for ${account}: it records ${
						token.apiUrl ?? 'no API'
					}. Run \`agentarea login --api-url=${account}\` to sign in again.`,
				);
				return null;
			}

			return token;
		} catch (error) {
			logger.error('Failed to retrieve token:', error);
			throw new StorageError(
				`Failed to retrieve authentication token: ${error}`,
			);
		}
	}

	/**
	 * Sign out of *apiUrl*'s origin; other hosts keep their sign-ins. False when
	 * there was no sign-in for it.
	 */
	async clearToken(apiUrl: string): Promise<boolean> {
		const account = accountFor(apiUrl);
		try {
			await this.migrateLegacyToken();
			const keyring = await this.keyring();
			const cleared = await keyring.deletePassword(SERVICE_NAME, account);
			logger.debug(`Token for ${account} cleared from keychain: ${cleared}`);
			return cleared;
		} catch (error) {
			logger.error('Failed to clear token:', error);
			throw new StorageError(`Failed to clear authentication token: ${error}`);
		}
	}

	/** Sign out of every host; returns the accounts that were cleared. */
	async clearAllTokens(): Promise<string[]> {
		try {
			const keyring = await this.keyring();
			const accounts = (await keyring.findCredentials(SERVICE_NAME)).map(
				credential => credential.account,
			);
			for (const account of accounts) {
				await keyring.deletePassword(SERVICE_NAME, account);
			}

			logger.debug(`Cleared ${accounts.length} token(s) from keychain`);
			return accounts;
		} catch (error) {
			logger.error('Failed to clear tokens:', error);
			throw new StorageError(`Failed to clear authentication tokens: ${error}`);
		}
	}

	private async migrateLegacyToken(): Promise<void> {
		this.migration ??= this.moveLegacyToken().catch((error: unknown) => {
			this.migration = undefined;
			throw error;
		});
		return this.migration;
	}

	/**
	 * Move the single pre-per-host sign-in to its host's account. One that is
	 * unreadable or records no host is left where it is and never sent: nothing
	 * says which API issued it. The next sign-in removes it.
	 */
	private async moveLegacyToken(): Promise<void> {
		const keyring = await this.keyring();
		const legacy = await keyring.getPassword(SERVICE_NAME, LEGACY_TOKEN_KEY);
		if (!legacy) {
			return;
		}

		const origin = legacyTokenOrigin(legacy);
		if (!origin) {
			if (!this.warnedUnboundLegacy) {
				this.warnedUnboundLegacy = true;
				logger.warn(
					'Ignoring the stored sign-in: it does not record which API issued it. Run `agentarea login --api-url=<api>` to sign in again.',
				);
			}

			return;
		}

		// Read last, so a sign-in another process saved meanwhile is kept.
		if (!(await keyring.getPassword(SERVICE_NAME, origin))) {
			await keyring.setPassword(SERVICE_NAME, origin, legacy);
		}

		await keyring.deletePassword(SERVICE_NAME, LEGACY_TOKEN_KEY);
		logger.debug(`Moved the stored sign-in to ${origin}`);
	}

	isTokenExpired(token: AuthToken): boolean {
		if (!token.expiresAt) {
			return false;
		}

		const expirationTime = new Date(token.expiresAt).getTime();
		const currentTime = new Date().getTime();
		const timeUntilExpiration = expirationTime - currentTime;

		// Consider token expired if less than 5 minutes remaining
		return timeUntilExpiration < 5 * 60 * 1000;
	}

	shouldRefreshToken(token: AuthToken): boolean {
		if (!token.refreshToken) {
			return false;
		}

		return this.isTokenExpired(token);
	}
}

// Export a singleton instance
export const tokenStorage = new TokenStorage();
