import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {logger} from './utils/logger.js';
import {apiClient} from './services/apiClient.js';
import {tokenStorage} from './utils/storage.js';
import {AuthToken} from './commands/authToken.js';
import {InteractiveCLI} from './components/InteractiveCLI.js';

interface TUIProps {
	token?: string;
}

export default function TUI({token: cliToken}: TUIProps) {
	const [loadedToken, setLoadedToken] = useState<string | null>(cliToken || null);
	const [loading, setLoading] = useState(!cliToken);
	const [showAuthInput, setShowAuthInput] = useState(false);
	const [tokenExpired, setTokenExpired] = useState(false);

	// Setup 401 error handler for API client
	useEffect(() => {
		apiClient.set401Callback(async (error) => {
			logger.warn('Token expired, prompting for new token');
			setTokenExpired(true);
		});
	}, []);

	// Load token from storage on startup
	useEffect(() => {
		const loadToken = async () => {
			try {
				// If token provided via CLI, use it directly
				if (cliToken) {
					setLoadedToken(cliToken);
					setLoading(false);
					return;
				}

				// Try to load from storage
				const storedToken = await tokenStorage.getToken();
				if (storedToken) {
					setLoadedToken(storedToken.accessToken);
					setLoading(false);
				} else {
					// No token found, show auth input
					setShowAuthInput(true);
					setLoading(false);
				}
			} catch (error) {
				logger.warn('Failed to load stored token');
				setShowAuthInput(true);
				setLoading(false);
			}
		};

		loadToken();
	}, [cliToken]);

	// Set token in API client when loaded
	useEffect(() => {
		if (loadedToken) {
			const authToken = {
				accessToken: loadedToken,
				tokenType: 'Bearer',
				expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000),
			};
			apiClient.setToken(authToken);
			logger.info('Token set for API authentication');
		}
	}, [loadedToken]);

	// Show loading state
	if (loading) {
		return (
			<Box flexDirection="column" padding={1}>
				<Text color="yellow">⏳ Loading authentication state...</Text>
			</Box>
		);
	}

	// Show token input screen if no token or token expired
	if ((!loadedToken && showAuthInput) || tokenExpired) {
		const handleNewToken = (newToken: string) => {
			setLoadedToken(newToken);
			setTokenExpired(false);
			setShowAuthInput(false);
		};

		return <AuthToken onTokenSet={handleNewToken} />;
	}

	if (!loadedToken) {
		return (
			<Box flexDirection="column" padding={1} borderStyle="round" borderColor="red">
				<Box marginBottom={1}>
					<Text bold color="red">
						❌ No Authentication Token
					</Text>
				</Box>
				<Box marginBottom={1}>
					<Text>Provide a JWT token to use the CLI:</Text>
				</Box>
				<Box marginLeft={2} marginBottom={1}>
					<Text>agentarea-cli --token=YOUR_JWT_TOKEN</Text>
				</Box>
				<Box marginBottom={1}>
					<Text>Or set AGENTAREA_TOKEN environment variable:</Text>
				</Box>
				<Box marginLeft={2} marginBottom={1}>
					<Text>AGENTAREA_TOKEN=eyJ... agentarea-cli</Text>
				</Box>
			</Box>
		);
	}

	// Extract user info from JWT if possible
	let userEmail = 'user@agentarea.dev';
	try {
		const parts = loadedToken.split('.');
		if (parts.length === 3) {
			const decoded = JSON.parse(Buffer.from(parts[1], 'base64').toString());
			userEmail = decoded.email || decoded.sub || 'User';
		}
	} catch (error) {
		logger.warn('Could not decode JWT');
	}

	// Show interactive CLI
	return (
		<InteractiveCLI userEmail={userEmail} token={loadedToken} />
	);
}
