import React, {useEffect} from 'react';
import {signalHandler} from './utils/signals.js';
import {logger} from './utils/logger.js';
import {configManager} from './utils/config.js';
import {apiClient} from './services/apiClient.js';
import {initApiClient, setRuntimeToken} from './services/apiRuntime.js';
import {ErrorBoundary} from './components/ErrorBoundary.js';
import TUI from './tui.js';

interface AppProps {
	token?: string;
	apiUrl?: string;
}

export default function App({token: cliToken, apiUrl}: AppProps) {
	// Initialize config with provided API URL if specified
	if (apiUrl) {
		process.env['API_URL'] = apiUrl;
		configManager.reinitialize();
		apiClient.reinitialize();
	}

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
