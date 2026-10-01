import { NextRequest, NextResponse } from "next/server";
import { envelopeUpstream, readCapped } from "@/lib/sentry-tunnel";

const MAX_ENVELOPE_BYTES = 1_000_000;
const MAX_HEADER_BYTES = 8_192;
const UPSTREAM_TIMEOUT_MS = 10_000;
const RATE_LIMIT_HEADERS = ["retry-after", "x-sentry-rate-limits"];

// Browser error reports arrive here, same-origin, so ad blockers don't drop
// them on the way to Sentry. The client IP is deliberately not forwarded.
export async function POST(request: NextRequest) {
  const dsn = process.env.SENTRY_DSN;
  if (!dsn) {
    return new NextResponse(null, { status: 404 });
  }
  if (Number(request.headers.get("content-length")) > MAX_ENVELOPE_BYTES) {
    return new NextResponse(null, { status: 413 });
  }

  const body = await readCapped(request.body, MAX_ENVELOPE_BYTES);
  if (!body) {
    return new NextResponse(null, { status: 413 });
  }
  const newline = body.indexOf(0x0a);
  const headerEnd = newline === -1 ? body.byteLength : newline;
  if (headerEnd > MAX_HEADER_BYTES) {
    return new NextResponse(null, { status: 400 });
  }

  const upstream = envelopeUpstream(
    new TextDecoder().decode(body.subarray(0, headerEnd)),
    dsn
  );
  if (!upstream) {
    return new NextResponse(null, { status: 400 });
  }

  try {
    const response = await fetch(upstream, {
      method: "POST",
      body,
      headers: { "Content-Type": "application/x-sentry-envelope" },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    await response.body?.cancel();
    const headers = new Headers();
    for (const name of RATE_LIMIT_HEADERS) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(null, { status: response.status, headers });
  } catch (error) {
    console.error("[sentry-tunnel] forwarding to Sentry failed", error);
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return new NextResponse(null, { status: timedOut ? 504 : 502 });
  }
}
