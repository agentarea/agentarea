import axios, {type AxiosInstance, type AxiosError} from 'axios';
import {tokenStorage} from '../utils/storage.js';
import {configManager} from '../utils/config.js';
import {logger} from '../utils/logger.js';
import {NetworkError, AuthenticationError} from '../utils/error.js';
import {type AuthToken} from '../types/index.js';

class ApiClient {
	private client: AxiosInstance;
	private currentToken: AuthToken | null = null;
	private on401Callback: ((error: AxiosError) => Promise<void>) | null = null;

	constructor() {
		const config = configManager.get();

		this.client = axios.create({
			baseURL: config.apiBaseUrl,
			timeout: config.apiTimeout,
			headers: {
				'Content-Type': 'application/json',
			},
		});

		this.setupInterceptors();
	}

	private setupInterceptors() {
		// Add request interceptor to include auth token
		this.client.interceptors.request.use(
			config => {
				if (this.currentToken) {
					config.headers.Authorization = `${this.currentToken.tokenType} ${this.currentToken.accessToken}`;
				}

				return config;
			},
			error => {
				return Promise.reject(error);
			},
		);

		// Add response interceptor to handle token refresh and 401 errors
		this.client.interceptors.response.use(
			response => response,
			async (error: AxiosError) => {
				const originalConfig = error.config as any;

				// Handle 401 Unauthorized
				if (
					error.response?.status === 401 &&
					originalConfig &&
					!originalConfig._retry
				) {
					originalConfig._retry = true;

					try {
						if (this.currentToken?.refreshToken) {
							// Try to refresh token if available
							const newToken = await this.refreshToken();
							this.currentToken = newToken;
							await tokenStorage.saveToken(newToken);

							// Retry the original request with new token
							return this.client(originalConfig);
						} else {
							// No refresh token available, invoke callback if set
							if (this.on401Callback) {
								await this.on401Callback(error);
								// After callback, retry the request with potentially updated token
								return this.client(originalConfig);
							}
						}
					} catch (refreshError) {
						logger.error('Token refresh failed:', refreshError);
						// Token refresh failed, user needs to re-authenticate
						await tokenStorage.clearToken();
						this.currentToken = null;
						throw new AuthenticationError(
							'Session expired. Please login again.',
						);
					}
				}

				return Promise.reject(error);
			},
		);
	}

	async initialize(): Promise<void> {
		try {
			// Load stored token if available
			const storedToken = await tokenStorage.getToken();

			if (storedToken) {
				// Check if token needs refresh
				if (tokenStorage.shouldRefreshToken(storedToken)) {
					logger.debug('Refreshing stored token');
					const newToken = await this.refreshToken();
					this.currentToken = newToken;
					await tokenStorage.saveToken(newToken);
				} else {
					this.currentToken = storedToken;
				}

				logger.debug('API client initialized with stored token');
			} else {
				logger.debug(
					'No stored token found, API client initialized without auth',
				);
			}
		} catch (error) {
			logger.error('Failed to initialize API client:', error);
			throw new NetworkError(`Failed to initialize API client: ${error}`);
		}
	}

	setToken(token: AuthToken): void {
		this.currentToken = token;
		logger.debug('API client token updated');
	}

	async login(email: string, password: string): Promise<AuthToken> {
		try {
			const config = configManager.get();

			// Use Kratos for authentication via self-service API
			// 1. Create a login flow
			const flowResponse = await axios.get(
				`${config.kratosUrl}/self-service/login/api`,
				{
					withCredentials: true,
					headers: {
						Accept: 'application/json',
					},
				},
			);

			const flowId = (flowResponse.data as any).id;

			if (!flowId) {
				throw new AuthenticationError('Failed to create login flow');
			}

			logger.debug(`Created login flow: ${flowId}`);

			// 2. Submit login credentials to Kratos
			const submitResponse = await axios.post(
				`${config.kratosUrl}/self-service/login?flow=${flowId}`,
				{
					csrf_token: this.extractCsrfToken(flowResponse.data),
					method: 'password',
					password,
					identifier: email,
				},
				{
					withCredentials: true,
					validateStatus: () => true,
				},
			);

			// Check if login was successful (Kratos redirects on success)
			if (submitResponse.status >= 400) {
				throw new AuthenticationError('Invalid email or password');
			}

			// Extract session token from cookies (Kratos sets ory_kratos_session)
			const sessionToken = this.extractSessionToken(submitResponse.headers);

			if (!sessionToken) {
				throw new AuthenticationError('Failed to obtain session token');
			}

			const token: AuthToken = {
				accessToken: sessionToken,
				tokenType: 'Bearer',
				expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000), // 24h default
			};

			this.currentToken = token;
			logger.info('Successfully logged in');
			return token;
		} catch (error) {
			logger.error('Login failed:', error);

			if (error instanceof AuthenticationError) {
				throw error;
			}

			throw new NetworkError(`Login failed: ${error}`);
		}
	}

	async refreshToken(): Promise<AuthToken> {
		try {
			if (!this.currentToken?.refreshToken) {
				throw new AuthenticationError('No refresh token available');
			}

			const response = await this.client.post<{
				accessToken: string;
				expiresIn?: number;
			}>('/auth/refresh', {
				refreshToken: this.currentToken.refreshToken,
			});

			const token: AuthToken = {
				accessToken: response.data.accessToken,
				refreshToken: this.currentToken.refreshToken,
				tokenType: 'Bearer',
				expiresAt: response.data.expiresIn
					? new Date(Date.now() + response.data.expiresIn * 1000)
					: undefined,
			};

			logger.debug('Token refreshed successfully');
			return token;
		} catch (error) {
			logger.error('Token refresh failed:', error);
			throw new AuthenticationError(`Token refresh failed: ${error}`);
		}
	}

	async logout(): Promise<void> {
		try {
			const config = configManager.get();

			// Logout from Kratos
			await axios.get(`${config.kratosUrl}/self-service/logout/browser`, {
				withCredentials: true,
			});

			this.currentToken = null;
			logger.info('Successfully logged out');
		} catch (error) {
			logger.warn(
				'Logout failed (may be expected if session already expired):',
				error,
			);
			// Clear token anyway
			this.currentToken = null;
		}
	}

	private extractCsrfToken(html: string): string {
		// Extract CSRF token from Kratos login form HTML
		const match = html.match(/name="csrf_token"\s+value="([^"]+)"/);
		return match ? match[1] : '';
	}

	private extractSessionToken(headers: Record<string, any>): string | null {
		// Extract session token from Set-Cookie header
		const setCookie = headers['set-cookie'];
		if (Array.isArray(setCookie)) {
			for (const cookie of setCookie) {
				if (cookie.includes('ory_kratos_session')) {
					const match = cookie.match(/ory_kratos_session=([^;]+)/);
					if (match) {
						return match[1];
					}
				}
			}
		}
		return null;
	}

	set401Callback(callback: (error: AxiosError) => Promise<void>): void {
		this.on401Callback = callback;
	}

	reinitialize(): void {
		const config = configManager.get();

		this.client = axios.create({
			baseURL: config.apiBaseUrl,
			timeout: config.apiTimeout,
			headers: {
				'Content-Type': 'application/json',
			},
		});

		this.setupInterceptors();

		logger.debug('API client reinitialized');
	}

	getClient(): AxiosInstance {
		return this.client;
	}

	getToken(): AuthToken | null {
		return this.currentToken;
	}

	hasToken(): boolean {
		return this.currentToken !== null;
	}

	clearToken(): void {
		this.currentToken = null;
		logger.debug('API client token cleared');
	}
}

// Export a singleton instance
export const apiClient = new ApiClient();

// Make axios error checking available
export {axios};
