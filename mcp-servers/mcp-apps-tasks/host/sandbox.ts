/**
 * Outer sandbox frame, served from its own origin. It creates the inner frame
 * that runs the untrusted view and relays messages between it and the host.
 * Adapted from the ext-apps basic-host example.
 */
import {
  buildAllowAttribute,
  type McpUiSandboxProxyReadyNotification,
  type McpUiSandboxResourceReadyNotification,
} from "@modelcontextprotocol/ext-apps/app-bridge";

const ALLOWED_REFERRER = /^http:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/;

if (window.self === window.top) {
  throw new Error("The sandbox page only runs inside a host iframe");
}
if (!ALLOWED_REFERRER.test(document.referrer)) {
  throw new Error(`Embedding page not allowed: ${document.referrer || "no referrer"}`);
}

const HOST_ORIGIN = new URL(document.referrer).origin;
const OWN_ORIGIN = window.location.origin;

// Self-test: reaching into the host must fail. If it does not, the sandbox is
// misconfigured and must not run anything.
try {
  void window.top!.document;
  throw new Error("FAIL");
} catch (error) {
  if (error instanceof Error && error.message === "FAIL") {
    throw new Error("The sandbox can reach the host page; refusing to run");
  }
}

const inner = document.createElement("iframe");
inner.style.cssText = "width:100%;height:100%;border:none;";
inner.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
document.body.append(inner);

const RESOURCE_READY: McpUiSandboxResourceReadyNotification["method"] =
  "ui/notifications/sandbox-resource-ready";
const PROXY_READY: McpUiSandboxProxyReadyNotification["method"] =
  "ui/notifications/sandbox-proxy-ready";

window.addEventListener("message", (event) => {
  if (event.source === window.parent) {
    if (event.origin !== HOST_ORIGIN) return;
    if (event.data?.method === RESOURCE_READY) {
      const { html, sandbox, permissions } = event.data.params;
      if (typeof sandbox === "string") inner.setAttribute("sandbox", sandbox);
      const allow = buildAllowAttribute(permissions);
      if (allow) inner.setAttribute("allow", allow);
      if (typeof html === "string") {
        const doc = inner.contentDocument;
        if (doc) {
          doc.open();
          doc.write(html);
          doc.close();
        } else {
          inner.srcdoc = html;
        }
      }
      return;
    }
    inner.contentWindow?.postMessage(event.data, "*");
  } else if (event.source === inner.contentWindow) {
    if (event.origin !== OWN_ORIGIN) return;
    window.parent.postMessage(event.data, HOST_ORIGIN);
  }
});

window.parent.postMessage({ jsonrpc: "2.0", method: PROXY_READY, params: {} }, HOST_ORIGIN);
