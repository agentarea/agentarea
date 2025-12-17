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

export interface TaskSubmissionRequest {
	agentId: string;
	title: string;
	description?: string;
	parameters?: Record<string, unknown>;
}

export interface TaskResponse {
	taskId: string;
	agentId: string;
	streamUrl: string;
	estimatedDuration?: number;
}

// SSE Event Types
export type TaskEventType =
	| 'output'
	| 'status'
	| 'progress'
	| 'error'
	| 'complete';

export interface TaskOutputEvent {
	eventType: TaskEventType;
	taskId: string;
	timestamp: Date;
	data: TaskOutputData;
}

export type TaskOutputData =
	| OutputChunk
	| StatusUpdate
	| ProgressUpdate
	| ErrorEvent
	| CompletionEvent;

export interface OutputChunk {
	type: 'output';
	content: string;
	stream: 'stdout' | 'stderr';
}

export interface StatusUpdate {
	type: 'status';
	status: TaskStatus;
	message: string;
}

export interface ProgressUpdate {
	type: 'progress';
	current: number;
	total: number;
	percentage: number;
}

export interface ErrorEvent {
	type: 'error';
	code: string;
	message: string;
	details?: unknown;
}

export interface CompletionEvent {
	type: 'complete';
	status: 'success' | 'failure';
	message: string;
	resultSummary?: unknown;
}

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
