import {logger} from './logger.js';
import {StorageError} from './error.js';
import {type AuthToken} from '../types/index.js';

const SERVICE_NAME = 'agentarea-cli';
const TOKEN_KEY = 'auth_token';

// Load the native OS keychain addon lazily on first token operation rather than
// at module import. The dependency is still required — a broken load throws
// here as it always would — but merely importing this module (e.g. from a
// unit test or a headless environment) no longer forces the native binding.
type Keyring = typeof import('@zowe/secrets-for-zowe-sdk')['keyring'];
let keyringPromise: Promise<Keyring> | undefined;
async function getKeyring(): Promise<Keyring> {
	keyringPromise ??= import('@zowe/secrets-for-zowe-sdk').then(m => m.keyring);
	return keyringPromise;
}

export class TokenStorage {
	async saveToken(token: AuthToken): Promise<void> {
		try {
			const tokenString = JSON.stringify(token);
			const keyring = await getKeyring();
			await keyring.setPassword(SERVICE_NAME, TOKEN_KEY, tokenString);
			logger.debug('Token saved to keychain');
		} catch (error) {
			logger.error('Failed to save token:', error);
			throw new StorageError(`Failed to save authentication token: ${error}`);
		}
	}

	async getToken(): Promise<AuthToken | null> {
		try {
			const keyring = await getKeyring();
			const tokenString = await keyring.getPassword(SERVICE_NAME, TOKEN_KEY);

			if (!tokenString) {
				logger.debug('No stored token found');
				return null;
			}

			const token: AuthToken = JSON.parse(tokenString);
			logger.debug('Token retrieved from keychain');
			return token;
		} catch (error) {
			logger.error('Failed to retrieve token:', error);
			throw new StorageError(
				`Failed to retrieve authentication token: ${error}`,
			);
		}
	}

	async clearToken(): Promise<void> {
		try {
			const keyring = await getKeyring();
			await keyring.deletePassword(SERVICE_NAME, TOKEN_KEY);
			logger.debug('Token cleared from keychain');
		} catch (error) {
			logger.error('Failed to clear token:', error);
			throw new StorageError(`Failed to clear authentication token: ${error}`);
		}
	}

	async hasToken(): Promise<boolean> {
		try {
			const token = await this.getToken();
			return token !== null;
		} catch (error) {
			logger.error('Failed to check token:', error);
			return false;
		}
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
