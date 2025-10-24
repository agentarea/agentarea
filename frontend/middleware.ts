// Copyright © 2024 Ory Corp

import { createOryMiddleware } from "@ory/nextjs/middleware";
import oryConfig from "@/ory.config";

// This function can be marked `async` if using `await` inside
export const middleware = createOryMiddleware(oryConfig);

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
