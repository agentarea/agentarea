import { NextResponse } from "next/server";
import { getStreamEventById } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";

/**
 * One event of the workspace feed with what each subscriber did with it, for
 * the feed's side panel: opening an event reads this alone, not the page.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ eventId: string }> }
) {
  const { eventId } = await params;
  const result = await getStreamEventById(eventId);
  if (result.data) {
    return NextResponse.json(result.data, {
      headers: { "Cache-Control": "no-store" },
    });
  }
  const status = result.status ?? 502;
  if (status !== 403 && status !== 404) {
    console.error(
      `Stream event ${eventId} (${status}): ${formatApiError(result.error)}`
    );
  }
  return NextResponse.json(
    { detail: formatApiError(result.error) },
    { status: status === 403 ? 404 : status }
  );
}
