import { describe, expect, test } from "bun:test";
import { CallerContextError, callerFromHeaders, verifyContextToken } from "./caller.ts";

// Minted by agentarea_mcp.tool_context.sign_context (the platform) at iat 1792000000.
const KEY = "4896aeffbc037762218722536c6b3909507c657b401b1dfd840e39b056c940f8";
const INSTANCE = "c92f0870-465a-4c70-8c11-b33d08fd8c54";
const NOW = new Date(1792000000 * 1000 + 60_000);
const USER_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwcm90b2NvbCI6IjEiLCJ3b3Jrc3BhY2VfaWQiOiJ3cy0xIiwidXNlcl9pZCI6InVzZXItMSIsInVzZXJfZW1haWwiOiJtYXlhQGFjbWUucnUiLCJpc3MiOiJhZ2VudGFyZWEiLCJhdWQiOiJjOTJmMDg3MC00NjVhLTRjNzAtOGMxMS1iMzNkMDhmZDhjNTQiLCJpYXQiOjE3OTIwMDAwMDAsImV4cCI6MTc5MjAwMDMwMCwianRpIjoiZjU0NzE1YzMtNjg1Ni00ZTYxLTkzODctMmYyNmEwNDhkN2YzIiwidG9vbCI6ImNyZWF0ZV90YXNrIn0.dlPEg0_qAjVF-tZtifRafPI680l0y5jM4-6JThC7DH4";
const AGENT_TOKEN =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJwcm90b2NvbCI6IjEiLCJ0YXNrX2lkIjoidGFzay0xIiwidG9vbF9jYWxsX2lkIjoiY2FsbC0xIiwid29ya3NwYWNlX2lkIjoid3MtMSIsImlkZW1wb3RlbmN5X2tleSI6InRhc2stMTpjYWxsLTEiLCJhZ2VudF9pZCI6IjdiMTQ2ZDI5LWQ4ZmQtNDVjNy04ZDQ2LTkxZDAyYThmNWIwNiIsImlzcyI6ImFnZW50YXJlYSIsImF1ZCI6ImM5MmYwODcwLTQ2NWEtNGM3MC04YzExLWIzM2QwOGZkOGM1NCIsImlhdCI6MTc5MjAwMDAwMCwiZXhwIjoxNzkyMDAwMzAwLCJqdGkiOiI2NzVhZmM3MS01Mzg0LTRiZjUtYmVlMy02YmY1NGRmZWJmMmUiLCJ0b29sIjoidXBkYXRlX3Rhc2sifQ.SnOx-0cwRnw-Qo7lMXEZJbRgQ0iSSBEQDd79Hu2jKzs";

const opts = { key: KEY, audience: INSTANCE, now: NOW };

describe("verifyContextToken", () => {
  test("a person's direct call becomes a user caller", async () => {
    expect(await verifyContextToken(USER_TOKEN, opts)).toEqual({
      kind: "user",
      id: "user-1",
      workspaceId: "ws-1",
      email: "maya@acme.ru",
      clientId: undefined,
      taskId: undefined,
      tool: "create_task",
    });
  });

  test("an agent's call becomes an agent caller with its task", async () => {
    expect(await verifyContextToken(AGENT_TOKEN, opts)).toMatchObject({
      kind: "agent",
      id: "7b146d29-d8fd-45c7-8d46-91d02a8f5b06",
      workspaceId: "ws-1",
      taskId: "task-1",
      tool: "update_task",
    });
  });

  test("a wrong key, another instance, an expired token and a tampered payload are refused", async () => {
    await expect(verifyContextToken(USER_TOKEN, { ...opts, key: "0".repeat(64) })).rejects.toThrow("signature");
    await expect(verifyContextToken(USER_TOKEN, { ...opts, audience: "other" })).rejects.toThrow("audience");
    await expect(verifyContextToken(USER_TOKEN, { ...opts, now: new Date(1792000300 * 1000 + 31_000) })).rejects.toThrow("expired");
    const [h, p, s] = USER_TOKEN.split(".");
    const forged = Buffer.from(Buffer.from(p!, "base64url").toString().replace("user-1", "user-2")).toString("base64url");
    await expect(verifyContextToken(`${h}.${forged}.${s}`, opts)).rejects.toThrow("signature");
    await expect(verifyContextToken("not-a-jwt", opts)).rejects.toBeInstanceOf(CallerContextError);
  });
});

describe("callerFromHeaders", () => {
  test("no header is no caller; a present header must verify", async () => {
    expect(await callerFromHeaders(new Headers(), opts)).toBeNull();
    expect((await callerFromHeaders(new Headers({ "X-AgentArea-Context": USER_TOKEN }), opts))?.id).toBe("user-1");
    await expect(callerFromHeaders(new Headers({ "x-agentarea-context": "spoofed" }), opts)).rejects.toBeInstanceOf(CallerContextError);
  });
});
