import {apiClient} from './apiClient.js';
import {tokenStorage} from '../utils/storage.js';
import {logger} from '../utils/logger.js';
import {AuthenticationError} from '../utils/error.js';
import {type AuthToken, type User} from '../types/index.js';

export class AuthService {
	private currentUser: User | null = null;

	async initialize(): Promise<void> {
		try {
			await apiClient.initialize();

			// Try to load stored token
			const token = await tokenStorage.getToken();
			if (token) {
				apiClient.setToken(token);
				logger.debug('Auth service initialized with stored token');
			}
		} catch (error) {
			logger.error('Failed to initialize auth service:', error);
		}
	}

	async login(
		email: string,
		password: string,
	): Promise<{token: AuthToken; user: User}> {
		try {
			// Validate input
			if (!email || !password) {
				throw new AuthenticationError('Email and password are required');
			}

			if (!this.isValidEmail(email)) {
				throw new AuthenticationError('Invalid email format');
			}

			// Login via API
			const token = await apiClient.login(email, password);

			// Store token
			await tokenStorage.saveToken(token);

			// Extract user info from token (normally would be in response, but for now using email)
			const user: User = {
				id: this.extractIdFromToken(token.accessToken),
				email,
				createdAt: new Date(),
				lastLoginAt: new Date(),
			};

			this.currentUser = user;

			logger.info(`User logged in: ${email}`);
			return {token, user};
		} catch (error) {
			logger.error('Login failed:', error);
			throw error;
		}
	}

	async logout(): Promise<void> {
		try {
			await apiClient.logout();
			await tokenStorage.clearToken();
			this.currentUser = null;
			logger.info('User logged out');
		} catch (error) {
			logger.error('Logout failed:', error);
			// Still clear local state even if API call fails
			await tokenStorage.clearToken();
			this.currentUser = null;
			throw error;
		}
	}

	async refreshToken(): Promise<AuthToken> {
		try {
			const newToken = await apiClient.refreshToken();
			await tokenStorage.saveToken(newToken);
			logger.debug('Token refreshed successfully');
			return newToken;
		} catch (error) {
			logger.error('Token refresh failed:', error);
			throw error;
		}
	}

	async isAuthenticated(): Promise<boolean> {
		try {
			const token = await tokenStorage.getToken();
			if (!token) {
				return false;
			}

			if (tokenStorage.isTokenExpired(token)) {
				// Try to refresh
				try {
					await this.refreshToken();
					return true;
				} catch {
					return false;
				}
			}

			return true;
		} catch (error) {
			logger.error('Error checking authentication:', error);
			return false;
		}
	}

	async getToken(): Promise<AuthToken | null> {
		try {
			return await tokenStorage.getToken();
		} catch (error) {
			logger.error('Error getting token:', error);
			return null;
		}
	}

	getCurrentUser(): User | null {
		return this.currentUser;
	}

	setCurrentUser(user: User): void {
		this.currentUser = user;
	}

	clearCurrentUser(): void {
		this.currentUser = null;
	}

	private isValidEmail(email: string): boolean {
		const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
		return emailRegex.test(email);
	}

	private extractIdFromToken(token: string): string {
		// In a real scenario, you would decode the JWT and extract the user ID
		// For now, we'll use a placeholder
		try {
			const parts = token.split('.');
			if (parts.length === 3) {
				const decoded = JSON.parse(Buffer.from(parts[1], 'base64').toString());
				return decoded.sub || decoded.id || 'unknown';
			}
		} catch (error) {
			logger.debug('Could not decode token payload');
		}

		return 'unknown';
	}
}

// Export a singleton instance
export const authService = new AuthService();
