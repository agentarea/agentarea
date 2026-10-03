/**
 * Field diffs of an audit event, as lines a person can read.
 *
 * A change's `before`/`after` may be a whole object (a connection's headers or
 * env, a JSON spec). Rendering it with `String()` printed `[object Object]`;
 * instead every leaf that differs becomes its own `a.b.c` line. A value under a
 * key that names a credential, or anywhere inside headers or env, is masked:
 * that it changed is the audit fact, what it changed to is not.
 */

export const MASKED = "***";

export interface AuditChangeLine {
  field: string;
  before: string;
  after: string;
}

interface RawChange {
  field?: unknown;
  before?: unknown;
  after?: unknown;
}

const SENSITIVE_KEY =
  /api[_-]?key|authorization|cookie|credential|password|passwd|private[_-]?key|secret|token/i;

/** Containers whose every value is a credential more often than not. */
const SECRET_CONTAINERS: Record<string, true> = {
  env: true,
  env_vars: true,
  environment: true,
  headers: true,
  secrets: true,
};

const MAX_DEPTH = 4;

type PlainObject = Record<string, unknown>;

function isPlainObject(value: unknown): value is PlainObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSensitivePath(path: string[]): boolean {
  return path.some(
    (segment) =>
      SENSITIVE_KEY.test(segment) ||
      SECRET_CONTAINERS[segment.toLowerCase()] === true
  );
}

function display(value: unknown): string {
  if (value === undefined || value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function flatten(
  path: string[],
  before: unknown,
  after: unknown,
  depth: number,
  out: AuditChangeLine[]
): void {
  if (JSON.stringify(before ?? null) === JSON.stringify(after ?? null)) return;
  const sensitive = isSensitivePath(path);
  const nested =
    depth < MAX_DEPTH &&
    (isPlainObject(before) || isPlainObject(after)) &&
    (before == null || isPlainObject(before)) &&
    (after == null || isPlainObject(after));

  if (nested) {
    const b = isPlainObject(before) ? before : {};
    const a = isPlainObject(after) ? after : {};
    const keys = Array.from(
      new Set([...Object.keys(b), ...Object.keys(a)])
    ).sort();
    for (const key of keys) {
      flatten([...path, key], b[key], a[key], depth + 1, out);
    }
    return;
  }

  out.push({
    field: path.join("."),
    before: sensitive ? (before == null ? "null" : MASKED) : display(before),
    after: sensitive ? (after == null ? "null" : MASKED) : display(after),
  });
}

export function auditChangeLines(
  changes: readonly RawChange[] | null | undefined
): AuditChangeLine[] {
  const lines: AuditChangeLine[] = [];
  for (const change of changes ?? []) {
    const field =
      typeof change.field === "string" && change.field
        ? change.field
        : "unknown";
    flatten([field], change.before, change.after, 0, lines);
  }
  return lines;
}
