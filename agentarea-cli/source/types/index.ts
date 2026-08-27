// Authentication Types
export interface User {
	id: string;
	email: string;
	name?: string;
	createdAt: Date;
	lastLoginAt?: Date;
}

export interface AuthToken {
	accessToken: string;
	refreshToken?: string;
	expiresAt?: Date;
	tokenType: string;
	// Set by the OAuth login flow: the dynamically registered client and the API
	// it was registered against, so a refresh can be replayed without a browser.
	clientId?: string;
	apiUrl?: string;
}

export interface Credentials {
	email: string;
	password: string;
	apiKey?: string;
}

// Agent Types
export type AgentStatus = 'online' | 'offline' | 'busy' | 'error';

export interface Agent {
	id: string;
	name: string;
	description?: string;
	status: AgentStatus;
	capabilities: string[];
	version?: string;
	metadata?: Record<string, unknown>;
	lastHeartbeat?: Date;
}

export interface AgentList {
	agents: Agent[];
	total: number;
	timestamp: Date;
}

// Task Types
export type TaskStatus =
	| 'pending'
	| 'running'
	| 'completed'
	| 'failed'
	| 'cancelled';

export interface Task {
	id: string;
	agentId: string;
	title: string;
	description?: string;
	parameters?: Record<string, unknown>;
	status: TaskStatus;
	submittedAt: Date;
	startedAt?: Date;
	completedAt?: Date;
	result?: unknown;
	error?: TaskError;
}

export interface TaskError {
	code: string;
	message: string;
	details?: unknown;
	timestamp: Date;
}

// Task events live in services/sse.ts, typed by the canonical event contract.

// Configuration Types
export interface CLIConfig {
	kratosUrl: string;
	apiBaseUrl: string;
	apiTimeout?: number;
	maxRetries?: number;
	retryDelay?: number;
	streamTimeout?: number;
	logLevel?: 'debug' | 'info' | 'warn' | 'error';
	theme?: 'light' | 'dark' | 'auto';
}

export interface SessionState {
	userId?: string;
	userEmail?: string;
	selectedAgentId?: string;
	recentTaskIds?: string[];
}
