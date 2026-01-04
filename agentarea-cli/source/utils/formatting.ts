/**
 * Terminal formatting utilities for styled output
 */

const colors = {
	reset: '\x1b[0m',
	bright: '\x1b[1m',
	dim: '\x1b[2m',
	cyan: '\x1b[36m',
	green: '\x1b[32m',
	yellow: '\x1b[33m',
	red: '\x1b[31m',
	blue: '\x1b[34m',
	gray: '\x1b[90m',
};

export function formatPrompt(text: string): string {
	return `${colors.cyan}▶${colors.reset} ${colors.bright}${text}${colors.reset}`;
}

export function formatInput(input: string): string {
	return `${colors.blue}${input}${colors.reset}`;
}

export function formatSuccess(message: string): string {
	return `${colors.green}✓${colors.reset} ${message}`;
}

export function formatError(message: string): string {
	return `${colors.red}✗${colors.reset} ${message}`;
}

export function formatInfo(message: string): string {
	return `${colors.cyan}ℹ${colors.reset} ${message}`;
}

export function formatHeader(title: string): string {
	const line = '─'.repeat(80);
	return `
${colors.bright}${colors.cyan}┌${line}┐${colors.reset}
${colors.bright}${colors.cyan}│${colors.reset} ${colors.bright}${title}${colors.reset}
${colors.bright}${colors.cyan}└${line}┘${colors.reset}
`;
}

export function formatCommand(command: string): string {
	return `${colors.gray}${command}${colors.reset}`;
}

export function formatHighlight(text: string): string {
	return `${colors.bright}${colors.yellow}${text}${colors.reset}`;
}

export function formatDim(text: string): string {
	return `${colors.dim}${colors.gray}${text}${colors.reset}`;
}

export function formatCode(code: string): string {
	return `${colors.blue}${code}${colors.reset}`;
}

export function clearLine(): void {
	process.stdout.write('\x1b[2K\r');
}

export function moveCursorUp(lines = 1): void {
	process.stdout.write(`\x1b[${lines}A`);
}

export function hideCursor(): void {
	process.stdout.write('\x1b[?25l');
}

export function showCursor(): void {
	process.stdout.write('\x1b[?25h');
}
