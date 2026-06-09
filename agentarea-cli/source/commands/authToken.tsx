import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import {tokenStorage} from '../utils/storage.js';
import {logger} from '../utils/logger.js';
import readline from 'readline';

interface AuthTokenProps {
	onTokenSet: (token: string) => void;
}

export function AuthToken({onTokenSet}: AuthTokenProps) {
	const [submitted, setSubmitted] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const promptForToken = async () => {
			try {
				const rl = readline.createInterface({
					input: process.stdin,
					output: process.stdout,
				});

				const token = await new Promise<string>(resolve => {
					rl.question('Paste your JWT token: ', answer => {
						rl.close();
						resolve(answer);
					});
				});

				if (!token.trim()) {
					setError('Token cannot be empty');
					return;
				}

				logger.debug('Token submitted, validating...');

				// Parse JWT to validate basic structure
				const parts = token.trim().split('.');
				if (parts.length !== 3) {
					setError(
						'Invalid token format. JWT must have 3 parts separated by dots.',
					);
					return;
				}

				// Try to decode payload to validate it's valid base64
				try {
					JSON.parse(Buffer.from(parts[1], 'base64').toString());
				} catch {
					setError(
						'Invalid token payload. Token does not appear to be a valid JWT.',
					);
					return;
				}

				// Save token
				const authToken = {
					accessToken: token.trim(),
					tokenType: 'Bearer',
					expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000),
				};

				await tokenStorage.saveToken(authToken);
				logger.info('Token saved successfully');
				setSubmitted(true);

				// Call callback
				onTokenSet(token.trim());
			} catch (err) {
				const message =
					err instanceof Error ? err.message : 'Failed to save token';
				setError(message);
				logger.error('Failed to save token:', err);
			}
		};

		promptForToken();
	}, [onTokenSet]);

	if (submitted) {
		return (
			<Box flexDirection="column" padding={1}>
				<Text color="green">✓ Token saved successfully!</Text>
			</Box>
		);
	}

	return (
		<Box
			flexDirection="column"
			padding={1}
			borderStyle="round"
			borderColor="cyan"
		>
			<Box marginBottom={1}>
				<Text bold color="cyan">
					🔐 JWT Token Configuration
				</Text>
			</Box>
			<Box marginBottom={1}>
				<Text>
					Paste your JWT token below. It will be saved securely in your system
					keychain.
				</Text>
			</Box>
			{error && (
				<Box marginBottom={1}>
					<Text color="red">❌ {error}</Text>
				</Box>
			)}
		</Box>
	);
}
