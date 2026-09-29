/**
 * Hydra consent redirect handler.
 *
 * Hydra redirects here (urls.consent) with ?consent_challenge=<challenge>.
 * Always forwards to the consent UI page for the user to approve or deny —
 * consent is never auto-accepted here. The backend forces skip_consent=false
 * for every DCR-registered client (see mcp_oauth_as.py), and no first-party
 * client relies on Hydra's skip=true signal, so there is no legitimate case
 * left to auto-accept for.
 */

import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const consentChallenge = searchParams.get("consent_challenge");

  if (!consentChallenge) {
    return NextResponse.json(
      { error: "Missing consent_challenge" },
      { status: 400 }
    );
  }

  const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
  return NextResponse.redirect(
    `${appUrl}/auth/consent?consent_challenge=${consentChallenge}`
  );
}
