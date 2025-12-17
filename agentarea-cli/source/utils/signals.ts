import process from 'process';
import exitHook from 'async-exit-hook';
import {logger} from './logger.js';

type CleanupFunction = () => Promise<void> | void;

class SignalHandler {
	private cleanupFunctions: CleanupFunction[] = [];
	private isShuttingDown = false;

	registerCleanup(fn: CleanupFunction): void {
		this.cleanupFunctions.push(fn);
		logger.debug('Cleanup function registered');
	}

	initialize(): void {
		// Register async exit hook to handle all termination signals
		exitHook(async callback => {
			if (this.isShuttingDown) {
				callback();
				return;
			}

			this.isShuttingDown = true;
			logger.info('Shutting down gracefully...');

			try {
				// Execute all cleanup functions in order with timeout
				const cleanupPromises = this.cleanupFunctions.map(async fn => {
					try {
						await Promise.resolve(fn());
					} catch (error) {
						logger.error('Cleanup function failed:', error);
					}
				});

				// Set a maximum cleanup time of 5 seconds
				const cleanupTimeout = new Promise<void>(resolve => {
					setTimeout(() => {
						logger.warn('Cleanup timeout reached, forcing exit');
						resolve();
					}, 5000);
				});

				await Promise.race([Promise.all(cleanupPromises), cleanupTimeout]);

				logger.info('Cleanup completed, exiting');
			} catch (error) {
				logger.error('Error during cleanup:', error);
			} finally {
				callback();
			}
		});

		// Handle specific signals
		process.on('SIGINT', () => {
			logger.debug('Received SIGINT');
		});

		process.on('SIGTERM', () => {
			logger.debug('Received SIGTERM');
		});

		logger.debug('Signal handlers initialized');
	}
}

// Export a singleton instance
export const signalHandler = new SignalHandler();
