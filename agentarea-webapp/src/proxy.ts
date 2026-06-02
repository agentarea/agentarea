import { createOryMiddleware } from "@ory/nextjs/middleware";
import oryConfig from "@/ory.config";
import { NextRequest, NextResponse } from "next/server";
import { env } from "@/env";
import { isProtectedRoute, hasLiveSession } from "@/lib/auth-session";

// This function can be marked `async` if using `await` inside
// The middleware automatically reads ORY_SDK_URL from environment variables
export const proxy = async (request: Request) => {
  // Redirect /self-service requests from the current host to NEXT_PUBLIC_ORY_SDK_URL if necessary
  const currentHost = request.headers.get("host");
  const publicOryUrl = env.ORY_BROWSER_URL;
  if (
    currentHost &&
    publicOryUrl &&
    (
      request.url.startsWith(`http://${currentHost}/self-service`) ||
      request.url.startsWith(`https://${currentHost}/self-service`)
    )
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
  if (isProtectedRoute(pathname)) {
    const alive = await hasLiveSession(nextReq.headers.get("cookie"), {
      orySdkUrl: env.ORY_SDK_URL,
    });
    if (!alive) {
      const loginUrl = new URL("/auth/login", nextReq.url);
      const res = NextResponse.redirect(loginUrl);
      // best-effort clear; fresh login overwrites it regardless. The cookie Domain is
      // configured in the Kratos chart and not known to the webapp, so a Domain-scoped
      // cookie may not match here — the redirect + re-login still self-heals the zombie state.
      res.cookies.delete({ name: "ory_kratos_session", path: "/" });
      return res;
    }
  }

  const response = createOryMiddleware(oryConfig)(nextReq);

  return response;
};


export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
