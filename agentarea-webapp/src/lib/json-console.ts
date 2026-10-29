import {
  formatWithOptions,
  inspect,
  stripVTControlCharacters,
  types,
} from "node:util";

export type LogLevel = "debug" | "info" | "warn" | "error";

const isError = (value: unknown): value is Error =>
  value instanceof Error || types.isNativeError(value);

/**
 * One console call as one JSON line, so a log collector gets one entry per
 * event with its level, however many lines the stack trace has.
 */
export function formatLogLine(
  level: LogLevel,
  args: unknown[],
  time: Date
): string {
  const error = args.find(isError);
  const [first, ...rest] = args.map((arg) =>
    isError(arg) ? String(arg) : arg
  );
  const msg = formatWithOptions({ breakLength: Infinity }, first, ...rest);
  return JSON.stringify({
    time: time.toISOString(),
    level,
    msg: stripVTControlCharacters(msg),
    // inspect rather than .stack: it also carries the cause chain and
    // Next's digest, which a failed fetch or a render error hide behind.
    ...(error && { error: error.message, stack: inspect(error) }),
  });
}

const METHODS = [
  ["debug", "debug"],
  ["log", "info"],
  ["info", "info"],
  ["warn", "warn"],
  ["error", "error"],
] as const;

/**
 * Writes straight to the stream rather than through the console method it
 * replaces: Next's own wrapper may append ANSI codes to the line.
 */
export function installJsonConsole(): void {
  for (const [method, level] of METHODS) {
    const stream =
      level === "warn" || level === "error" ? process.stderr : process.stdout;
    // eslint-disable-next-line no-console -- replaces the methods, calls none
    console[method] = (...args: unknown[]) => {
      stream.write(`${formatLogLine(level, args, new Date())}\n`);
    };
  }
}
