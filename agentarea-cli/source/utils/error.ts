// Custom error classes for the CLI application

export class CliError extends Error {
	constructor(message: string, public code: string = 'UNKNOWN_ERROR') {
		super(message);
		this.name = 'CliError';
	}
}

export class AuthenticationError extends CliError {
	constructor(message: string) {
		super(message, 'AUTHENTICATION_ERROR');
		this.name = 'AuthenticationError';
	}
}

export class AuthorizationError extends CliError {
	constructor(message: string) {
		super(message, 'AUTHORIZATION_ERROR');
		this.name = 'AuthorizationError';
	}
}

export class NetworkError extends CliError {
	constructor(message: string) {
		super(message, 'NETWORK_ERROR');
		this.name = 'NetworkError';
	}
}

export class ValidationError extends CliError {
	constructor(message: string) {
		super(message, 'VALIDATION_ERROR');
		this.name = 'ValidationError';
	}
}

export class StorageError extends CliError {
	constructor(message: string) {
		super(message, 'STORAGE_ERROR');
		this.name = 'StorageError';
	}
}

export class ConfigError extends CliError {
	constructor(message: string) {
		super(message, 'CONFIG_ERROR');
		this.name = 'ConfigError';
	}
}

export class TaskError extends CliError {
	constructor(message: string) {
		super(message, 'TASK_ERROR');
		this.name = 'TaskError';
	}
}

export class SSEError extends CliError {
	constructor(message: string) {
		super(message, 'SSE_ERROR');
		this.name = 'SSEError';
	}
}

// Helper function to format errors for display
export function formatError(error: unknown): string {
	if (error instanceof CliError) {
		return error.message;
	}

	if (error instanceof Error) {
		return error.message;
	}

	return String(error);
}

// Helper function to check if error is a specific type
export function isAuthError(error: unknown): error is AuthenticationError {
	return error instanceof AuthenticationError;
}

export function isNetworkError(error: unknown): error is NetworkError {
	return error instanceof NetworkError;
}

export function isValidationError(error: unknown): error is ValidationError {
	return error instanceof ValidationError;
}
