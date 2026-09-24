import { NextResponse } from "next/server";
import {
  McpUiResourceCspSchema,
  type McpUiResourceCsp,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { env } from "@/env";
import { buildSandboxCsp } from "@/lib/mcp-apps/csp";

function configuredOrigin(value: string | undefined): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function inlineScriptValue(value: string): string {
  return JSON.stringify(value).replaceAll("<", "\\u003c");
}

function sandboxHtml(appOrigin: string): string {
  const allowedHostOrigin = inlineScriptValue(appOrigin);

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MCP App sandbox</title>
    <style>
      :root, body { width: 100%; height: 100%; margin: 0; padding: 0; }
      body { overflow: hidden; }
      iframe { display: block; width: 100%; height: 100%; border: 0; }
    </style>
  </head>
  <body>
    <script>
      (() => {
        "use strict";

        if (window.self === window.top) {
          throw new Error("The MCP Apps sandbox must be embedded");
        }

        const allowedHostOrigin = ${allowedHostOrigin};
        const referrer = document.referrer;
        let hostOrigin;
        try {
          hostOrigin = new URL(referrer).origin;
        } catch {
          throw new Error("The MCP Apps sandbox requires a valid embedding origin");
        }
        if (hostOrigin !== allowedHostOrigin) {
          throw new Error("The MCP Apps sandbox embedding origin is not allowed");
        }

        // A sandbox that can read its parent is misconfigured and must not run.
        try {
          void window.top.document;
          throw new Error("The MCP Apps sandbox can reach its host");
        } catch (error) {
          if (error instanceof Error && error.message === "The MCP Apps sandbox can reach its host") {
            throw error;
          }
        }

        const ownOrigin = window.location.origin;
        const inner = document.createElement("iframe");
        inner.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
        document.body.append(inner);

        const resourceReady = "ui/notifications/sandbox-resource-ready";
        const proxyReady = "ui/notifications/sandbox-proxy-ready";

        window.addEventListener("message", (event) => {
          if (event.source === window.parent) {
            if (event.origin !== hostOrigin) return;
            const message = event.data;
            if (!message || typeof message !== "object") return;

            if (message.method === resourceReady) {
              const params = message.params;
              if (!params || typeof params.html !== "string") return;
              if (typeof params.sandbox === "string") {
                inner.setAttribute("sandbox", params.sandbox);
              }
              const doc = inner.contentDocument;
              if (doc) {
                doc.open();
                doc.write(params.html);
                doc.close();
              } else {
                inner.srcdoc = params.html;
              }
              return;
            }

            inner.contentWindow?.postMessage(message, ownOrigin);
            return;
          }

          if (event.source === inner.contentWindow) {
            if (event.origin !== ownOrigin) return;
            window.parent.postMessage(event.data, hostOrigin);
          }
        });

        window.parent.postMessage(
          { jsonrpc: "2.0", method: proxyReady, params: {} },
          hostOrigin
        );
      })();
    </script>
  </body>
</html>`;
}

export function GET(request: Request) {
  const sandboxOrigin = configuredOrigin(env.MCP_APPS_SANDBOX_ORIGIN);
  const requestHost = request.headers.get("host")?.toLowerCase();
  const sandboxHost = sandboxOrigin
    ? new URL(sandboxOrigin).host.toLowerCase()
    : null;
  if (!sandboxOrigin || requestHost !== sandboxHost) {
    return new NextResponse("MCP Apps sandbox is not served on this origin", {
      status: 404,
    });
  }

  const appOrigin = configuredOrigin(env.WEBAPP_PUBLIC_ORIGIN);
  if (!appOrigin) {
    return new NextResponse("MCP Apps host origin is not configured", {
      status: 500,
    });
  }

  const referer = request.headers.get("referer");
  if (referer) {
    const refererOrigin = configuredOrigin(referer);
    if (refererOrigin !== appOrigin) {
      return new NextResponse(
        "MCP Apps sandbox embedding origin is not allowed",
        {
          status: 403,
        }
      );
    }
  }

  let csp: McpUiResourceCsp | undefined;
  const cspValue = new URL(request.url).searchParams.get("csp");
  if (cspValue) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(cspValue);
    } catch {
      return new NextResponse("csp must be valid JSON", { status: 400 });
    }
    const result = McpUiResourceCspSchema.safeParse(parsed);
    if (!result.success) {
      return new NextResponse("csp is not a valid MCP Apps CSP", {
        status: 400,
      });
    }
    csp = result.data;
  }

  return new NextResponse(sandboxHtml(appOrigin), {
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy": buildSandboxCsp(csp, appOrigin),
      "Content-Type": "text/html; charset=utf-8",
    },
  });
}
