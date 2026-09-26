"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AppBridge,
  PostMessageTransport,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import {
  callMcpAppToolAction,
  startMcpAppAction,
} from "@/app/w/[workspace]/(main)/apps/actions";
import { parseMcpAppLink, type McpAppLink } from "@/lib/apps/links";
import type { McpAppUiResource } from "@/lib/apps/mcp/tools";
import {
  MCP_UI_STYLE_TOKEN_NAMES,
  mcpUiStyleVariablesFromTokens,
} from "@/lib/apps/styles";

const HOST_INFO = {
  name: "AgentArea MCP Apps",
  version: "0.1.0",
} as const;
const SANDBOX_PROXY_READY = "ui/notifications/sandbox-proxy-ready";
const SANDBOX_PATH = "/app-sandbox";
const PROXY_READY_TIMEOUT_MS = 15_000;
// An app that throws before connecting (a blocked script, a bad bundle) never
// initializes; without a bound the page would say "Loading" forever.
const APP_INITIALIZE_TIMEOUT_MS = 30_000;

type McpAppFrameProps = {
  instanceId: string;
  toolName: string;
  title: string;
  resource: McpAppUiResource;
  /** Must keep its identity between renders: a new object restarts the app. */
  entryArguments: Record<string, unknown>;
  /** Receives the app's links to other UIs of its connection. */
  onOpenApp: (link: McpAppLink) => void;
};

type RuntimeConfig = {
  APPS_SANDBOX_ORIGIN?: string;
};

function runtimeConfig(): RuntimeConfig {
  return (window as Window & { __ENV__?: RuntimeConfig }).__ENV__ ?? {};
}

// next-themes puts the theme class on <html> in its own effect, which runs
// after this component's effects, so the theme and the tokens are both read
// from the DOM rather than from `useTheme()`.
function readHostAppearance(): Pick<McpUiHostContext, "theme" | "styles"> {
  const root = document.documentElement;
  const computed = getComputedStyle(root);
  const tokens = Object.fromEntries(
    MCP_UI_STYLE_TOKEN_NAMES.map((name) => [
      name,
      computed.getPropertyValue(name),
    ])
  );
  return {
    theme: root.classList.contains("dark") ? "dark" : "light",
    styles: { variables: mcpUiStyleVariablesFromTokens(tokens) },
  };
}

export default function McpAppFrame({
  instanceId,
  toolName,
  title,
  resource,
  entryArguments,
  onOpenApp,
}: McpAppFrameProps) {
  const t = useTranslations("AppsPage");
  const onOpenAppRef = useRef(onOpenApp);
  onOpenAppRef.current = onOpenApp;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<AppBridge | null>(null);
  const [status, setStatus] = useState<"loading" | "running" | "error">(
    "loading"
  );
  const [failure, setFailure] = useState<{
    title: "configurationError" | "resourceError" | "toolError";
    message: string;
  } | null>(null);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    let disposed = false;
    let connected = false;
    let initialized = false;
    const { csp, permissions } = resource;

    const fail = (
      reason: unknown,
      title: "configurationError" | "resourceError" = "resourceError"
    ) => {
      if (disposed) return;
      setFailure({
        title,
        message: reason instanceof Error ? reason.message : String(reason),
      });
      setStatus("error");
      console.error("MCP App failed", reason);
    };

    const sandboxValue = runtimeConfig().APPS_SANDBOX_ORIGIN?.trim();
    if (!sandboxValue) {
      fail(
        new Error("Apps sandbox origin is not configured"),
        "configurationError"
      );
      return;
    }

    let sandboxOrigin: string;
    try {
      sandboxOrigin = new URL(sandboxValue).origin;
    } catch {
      fail(new Error("Apps sandbox origin is invalid"), "configurationError");
      return;
    }
    if (sandboxOrigin === window.location.origin) {
      fail(
        new Error("Apps sandbox must use a different origin"),
        "configurationError"
      );
      return;
    }

    const sandboxUrl = new URL(SANDBOX_PATH, sandboxOrigin);
    if (csp) sandboxUrl.searchParams.set("csp", JSON.stringify(csp));

    let cancelProxyReady = () => {};
    const proxyReady = new Promise<void>((resolve, reject) => {
      const onMessage = (event: MessageEvent) => {
        if (
          event.source !== iframe.contentWindow ||
          event.origin !== sandboxOrigin ||
          event.data?.method !== SANDBOX_PROXY_READY
        ) {
          return;
        }
        cleanup();
        cancelProxyReady = () => {};
        resolve();
      };
      const timer = window.setTimeout(() => {
        cleanup();
        cancelProxyReady = () => {};
        reject(new Error("Timed out waiting for the Apps sandbox"));
      }, PROXY_READY_TIMEOUT_MS);
      const cleanup = () => {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMessage);
      };
      cancelProxyReady = () => {
        cleanup();
        reject(new Error("Apps sandbox setup was cancelled"));
      };
      window.addEventListener("message", onMessage);
    });

    iframe.src = sandboxUrl.href;

    const start = async () => {
      await proxyReady;
      if (disposed || !iframe.contentWindow) return;

      const hostContext: McpUiHostContext = {
        ...readHostAppearance(),
        platform: "web",
        displayMode: "fullscreen",
        availableDisplayModes: ["fullscreen"],
      };
      const bridge = new AppBridge(
        null,
        HOST_INFO,
        { serverTools: {}, openLinks: {} },
        { hostContext }
      );
      bridgeRef.current = bridge;

      // A failed call is the app's to handle: it arrives as an MCP tool error
      // for its own request, and the app keeps running.
      bridge.oncalltool = async (params) =>
        callMcpAppToolAction(instanceId, params.name, params.arguments ?? {});
      // The host offers only fullscreen: the frame fills the page and the app
      // scrolls inside it. Applying reported content heights here stretched
      // the frame past its clipped container and cut tall apps off.
      bridge.onopenlink = async ({ url }) => {
        const appLink = parseMcpAppLink(url);
        if (appLink) {
          onOpenAppRef.current(appLink);
          return {};
        }
        try {
          const target = new URL(url);
          if (target.protocol !== "http:" && target.protocol !== "https:") {
            return { isError: true };
          }
          window.open(target.href, "_blank", "noopener,noreferrer");
          return {};
        } catch {
          return { isError: true };
        }
      };
      // Only problems reach the host console; an app's info and debug chatter
      // stays inside its own frame's devtools.
      bridge.onloggingmessage = ({ level, data }) => {
        if (level === "warning") console.warn("[MCP App]", data);
        else if (["error", "critical", "alert", "emergency"].includes(level)) {
          console.error("[MCP App]", data);
        }
      };
      const initializedPromise = new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(
          () => reject(new Error("The app did not start within 30 seconds")),
          APP_INITIALIZE_TIMEOUT_MS
        );
        bridge.oninitialized = () => {
          window.clearTimeout(timer);
          initialized = true;
          resolve();
        };
      });

      await bridge.connect(
        new PostMessageTransport(iframe.contentWindow, iframe.contentWindow)
      );
      connected = true;
      await bridge.sendSandboxResourceReady({
        html: resource.html,
        csp,
        permissions,
      });
      await initializedPromise;
      if (disposed) return;

      await bridge.sendHostContextChange(readHostAppearance());
      await bridge.sendToolInput({ arguments: entryArguments });
      setStatus("running");

      const started = await startMcpAppAction(
        instanceId,
        toolName,
        entryArguments
      ).catch((error: unknown) => ({
        ok: false as const,
        error: error instanceof Error ? error.message : String(error),
      }));
      if (disposed) return;
      if (started.ok) {
        await bridge.sendToolResult(started.result);
      } else {
        setFailure({ title: "toolError", message: started.error });
        setStatus("error");
        await bridge.sendToolCancelled({ reason: started.error });
      }
    };

    start().catch(fail);

    return () => {
      disposed = true;
      cancelProxyReady();
      const bridge = bridgeRef.current;
      bridgeRef.current = null;
      if (!bridge) return;

      void (async () => {
        try {
          if (
            connected &&
            initialized &&
            typeof bridge.teardownResource === "function"
          ) {
            await bridge.teardownResource({});
          }
        } catch (teardownError) {
          console.error("MCP App teardown failed", teardownError);
        } finally {
          await bridge.close();
        }
      })();
    };
  }, [entryArguments, instanceId, resource, toolName]);

  useEffect(() => {
    const bridge = bridgeRef.current;
    if (!bridge || status !== "running") return;
    const observer = new MutationObserver(() => {
      void bridge.sendHostContextChange(readHostAppearance());
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });
    return () => observer.disconnect();
  }, [status]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
      <iframe
        sandbox="allow-scripts allow-same-origin allow-forms"
        ref={iframeRef}
        title={title}
        className="h-full min-h-0 w-full flex-1 border-0"
        aria-busy={status === "loading"}
      />
      {status === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/90 text-sm text-muted-foreground">
          {t("loading")}
        </div>
      )}
      {status === "error" && failure && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/95 p-6">
          <div
            className="max-w-lg rounded-lg border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive"
            role="alert"
          >
            <p className="font-medium">{t(failure.title)}</p>
            <p className="mt-2 break-words">{failure.message}</p>
          </div>
        </div>
      )}
    </div>
  );
}
