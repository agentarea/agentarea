/**
 * Server-side proxy for Hydra admin consent API.
 *
 * Keeps the Hydra admin URL server-side only — never exposed to the browser.
 * Every request must carry a live Kratos session, AND that session's
 * identity must be the subject Hydra recorded for the consent request
 * (returned by getOAuth2ConsentRequest). A live session alone is not
 * enough — otherwise a logged-in user B could read or accept a consent
 * challenge that belongs to user A's login.
 *
 * GET  /api/hydra/consent?challenge=<challenge>
 *   → fetch consent request details
 *
 * PUT  /api/hydra/consent?challenge=<challenge>&action=accept
 *   → accept the consent challenge (body forwarded as-is)
 *
 * PUT  /api/hydra/consent?challenge=<challenge>&action=reject
 *   → reject the consent challenge (body forwarded as-is)
 */

import { NextRequest, NextResponse } from "next/server";
import { getLiveSessionIdentityId } from "@/lib/auth-session";
import { sessionMatchesConsentSubject } from "./subject-match";

const HYDRA_ADMIN_URL =
  process.env.HYDRA_ADMIN_URL ||
  process.env.ORY_HYDRA_ADMIN_URL ||
  "http://localhost:4445";
const KRATOS_PUBLIC_URL = process.env.ORY_SDK_URL || "http://localhost:4433";

async function requireSessionIdentity(
  request: NextRequest
): Promise<string | null> {
  return getLiveSessionIdentityId(request.headers.get("cookie"), {
    orySdkUrl: KRATOS_PUBLIC_URL,
  });
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const challenge = searchParams.get("challenge");

  if (!challenge) {
    return NextResponse.json({ error: "Missing challenge" }, { status: 400 });
  }

  const sessionIdentityId = await requireSessionIdentity(request);
  if (!sessionIdentityId) {
    return NextResponse.json({ error: "No active session" }, { status: 401 });
  }

  try {
    const res = await fetch(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent?consent_challenge=${challenge}`
    );
    const data = await res.json();
    if (
      res.ok &&
      !sessionMatchesConsentSubject(sessionIdentityId, data?.subject)
    ) {
      return NextResponse.json(
        { error: "Consent request does not belong to this session" },
        { status: 403 }
      );
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[hydra/consent] Failed to fetch consent request:", err);
    return NextResponse.json(
      { error: "Failed to fetch consent request" },
      { status: 500 }
    );
  }
}

export async function PUT(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const challenge = searchParams.get("challenge");
  const action = searchParams.get("action");

  if (!challenge || !action) {
    return NextResponse.json(
      { error: "Missing challenge or action" },
      { status: 400 }
    );
  }

  if (action !== "accept" && action !== "reject") {
    return NextResponse.json(
      { error: "action must be accept or reject" },
      { status: 400 }
    );
  }

  const sessionIdentityId = await requireSessionIdentity(request);
  if (!sessionIdentityId) {
    return NextResponse.json({ error: "No active session" }, { status: 401 });
  }

  try {
    const consentRes = await fetch(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent?consent_challenge=${challenge}`
    );
    if (!consentRes.ok) {
      const errBody = await consentRes.text();
      console.error(
        `[hydra/consent] Failed to load consent request before ${action}:`,
        errBody
      );
      return NextResponse.json(
        { error: "Failed to load consent request" },
        { status: consentRes.status }
      );
    }
    const consentRequest = await consentRes.json();
    if (
      !sessionMatchesConsentSubject(sessionIdentityId, consentRequest?.subject)
    ) {
      return NextResponse.json(
        { error: "Consent request does not belong to this session" },
        { status: 403 }
      );
    }
  } catch (err) {
    console.error(
      "[hydra/consent] Failed to verify consent request subject:",
      err
    );
    return NextResponse.json(
      { error: "Failed to verify consent request" },
      { status: 500 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const hydraPath =
    action === "accept"
      ? `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/accept?consent_challenge=${challenge}`
      : `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/reject?consent_challenge=${challenge}`;

  try {
    const res = await fetch(hydraPath, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error(`[hydra/consent] Failed to ${action} consent:`, err);
    return NextResponse.json(
      { error: `Failed to ${action} consent` },
      { status: 500 }
    );
  }
}
