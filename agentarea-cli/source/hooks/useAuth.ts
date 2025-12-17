import {useState, useEffect, useCallback} from 'react';
import {authService} from '../services/auth.js';
import {apiClient} from '../services/apiClient.js';
import {tokenStorage} from '../utils/storage.js';
import {logger} from '../utils/logger.js';
import {type AuthToken, type User} from '../types/index.js';

export interface AuthState {
	isAuthenticated: boolean;
	isLoading: boolean;
	error: string | null;
	user: User | null;
	token: AuthToken | null;
}

export function useAuth() {
	const [state, setState] = useState<AuthState>({
		isAuthenticated: false,
		isLoading: true,
		error: null,
		user: null,
		token: null,
	});

	// Initialize auth on mount
	useEffect(() => {
		const initialize = async () => {
			try {
				await authService.initialize();
				const isAuthenticated = await authService.isAuthenticated();
				const token = await authService.getToken();

				setState(prev => ({
					...prev,
					isAuthenticated,
					isLoading: false,
					token,
				}));

				logger.debug('Auth hook initialized');
			} catch (error) {
				logger.error('Auth initialization failed:', error);
				setState(prev => ({
					...prev,
					isLoading: false,
					error: 'Failed to initialize authentication',
				}));
			}
		};

		initialize();
	}, []);

	const login = useCallback(async (email: string, password: string) => {
		setState(prev => ({...prev, isLoading: true, error: null}));

		try {
			const {token, user} = await authService.login(email, password);

			setState(prev => ({
				...prev,
				isAuthenticated: true,
				isLoading: false,
				user,
				token,
				error: null,
			}));

			logger.info('User logged in successfully');
			return {success: true, user, token};
		} catch (error) {
			const errorMessage =
				error instanceof Error ? error.message : 'Login failed';

			setState(prev => ({
				...prev,
				isLoading: false,
				error: errorMessage,
			}));

			logger.error('Login error:', errorMessage);
			return {success: false, error: errorMessage};
		}
	}, []);

	const logout = useCallback(async () => {
		setState(prev => ({...prev, isLoading: true, error: null}));

		try {
			await authService.logout();

			setState(prev => ({
				...prev,
				isAuthenticated: false,
				isLoading: false,
				user: null,
				token: null,
				error: null,
			}));

			logger.info('User logged out successfully');
			return {success: true};
		} catch (error) {
			const errorMessage =
				error instanceof Error ? error.message : 'Logout failed';

			setState(prev => ({
				...prev,
				isLoading: false,
				error: errorMessage,
			}));

			logger.error('Logout error:', errorMessage);
			return {success: false, error: errorMessage};
		}
	}, []);

	const refreshToken = useCallback(async () => {
		try {
			const token = await authService.refreshToken();

			setState(prev => ({
				...prev,
				token,
				error: null,
			}));

			logger.debug('Token refreshed successfully');
			return {success: true, token};
		} catch (error) {
			const errorMessage =
				error instanceof Error ? error.message : 'Token refresh failed';

			setState(prev => ({
				...prev,
				error: errorMessage,
			}));

			logger.error('Token refresh error:', errorMessage);
			return {success: false, error: errorMessage};
		}
	}, []);

	const clearError = useCallback(() => {
		setState(prev => ({...prev, error: null}));
	}, []);

	const setToken = useCallback((jwtToken: string) => {
		try {
			// Create an AuthToken from the JWT string
			const token: AuthToken = {
				accessToken: jwtToken,
				tokenType: 'Bearer',
				// Decode JWT to get expiration
				expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000), // Default 24h
			};

			// Set in API client
			apiClient.setToken(token);

			// Extract user from JWT payload if possible
			const parts = jwtToken.split('.');
			if (parts.length === 3) {
				try {
					const decoded = JSON.parse(Buffer.from(parts[1], 'base64').toString());
					const user: User = {
						id: decoded.sub || decoded.user_id || 'unknown',
						email: decoded.email || 'unknown',
						createdAt: new Date(),
					};

					setState(prev => ({
						...prev,
						isAuthenticated: true,
						token,
						user,
						error: null,
					}));

					// Save to storage
					tokenStorage.saveToken(token).catch(err =>
						logger.warn('Failed to save token to storage:', err),
					);
				} catch (decodeError) {
					logger.warn('Could not decode JWT payload:', decodeError);
					setState(prev => ({
						...prev,
						isAuthenticated: true,
						token,
					}));
				}
			}

			logger.info('Token set successfully');
		} catch (error) {
			logger.error('Failed to set token:', error);
			setState(prev => ({
				...prev,
				error: error instanceof Error ? error.message : 'Failed to set token',
			}));
		}
	}, []);

	return {
		...state,
		login,
		logout,
		refreshToken,
		clearError,
		setToken,
	};
}
