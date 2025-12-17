import process from 'process';
import path from 'path';
import {fileURLToPath} from 'url';
import Conf from 'conf';
import {type CLIConfig} from '../types/index.js';
import {logger} from './logger.js';
import {ConfigError} from './error.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Default configuration values
const defaultConfig: CLIConfig = {
	kratosUrl: process.env['KRATOS_URL'] || 'http://localhost:4433',
	apiBaseUrl: process.env['API_URL'] || 'http://localhost:8000',
	apiTimeout: Number(process.env['API_TIMEOUT']) || 30000,
	maxRetries: Number(process.env['MAX_RETRIES']) || 3,
	retryDelay: Number(process.env['RETRY_DELAY']) || 1000,
	streamTimeout: Number(process.env['STREAM_TIMEOUT']) || 60000,
	logLevel: (process.env['LOG_LEVEL'] as CLIConfig['logLevel']) || 'info',
	theme: (process.env['THEME'] as CLIConfig['theme']) || 'auto',
};

// Create persistent config store
const configStore = new Conf<CLIConfig>({
	projectName: 'agentarea-cli',
	defaults: defaultConfig,
});

export class ConfigManager {
	private config: CLIConfig;

	constructor() {
		this.config = {...defaultConfig};
		this.loadConfig();
	}

	private loadConfig(): void {
		try {
			// Load from environment variables (highest priority)
			const envConfig: Partial<CLIConfig> = {};

			if (process.env['KRATOS_URL']) {
				envConfig.kratosUrl = process.env['KRATOS_URL'];
			}

			if (process.env['API_URL']) {
				envConfig.apiBaseUrl = process.env['API_URL'];
			}

			if (process.env['API_TIMEOUT']) {
				envConfig.apiTimeout = Number(process.env['API_TIMEOUT']);
			}

			if (process.env['MAX_RETRIES']) {
				envConfig.maxRetries = Number(process.env['MAX_RETRIES']);
			}

			if (process.env['RETRY_DELAY']) {
				envConfig.retryDelay = Number(process.env['RETRY_DELAY']);
			}

			if (process.env['STREAM_TIMEOUT']) {
				envConfig.streamTimeout = Number(process.env['STREAM_TIMEOUT']);
			}

			if (process.env['LOG_LEVEL']) {
				envConfig.logLevel = process.env['LOG_LEVEL'] as CLIConfig['logLevel'];
			}

			if (process.env['THEME']) {
				envConfig.theme = process.env['THEME'] as CLIConfig['theme'];
			}

			// Merge with persistent config
			this.config = {
				...configStore.store,
				...envConfig,
			};

			logger.debug('Configuration loaded', this.config);
		} catch (error) {
			logger.error('Failed to load configuration:', error);
			throw new ConfigError(`Failed to load configuration: ${error}`);
		}
	}

	get(): CLIConfig {
		return this.config;
	}

	set(key: keyof CLIConfig, value: unknown): void {
		try {
			this.config[key] = value as never;
			configStore.set(key, value as never);
			logger.debug(`Config updated: ${key} = ${value}`);
		} catch (error) {
			logger.error(`Failed to set config ${key}:`, error);
			throw new ConfigError(`Failed to set configuration: ${error}`);
		}
	}

	update(partial: Partial<CLIConfig>): void {
		try {
			this.config = {...this.config, ...partial};
			configStore.set(partial);
			logger.debug('Configuration updated', partial);
		} catch (error) {
			logger.error('Failed to update configuration:', error);
			throw new ConfigError(`Failed to update configuration: ${error}`);
		}
	}

	reset(): void {
		try {
			configStore.clear();
			this.config = {...defaultConfig};
			logger.info('Configuration reset to defaults');
		} catch (error) {
			logger.error('Failed to reset configuration:', error);
			throw new ConfigError(`Failed to reset configuration: ${error}`);
		}
	}

	reinitialize(): void {
		try {
			this.loadConfig();
			logger.info('Configuration reinitialized');
		} catch (error) {
			logger.error('Failed to reinitialize configuration:', error);
			throw new ConfigError(`Failed to reinitialize configuration: ${error}`);
		}
	}

	validate(): void {
		try {
			if (!this.config.kratosUrl) {
				throw new Error('KRATOS_URL is required');
			}

			if (!this.config.apiBaseUrl) {
				throw new Error('API_URL is required');
			}

			if (this.config.apiTimeout && this.config.apiTimeout < 0) {
				throw new Error('API_TIMEOUT must be positive');
			}

			if (this.config.maxRetries && this.config.maxRetries < 0) {
				throw new Error('MAX_RETRIES must be positive');
			}

			logger.debug('Configuration validation passed');
		} catch (error) {
			logger.error('Configuration validation failed:', error);
			throw new ConfigError(`Configuration validation failed: ${error}`);
		}
	}
}

// Create and export a singleton instance
export const configManager = new ConfigManager();
