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
 * PUT  /api/hydra/consent?challenge=<challenge>&action=accept|reject
 *   → decide the consent challenge; the request body is ignored and the
 *     decision is built from the consent request (see decision-body.ts)
 */

import { NextRequest, NextResponse } from "next/server";
import { getLiveSessionIdentityId } from "@/lib/auth-session";
import { type ConsentRequest, consentDecisionBody } from "./decision-body";
import { sessionMatchesConsentSubject } from "./subject-match";

const HYDRA_ADMIN_URL =
  process.env.AGENTAREA_AUTH_HYDRA_ADMIN_URL ||
  process.env.AGENTAREA_AUTH_HYDRA_ADMIN_URL ||
  "http://localhost:4445";
const KRATOS_PUBLIC_URL = process.env.ORY_SDK_URL || "http://localhost:4433";

function consentUrl(suffix: string, challenge: string): string {
  return `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent${suffix}?consent_challenge=${encodeURIComponent(challenge)}`;
}

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
    const res = await fetch(consentUrl("", challenge));
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

  let consentRequest: ConsentRequest;
  try {
    const consentRes = await fetch(consentUrl("", challenge));
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
    consentRequest = await consentRes.json();
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

  try {
    const res = await fetch(consentUrl(`/${action}`, challenge), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(consentDecisionBody(action, consentRequest)),
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
