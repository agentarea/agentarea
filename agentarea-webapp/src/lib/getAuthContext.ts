"use server";

import { cache } from "react";
import { getAuthToken } from "./getAuthToken";

export interface AuthContext {
  userId: string | null;
  workspaceId: string | null;
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

async function getAuthContextImpl(): Promise<AuthContext> {
  const token = await getAuthToken();
  if (!token) return { userId: null, workspaceId: null };

  const payload = decodeJwtPayload(token);
  const userId = (payload?.sub as string) ?? null;
  // The backend falls back to user_id when the token has no workspace_id claim
  // (each user gets their own personal workspace by default).
  const workspaceId = (payload?.workspace_id as string) ?? userId;

  return { userId, workspaceId };
}

export const getAuthContext = cache(getAuthContextImpl);
