import process from 'process';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const logLevels: Record<LogLevel, number> = {
	debug: 0,
	info: 1,
	warn: 2,
	error: 3,
};

class Logger {
	private currentLevel: LogLevel;

	constructor(level: LogLevel = 'info') {
		this.currentLevel = level;
	}

	setLevel(level: LogLevel): void {
		this.currentLevel = level;
	}

	private shouldLog(level: LogLevel): boolean {
		return logLevels[level] >= logLevels[this.currentLevel];
	}

	debug(...args: unknown[]): void {
		if (this.shouldLog('debug')) {
			// Diagnostics go to stderr so stdout carries only command data
			// (JSON from `api`/`policies list` etc. stays pipeable into jq).
			console.error('[DEBUG]', ...args);
		}
	}

	info(...args: unknown[]): void {
		if (this.shouldLog('info')) {
			console.error('[INFO]', ...args);
		}
	}

	warn(...args: unknown[]): void {
		if (this.shouldLog('warn')) {
			console.warn('[WARN]', ...args);
		}
	}

	error(...args: unknown[]): void {
		if (this.shouldLog('error')) {
			console.error('[ERROR]', ...args);
		}
	}
}

// Create a default logger instance
const logLevel = (process.env['LOG_LEVEL'] as LogLevel) || 'info';
export const logger = new Logger(logLevel);

export default logger;
