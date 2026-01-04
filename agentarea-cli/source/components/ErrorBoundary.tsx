import React, {Component, ReactNode} from 'react';
import {Box, Text} from 'ink';
import {logger} from '../utils/logger.js';

interface ErrorBoundaryProps {
	children: ReactNode;
	onTokenExpired?: () => Promise<void>;
}

interface ErrorBoundaryState {
	hasError: boolean;
	error: Error | null;
	errorMessage: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
	constructor(props: ErrorBoundaryProps) {
		super(props);
		this.state = {
			hasError: false,
			error: null,
			errorMessage: '',
		};
	}

	static getDerivedStateFromError(error: Error): ErrorBoundaryState {
		return {
			hasError: true,
			error,
			errorMessage: error.message || 'An unexpected error occurred',
		};
	}

	override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
		logger.error('Error boundary caught error:', error);
		logger.error('Error info:', errorInfo);
	}

	override render() {
		if (this.state.hasError) {
			return (
				<Box flexDirection="column" paddingX={1} paddingY={1} borderStyle="round" borderColor="red">
					<Box marginBottom={1}>
						<Text bold color="red">
							❌ Application Error
						</Text>
					</Box>
					<Box marginBottom={1}>
						<Text color="red">{this.state.errorMessage}</Text>
					</Box>
					<Box>
						<Text dimColor>Please restart the CLI to continue.</Text>
					</Box>
				</Box>
			);
		}

		return this.props.children;
	}
}
