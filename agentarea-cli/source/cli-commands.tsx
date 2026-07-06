import React from 'react';
import {render} from 'ink';
import {apiClient} from './services/apiClient.js';
import {tokenStorage} from './utils/storage.js';
import {configManager} from './utils/config.js';
import {logger} from './utils/logger.js';
import {AgentsList} from './commands/agentsList.js';
import {connectClient} from './commands/connect.js';

interface CliOptions {
	token?: string;
	apiUrl?: string;
	scope?: string;
	name?: string;
	client?: string;
	target?: string;
}

export async function handleCliCommand(
	command: string | undefined,
	subcommand: string | undefined,
	options: CliOptions,
): Promise<boolean> {
	// Initialize config with provided API URL if specified
	if (options.apiUrl) {
		process.env['API_URL'] = options.apiUrl;
		configManager.reinitialize();
		apiClient.reinitialize();
	}

	// Load token from CLI flag or environment
	const token = options.token || process.env['AGENTAREA_TOKEN'];
	let loadedToken = token;

	// If no token provided, try to load from keychain
	if (!loadedToken) {
		try {
			const storedToken = await tokenStorage.getToken();
			if (storedToken) {
				loadedToken = storedToken.accessToken;
			}
		} catch (error) {
			logger.warn('Failed to load stored token');
		}
	}

	// If still no token, show error
	if (!loadedToken) {
		console.error('❌ Error: No authentication token provided');
		console.error('Provide a JWT token via:');
		console.error('  agentarea-cli --token=YOUR_JWT_TOKEN agents list');
		console.error('  AGENTAREA_TOKEN=YOUR_JWT_TOKEN agentarea-cli agents list');
		process.exit(1);
	}

	// Set token for API client
	const authToken = {
		accessToken: loadedToken,
		tokenType: 'Bearer',
		expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000),
	};
	apiClient.setToken(authToken);

	// Handle specific commands
	if (command === 'agents' && subcommand === 'list') {
		render(<AgentsList />);
		return true;
	}

	if (command === 'connect') {
		return connectClient(subcommand, {
			apiUrl: options.apiUrl || 'http://localhost:8000',
			token: authToken,
			scope: options.scope,
			name: options.name,
		});
	}

	if (command === 'mcp' && subcommand === 'sync') {
		if (!options.client) {
			console.error(
				'Usage: agentarea-cli mcp sync --client=<id> [--target=codex|claude]',
			);
			return false;
		}
		const target = options.target || 'claude';
		const apiUrl = options.apiUrl || 'http://localhost:8000';
		// Record which harness this client was synced for so the UI reflects it.
		try {
			await fetch(`${apiUrl}/v1/clients/${options.client}`, {
				method: 'PATCH',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${authToken}`,
				},
				body: JSON.stringify({kind: target}),
			});
		} catch {
			// Non-fatal: the connection still works without the kind label.
		}
		return connectClient(target, {
			apiUrl,
			token: authToken,
			scope: options.scope,
			name: options.name,
			clientId: options.client,
		});
	}

	// No command matched
	return false;
}
