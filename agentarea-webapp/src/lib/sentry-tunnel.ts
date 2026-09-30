export const SENTRY_TUNNEL_PATH = "/api/monitoring";

/**
 * Where to forward a browser error envelope, given its first line. Only
 * envelopes addressed to this deployment's own DSN are forwarded, so the
 * tunnel cannot relay to an arbitrary host or project.
 */
export function envelopeUpstream(
  headerLine: string,
  configuredDsn: string | undefined
): string | null {
  if (!configuredDsn) return null;

  let envelopeDsn: unknown;
  try {
    envelopeDsn = (JSON.parse(headerLine) as { dsn?: unknown }).dsn;
  } catch {
    return null;
  }
  if (typeof envelopeDsn !== "string") return null;

  const target = parseDsn(envelopeDsn);
  const own = parseDsn(configuredDsn);
  if (
    !target ||
    !own ||
    target.protocol !== own.protocol ||
    target.username !== own.username ||
    target.host !== own.host ||
    target.pathname !== own.pathname
  ) {
    return null;
  }

  const segments = own.pathname.split("/").filter(Boolean);
  const projectId = segments.pop();
  const prefix = segments.map((segment) => `/${segment}`).join("");
  const auth = `sentry_version=7&sentry_key=${encodeURIComponent(own.username)}`;
  return `${own.protocol}//${own.host}${prefix}/api/${projectId}/envelope/?${auth}`;
}

function parseDsn(dsn: string): URL | null {
  try {
    return new URL(dsn);
  } catch {
    return null;
  }
}

/** The body, or null once it grows past `maxBytes`; stops reading there. */
export async function readCapped(
  stream: ReadableStream<Uint8Array> | null,
  maxBytes: number
): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!stream) return new Uint8Array(0);
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}
