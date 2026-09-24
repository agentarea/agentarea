import { NextRequest, NextResponse } from "next/server";
import { env } from "@/env";
import {
  hasLiveSession,
  isProtectedRoute,
  loginRedirectPath,
} from "@/lib/auth-session";
import { buildContentSecurityPolicy } from "@/lib/csp";
import { createOryMiddleware } from "@/lib/ory/middleware";
import oryConfig from "@/ory.config";

// This function can be marked `async` if using `await` inside
// The middleware automatically reads ORY_SDK_URL from environment variables
export const proxy = async (request: Request) => {
  // Built here, not in next.config's headers(): this webapp is configured at
  // runtime (window.__ENV__, one built image for every environment), so the
  // origins folded into the policy must come from this request's actual
  // environment, not the build machine's.
  const csp = buildContentSecurityPolicy({
    apiOrigin: process.env.API_BROWSER_URL || env.API_URL,
    oryOrigin: env.ORY_BROWSER_URL || env.ORY_SDK_URL,
  });

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
    const redirectResponse = NextResponse.redirect(redirectUrl.toString(), 307);
    redirectResponse.headers.set("Content-Security-Policy", csp);
    return redirectResponse;
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
      const loginUrl = new URL(
        loginRedirectPath(pathname, nextReq.nextUrl.search),
        nextReq.url
      );
      const res = NextResponse.redirect(loginUrl);
      // best-effort clear; fresh login overwrites it regardless. The cookie Domain is
      // configured in the Kratos chart and not known to the webapp, so a Domain-scoped
      // cookie may not match here — the redirect + re-login still self-heals the zombie state.
      res.cookies.delete({ name: "ory_kratos_session", path: "/" });
      res.headers.set("Content-Security-Policy", csp);
      return res;
    }
  }

  const response = await createOryMiddleware(oryConfig)(nextReq);
  response.headers.set("Content-Security-Policy", csp);

  return response;
};

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
