/**
 * Hydra consent redirect handler.
 *
 * Hydra redirects here (urls.consent) with ?consent_challenge=<challenge>.
 * We fetch the consent request from Hydra admin and:
 *   - If skip=true (client has skip_consent): auto-accept and redirect back to Hydra
 *   - Otherwise: redirect to the consent UI page for user approval
 */

import { NextRequest, NextResponse } from "next/server";

const HYDRA_ADMIN_URL =
  process.env.HYDRA_ADMIN_URL ||
  process.env.ORY_HYDRA_ADMIN_URL ||
  "http://localhost:4445";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const consentChallenge = searchParams.get("consent_challenge");

  if (!consentChallenge) {
    return NextResponse.json({ error: "Missing consent_challenge" }, { status: 400 });
  }

  // Fetch consent request details from Hydra admin
  let consentRequest: any;
  try {
    const res = await fetch(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent?consent_challenge=${consentChallenge}`
    );
    if (!res.ok) {
      console.error("[hydra/consent-redirect] Failed to fetch consent request:", await res.text());
      return NextResponse.json({ error: "Failed to fetch consent request" }, { status: 500 });
    }
    consentRequest = await res.json();
  } catch (err) {
    console.error("[hydra/consent-redirect] Error fetching consent request:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }

  // Auto-accept consent for MCP clients with skip_consent: true,
  // or when Hydra signals skip=true.
  // MCP clients (Cursor, Claude Desktop) register with skip_consent but Hydra
  // may still set skip=false when requested_scope is empty. Check both.
  const clientSkipConsent = consentRequest.client?.skip_consent === true;

  if (consentRequest.skip || clientSkipConsent) {
    // Ensure we grant meaningful scopes even if the client didn't request any.
    // MCP clients often send empty scopes; we default to openid + offline_access
    // so the issued token works for API access.
    const grantScope =
      consentRequest.requested_scope?.length > 0
        ? consentRequest.requested_scope
        : ["openid", "offline_access"];

    const grantAudience =
      consentRequest.requested_access_token_audience?.length > 0
        ? consentRequest.requested_access_token_audience
        : consentRequest.client?.audience || [];

    try {
      const acceptRes = await fetch(
        `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/accept?consent_challenge=${consentChallenge}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            grant_scope: grantScope,
            grant_access_token_audience: grantAudience,
            session: {
              access_token: {
                workspace_id: consentRequest.context?.workspace_id || consentRequest.subject,
              },
              id_token: {
                workspace_id: consentRequest.context?.workspace_id || consentRequest.subject,
              },
            },
          }),
        }
      );

      if (!acceptRes.ok) {
        const errBody = await acceptRes.text();
        console.error("[hydra/consent-redirect] Failed to auto-accept consent:", errBody);
        return NextResponse.json({ error: "Failed to accept consent" }, { status: 500 });
      }

      const { redirect_to } = await acceptRes.json();
      return NextResponse.redirect(redirect_to);
    } catch (err) {
      console.error("[hydra/consent-redirect] Error auto-accepting consent:", err);
      return NextResponse.json({ error: "Internal error" }, { status: 500 });
    }
  }

  // Not skippable — redirect to the consent UI page
  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  return NextResponse.redirect(
    `${appUrl}/auth/consent?consent_challenge=${consentChallenge}`
  );
}
