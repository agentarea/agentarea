import { NextRequest, NextResponse } from "next/server";
import { envelopeUpstream } from "@/lib/sentry-tunnel";

// Browser error reports arrive here, same-origin, so ad blockers don't drop
// them on the way to Sentry. The client IP is deliberately not forwarded.
export async function POST(request: NextRequest) {
  const body = new Uint8Array(await request.arrayBuffer());
  const newline = body.indexOf(0x0a);
  const headerLine = new TextDecoder().decode(
    newline === -1 ? body : body.subarray(0, newline)
  );

  const upstream = envelopeUpstream(headerLine, process.env.SENTRY_DSN);
  if (!upstream) {
    return new NextResponse(null, { status: 400 });
  }

  try {
    const response = await fetch(upstream, {
      method: "POST",
      body,
      headers: { "Content-Type": "application/x-sentry-envelope" },
    });
    return new NextResponse(null, { status: response.status });
  } catch (error) {
    console.error("[sentry-tunnel] forwarding to Sentry failed", error);
    return new NextResponse(null, { status: 502 });
  }
}
