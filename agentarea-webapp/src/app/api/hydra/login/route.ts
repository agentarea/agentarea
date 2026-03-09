/**
 * Hydra login challenge handler.
 *
 * Hydra redirects users here (URLS_LOGIN) with ?login_challenge=<challenge>.
 * We check their Kratos session and accept/reject the challenge accordingly.
 *
 * Flow:
 *   Hydra → GET /api/hydra/login?login_challenge=<challenge>
 *   → check Kratos session cookie
 *   → if valid: accept challenge → redirect back to Hydra
 *   → if invalid: redirect to Kratos login with return_to pointing back here
 */

import { NextRequest, NextResponse } from "next/server";

const KRATOS_PUBLIC_URL = process.env.ORY_SDK_URL || "http://localhost:4433";
const HYDRA_ADMIN_URL =
  process.env.HYDRA_ADMIN_URL ||
  process.env.NEXT_PUBLIC_ORY_HYDRA_ADMIN_URL ||
  "http://localhost:4445";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const loginChallenge = searchParams.get("login_challenge");

  if (!loginChallenge) {
    return NextResponse.json({ error: "Missing login_challenge" }, { status: 400 });
  }

  // Forward browser cookies to Kratos to check the session
  const cookieHeader = request.headers.get("cookie") || "";

  let session: any = null;
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

  if (!session?.identity) {
    // No valid Kratos session — redirect to Kratos login, then back here
    const returnTo = encodeURIComponent(
      `${process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000"}/api/hydra/login?login_challenge=${loginChallenge}`
    );
    return NextResponse.redirect(
      `${process.env.NEXT_PUBLIC_ORY_SDK_URL || "http://localhost:4433"}/self-service/login/browser?return_to=${returnTo}`
    );
  }

  const subject = session.identity.id as string;

  // Accept the Hydra login challenge
  try {
    const acceptRes = await fetch(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login/accept?login_challenge=${loginChallenge}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject,
          remember: true,
          remember_for: 3600,
          context: {
            // Pass workspace_id (uses user_id as workspace per platform convention)
            workspace_id: subject,
          },
        }),
      }
    );

    if (!acceptRes.ok) {
      const errBody = await acceptRes.text();
      console.error("[hydra/login] Failed to accept login challenge:", errBody);
      return NextResponse.json({ error: "Failed to accept login challenge" }, { status: 500 });
    }

    const { redirect_to } = await acceptRes.json();
    return NextResponse.redirect(redirect_to);
  } catch (err) {
    console.error("[hydra/login] Error accepting login challenge:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
