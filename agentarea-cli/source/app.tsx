import React, {useEffect} from 'react';
import {signalHandler} from './utils/signals.js';
import {logger} from './utils/logger.js';
import {apiClient} from './services/apiClient.js';
import {
	applyApiUrlFlag,
	initApiClient,
	setRuntimeToken,
} from './services/apiRuntime.js';
import {ErrorBoundary} from './components/ErrorBoundary.js';
import TUI from './tui.js';

interface AppProps {
	token?: string;
	apiUrl?: string;
}

export default function App({token: cliToken, apiUrl}: AppProps) {
	// `--api-url` outranks AGENTAREA_API_URL and the saved config.
	applyApiUrlFlag(apiUrl);

	// Configure the shared API client for SDK-backed calls in the TUI.
	initApiClient();
	if (cliToken) {
		setRuntimeToken(cliToken);
	}

	// Setup 401 error handler for API client
	useEffect(() => {
		apiClient.set401Callback(async error => {
			logger.warn('401 Unauthorized received, prompting for new token');
		});
	}, []);

	// Initialize signal handlers for graceful shutdown
	useEffect(() => {
		signalHandler.initialize();
		logger.info('Application started');

		return () => {
			logger.info('Application shutting down');
		};
	}, []);

	return (
		<ErrorBoundary>
			<TUI token={cliToken} />
		</ErrorBoundary>
	);
}
