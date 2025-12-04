import { createOryMiddleware } from "@ory/nextjs/middleware";
import oryConfig from "@/ory.config";
import { NextRequest } from "next/server";

// This function can be marked `async` if using `await` inside
// The middleware automatically reads ORY_SDK_URL from environment variables
export const middleware = (request: Request) => {
  // Redirect /self-service requests from the current host to NEXT_PUBLIC_ORY_SDK_URL if necessary
  const currentHost = request.headers.get("host");
  const publicOryUrl = process.env.NEXT_PUBLIC_ORY_SDK_URL;
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
  return createOryMiddleware(oryConfig)(request as NextRequest);
};


export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
