import axios, {
	type AxiosInstance,
	type AxiosError,
	type InternalAxiosRequestConfig,
} from 'axios';
import {configManager} from '../utils/config.js';
import {logger} from '../utils/logger.js';
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

		// Expired tokens are refreshed before a client is built (loadAccessToken,
		// via the OAuth token endpoint); a 401 here means re-authentication.
		this.client.interceptors.response.use(
			response => response,
			async (error: AxiosError) => {
				const originalConfig: RetriableRequestConfig | undefined = error.config;

				if (
					error.response?.status === 401 &&
					originalConfig &&
					!originalConfig._retry &&
					this.on401Callback
				) {
					originalConfig._retry = true;
					await this.on401Callback(error);
					return this.client(originalConfig);
				}

				return Promise.reject(error);
			},
		);
	}

	setToken(token: AuthToken): void {
		this.currentToken = token;
		logger.debug('API client token updated');
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
