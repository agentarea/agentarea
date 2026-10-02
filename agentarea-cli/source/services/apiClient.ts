import axios, {
	type AxiosInstance,
	type AxiosError,
	type InternalAxiosRequestConfig,
} from 'axios';
import {tokenStorage} from '../utils/storage.js';
import {configManager} from '../utils/config.js';
import {logger} from '../utils/logger.js';
import {AuthenticationError} from '../utils/error.js';
import {type AuthToken} from '../types/index.js';

// Marks a request already replayed after a 401 so it is never retried twice.
type RetriableRequestConfig = InternalAxiosRequestConfig & {_retry?: boolean};

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
				const originalConfig: RetriableRequestConfig | undefined = error.config;

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

	setToken(token: AuthToken): void {
		this.currentToken = token;
		logger.debug('API client token updated');
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
