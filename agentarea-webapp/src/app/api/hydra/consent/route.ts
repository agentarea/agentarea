/**
 * Server-side proxy for Hydra admin consent API.
 *
 * Keeps the Hydra admin URL server-side only — never exposed to the browser.
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

const HYDRA_ADMIN_URL =
  process.env.HYDRA_ADMIN_URL ||
  process.env.NEXT_PUBLIC_ORY_HYDRA_ADMIN_URL ||
  "http://localhost:4445";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const challenge = searchParams.get("challenge");

  if (!challenge) {
    return NextResponse.json({ error: "Missing challenge" }, { status: 400 });
  }

  try {
    const res = await fetch(
      `${HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent?consent_challenge=${challenge}`
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[hydra/consent] Failed to fetch consent request:", err);
    return NextResponse.json({ error: "Failed to fetch consent request" }, { status: 500 });
  }
}

export async function PUT(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const challenge = searchParams.get("challenge");
  const action = searchParams.get("action");

  if (!challenge || !action) {
    return NextResponse.json({ error: "Missing challenge or action" }, { status: 400 });
  }

  if (action !== "accept" && action !== "reject") {
    return NextResponse.json({ error: "action must be accept or reject" }, { status: 400 });
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
    return NextResponse.json({ error: `Failed to ${action} consent` }, { status: 500 });
  }
}
