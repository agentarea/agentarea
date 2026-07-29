// Shared output helpers for non-TUI commands. Data goes to stdout as JSON so
// it stays pipeable; diagnostics/logs go to stderr (see utils/logger).

export interface SdkResult {
	data?: unknown;
	error?: unknown;
	response?: {status?: number};
}

export function printJson(value: unknown): void {
	console.log(JSON.stringify(value, null, 2));
}

/**
 * Exit only after stdout/stderr have fully drained. Calling process.exit()
 * straight after a large console.log() truncates piped output at the pipe
 * buffer boundary (~64KB) because the write is still async. A zero-length
 * write's callback fires after all prior writes flush, so we exit there.
 * Returns a never-resolving promise so callers can `await` it as a hard stop.
 */
export function flushAndExit(code: number): Promise<never> {
	return new Promise<never>(() => {
		let remaining = 2;
		const maybeExit = () => {
			remaining -= 1;
			if (remaining <= 0) {
				process.exit(code);
			}
		};

		process.stdout.write('', maybeExit);
		process.stderr.write('', maybeExit);
	});
}

export function reportResult(result: SdkResult): number {
	const status = result.response?.status;
	const failed =
		result.error !== undefined || (status !== undefined && status >= 400);

	if (failed) {
		printJson({status: status ?? null, error: result.error ?? null});
		return status !== undefined && status >= 400 ? 1 : 0;
	}

	printJson(result.data ?? null);
	return 0;
}
