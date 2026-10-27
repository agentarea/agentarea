/**
 * Who a call is for, as the platform signs it in X-AgentArea-Context
 * (docs/reference/mcp-tool-call-context.md).
 *
 * A platform-run app whose spec opts in with `"context": {"enabled": true}`
 * gets its key as MCP_CONTEXT_KEY and its own id as MCP_INSTANCE_ID; every
 * call an agent, a person in the app's view or a client makes carries an HS256
 * token for that id. Checked with WebCrypto, so the kit stays free of packages.
 */

const SKEW_S = 30;
const MAX_AGE_S = 600;
const HEADER = "x-agentarea-context";

export type Caller = {
  kind: "user" | "agent";
  /** The person's user id, or the agent's id. */
  id: string;
  workspaceId: string;
  email?: string;
  /** The client a person's call came through. */
  clientId?: string;
  /** The task an agent's call belongs to. */
  taskId?: string;
  /** The tool the token is for, when the request is exactly one tools/call. */
  tool?: string;
};

export class CallerContextError extends Error {}

export type VerifyOptions = { key: string; audience: string; now?: Date };

const encoder = new TextEncoder();

function decodeSegment(segment: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9_-]*$/.test(segment)) throw new CallerContextError("caller context is not a JWT");
  return Uint8Array.from(Buffer.from(segment, "base64url"));
}

function json(segment: string): Record<string, unknown> {
  try {
    const value = JSON.parse(new TextDecoder().decode(decodeSegment(segment)));
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  } catch {
    // fall through
  }
  throw new CallerContextError("caller context is not a JWT");
}

const text = (value: unknown) => (typeof value === "string" && value !== "" ? value : undefined);

/** Checks the token's HS256 signature, issuer, audience and age, and returns who it names. */
export async function verifyContextToken(token: string, options: VerifyOptions): Promise<Caller> {
  const parts = token.split(".");
  if (parts.length !== 3) throw new CallerContextError("caller context is not a JWT");
  const [headerPart, payloadPart, signaturePart] = parts as [string, string, string];
  const header = json(headerPart);
  if (header.alg !== "HS256") throw new CallerContextError("caller context must be signed with HS256");

  const key = await crypto.subtle.importKey("raw", encoder.encode(options.key), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  const valid = await crypto.subtle.verify("HMAC", key, decodeSegment(signaturePart), encoder.encode(`${headerPart}.${payloadPart}`));
  if (!valid) throw new CallerContextError("caller context signature does not match");

  const claims = json(payloadPart);
  const now = Math.floor((options.now ?? new Date()).getTime() / 1000);
  if (claims.iss !== "agentarea") throw new CallerContextError("caller context was not issued by agentarea");
  const audience = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!audience.includes(options.audience)) throw new CallerContextError("caller context audience is another instance");
  if (typeof claims.exp !== "number" || claims.exp + SKEW_S < now) throw new CallerContextError("caller context expired");
  if (typeof claims.iat !== "number" || claims.iat - SKEW_S > now || now - claims.iat > MAX_AGE_S) {
    throw new CallerContextError("caller context was issued at an impossible time");
  }
  const workspaceId = text(claims.workspace_id);
  if (!workspaceId) throw new CallerContextError("caller context names no workspace");

  const agentId = text(claims.agent_id);
  const userId = text(claims.user_id);
  if (agentId) {
    return { kind: "agent", id: agentId, workspaceId, taskId: text(claims.task_id), tool: text(claims.tool) };
  }
  if (userId) {
    return {
      kind: "user",
      id: userId,
      workspaceId,
      email: text(claims.user_email),
      clientId: text(claims.client_id),
      taskId: undefined,
      tool: text(claims.tool),
    };
  }
  throw new CallerContextError("caller context names neither a person nor an agent");
}

/** The caller of one request, null when it carries no context; a context that does not verify throws. */
export async function callerFromHeaders(headers: Headers, options: VerifyOptions): Promise<Caller | null> {
  const token = headers.get(HEADER);
  if (token === null) return null;
  return verifyContextToken(token, options);
}

/** MCP_CONTEXT_KEY and MCP_INSTANCE_ID, or null when the platform gave this app no caller context. */
export function contextOptionsFromEnv(env: Record<string, string | undefined> = process.env): VerifyOptions | null {
  const key = env.MCP_CONTEXT_KEY;
  if (!key) return null;
  const audience = env.MCP_INSTANCE_ID;
  if (!audience) throw new Error("MCP_CONTEXT_KEY is set without MCP_INSTANCE_ID; the platform sets both");
  return { key, audience };
}
