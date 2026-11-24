/**
 * Hydra login challenge handler.
 *
 * Hydra redirects users here (URLS_LOGIN) with ?login_challenge=<challenge>.
 * We check their Kratos session and accept/reject the challenge accordingly.
 *
 * Flow:
 *   Hydra → GET /api/hydra/login?login_challenge=<challenge>
 *   → read the login request from Hydra
 *   → check Kratos session cookie
 *   → if invalid: redirect to Kratos login with return_to pointing back here
 *   → if valid: accept or reject (see decision.ts) → redirect back to Hydra
 */

import { NextRequest, NextResponse } from "next/server";
import { type LoginRequest, loginDecision } from "./decision";

const KRATOS_PUBLIC_URL = process.env.ORY_SDK_URL || "http://localhost:4433";
const HYDRA_ADMIN_URL =
  process.env.AGENTAREA_AUTH_HYDRA_ADMIN_URL ||
  "http://localhost:4445";

function loginUrl(suffix: string, challenge: string): string {
  return `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login${suffix}?login_challenge=${encodeURIComponent(challenge)}`;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const loginChallenge = searchParams.get("login_challenge");

  if (!loginChallenge) {
    return NextResponse.json(
      { error: "Missing login_challenge" },
      { status: 400 }
    );
  }

  let loginRequest: LoginRequest;
  try {
    const res = await fetch(loginUrl("", loginChallenge));
    if (!res.ok) {
      const errBody = await res.text();
      console.error("[hydra/login] Failed to load login request:", errBody);
      return NextResponse.json(
        { error: "Failed to load login request" },
        { status: res.status }
      );
    }
    loginRequest = await res.json();
  } catch (err) {
    console.error("[hydra/login] Error loading login request:", err);
    return NextResponse.json(
      { error: "Failed to load login request" },
      { status: 500 }
    );
  }

  // Forward browser cookies to Kratos to check the session
  const cookieHeader = request.headers.get("cookie") || "";

  interface KratosSession {
    identity?: { id?: string };
  }
  let session: KratosSession | null = null;
  try {
    const res = await fetch(`${KRATOS_PUBLIC_URL}/sessions/whoami`, {
      headers: {
        Cookie: cookieHeader,
        Accept: "application/json",
      },
    });
    if (res.ok) {
      session = await res.json();
    }
  } catch (err) {
    console.error("[hydra/login] Failed to check Kratos session:", err);
  }

  if (!session?.identity?.id) {
    // No valid Kratos session — redirect to Kratos login, then back here
    const returnTo = encodeURIComponent(
      `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000"}/api/hydra/login?login_challenge=${encodeURIComponent(loginChallenge)}`
    );
    return NextResponse.redirect(
      `${process.env.ORY_BROWSER_URL || process.env.ORY_SDK_URL || "http://localhost:4433"}/self-service/login/browser?return_to=${returnTo}`
    );
  }

  const decision = loginDecision(loginRequest, session.identity.id);
  if (decision.action === "reject") {
    console.warn(
      "[hydra/login] Rejecting a remembered login for a different user"
    );
  }

  try {
    const res = await fetch(loginUrl(`/${decision.action}`, loginChallenge), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(decision.body),
    });

    if (!res.ok) {
      const errBody = await res.text();
      console.error(
        `[hydra/login] Failed to ${decision.action} login challenge:`,
        errBody
      );
      return NextResponse.json(
        { error: `Failed to ${decision.action} login challenge` },
        { status: 500 }
      );
    }

    const { redirect_to } = await res.json();
    return NextResponse.redirect(redirect_to);
  } catch (err) {
    console.error(
      `[hydra/login] Error during ${decision.action} of login challenge:`,
      err
    );
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
