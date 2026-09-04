"use server";

import { cache } from "react";
import { getAuthToken } from "./getAuthToken";
import { getWorkspaceContext } from "./workspace-context";

export interface AuthContext {
  userId: string | null;
  workspaceId: string | null;
  email: string | null;
  name: string | null;
  username: string | null;
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const json = Buffer.from(
      part.replace(/-/g, "+").replace(/_/g, "/"),
      "base64"
    ).toString("utf8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function getStringClaim(
  payload: Record<string, unknown> | null,
  key: string
): string | null {
  const value = payload?.[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function getNameClaim(payload: Record<string, unknown> | null): string | null {
  const value = payload?.name;
  if (typeof value === "string" && value.length > 0) return value;
  if (!value || typeof value !== "object") return null;

  const name = value as { first?: unknown; last?: unknown };
  const parts = [name.first, name.last].filter(
    (part): part is string => typeof part === "string" && part.length > 0
  );
  return parts.length > 0 ? parts.join(" ") : null;
}

async function getAuthContextImpl(): Promise<AuthContext> {
  const token = await getAuthToken();
  if (!token) {
    return {
      userId: null,
      workspaceId: null,
      email: null,
      name: null,
      username: null,
    };
  }

  const payload = decodeJwtPayload(token);
  const userId = getStringClaim(payload, "sub");
  const email = getStringClaim(payload, "email");
  const name = getNameClaim(payload);
  const username = getStringClaim(payload, "username");
  // The token's workspace claim only names the default workspace, so it goes
  // stale the moment the switcher points elsewhere. Callers pass workspaceId
  // into path-scoped endpoints (members, invitations), which would then read
  // the wrong workspace — resolve the active one instead, and fall back to the
  // claim when the list is unavailable. The backend falls back to user_id when
  // the token carries no claim at all (every user has a personal workspace).
  const { active } = await getWorkspaceContext();
  const workspaceId =
    active?.id ?? (payload?.workspace_id as string) ?? userId;

  return { userId, workspaceId, email, name, username };
}

export const getAuthContext = cache(getAuthContextImpl);
