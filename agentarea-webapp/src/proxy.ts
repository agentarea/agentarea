import { NextRequest, NextResponse } from "next/server";
import { env } from "@/env";
import {
  hasLiveSession,
  isProtectedRoute,
  loginRedirectPath,
} from "@/lib/auth-session";
import { createOryMiddleware } from "@/lib/ory/middleware";
import { workspaceSlugFromPath } from "@/lib/workspace-routes";
import { WORKSPACE_REFERENCE_HEADER } from "@/lib/workspaces";
import oryConfig from "@/ory.config";

/**
 * Scope a `/w/{slug}/...` request to its workspace. Pages, RSC fetches and
 * server actions (which post to the page URL) all read the header set here;
 * a client-supplied value is overwritten so the URL is the only source.
 */
function scopeToWorkspace(request: NextRequest, slug: string) {
  const headers = new Headers(request.headers);
  headers.set(WORKSPACE_REFERENCE_HEADER, slug);
  return NextResponse.next({ request: { headers } });
}

/**
 * Pass a request off any workspace page through without a client-supplied
 * workspace header, so server code only ever sees a slug taken from the URL.
 */
function unscoped(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete(WORKSPACE_REFERENCE_HEADER);
  return NextResponse.next({ request: { headers } });
}

// What NextResponse.next() marks a pass-through with, as opposed to a response
// the Ory proxy produced itself.
const PASS_THROUGH_MARKER = "x-middleware-next";

// This function can be marked `async` if using `await` inside
// The middleware automatically reads ORY_SDK_URL from environment variables
export const proxy = async (request: Request) => {
  // Redirect /self-service requests from the current host to NEXT_PUBLIC_ORY_SDK_URL if necessary
  const currentHost = request.headers.get("host");
  const publicOryUrl = env.ORY_BROWSER_URL;
  if (
    currentHost &&
    publicOryUrl &&
    (request.url.startsWith(`http://${currentHost}/self-service`) ||
      request.url.startsWith(`https://${currentHost}/self-service`))
  ) {
    const originalUrl = new URL(request.url);
    const redirectUrl = new URL(publicOryUrl);
    redirectUrl.pathname = originalUrl.pathname;
    redirectUrl.search = originalUrl.search;
    redirectUrl.hash = originalUrl.hash;
    return Response.redirect(redirectUrl.toString(), 307);
  }

  // Single authoritative auth gate. Validated with the SAME criterion the API
  // depends on (tokenize_as=agentarea_jwt) so the rendered shell and the API
  // Authorization can never diverge into a "zombie logged-in" state.
  const nextReq = request as NextRequest;
  const pathname = nextReq.nextUrl.pathname;
  if (pathname === "/app-sandbox") {
    return unscoped(nextReq);
  }
  if (isProtectedRoute(pathname)) {
    const alive = await hasLiveSession(nextReq.headers.get("cookie"), {
      orySdkUrl: env.ORY_SDK_URL,
    });
    if (!alive) {
      const loginUrl = new URL(
        loginRedirectPath(pathname, nextReq.nextUrl.search),
        nextReq.url
      );
      const res = NextResponse.redirect(loginUrl);
      // best-effort clear; fresh login overwrites it regardless. The cookie Domain is
      // configured in the Kratos chart and not known to the webapp, so a Domain-scoped
      // cookie may not match here — the redirect + re-login still self-heals the zombie state.
      res.cookies.delete({ name: "ory_kratos_session", path: "/" });
      return res;
    }
  }

  const slug = workspaceSlugFromPath(pathname);
  if (slug) {
    return scopeToWorkspace(nextReq, slug);
  }

  const response = await createOryMiddleware(oryConfig)(nextReq);
  return response.headers.has(PASS_THROUGH_MARKER)
    ? unscoped(nextReq)
    : response;
};

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
