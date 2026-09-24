import {
  AppBridge,
  buildAllowAttribute,
  getToolUiResourceUri,
  isToolVisibilityModelOnly,
  PostMessageTransport,
  RESOURCE_MIME_TYPE,
  type McpUiResourceCsp,
  type McpUiResourcePermissions,
  type McpUiSandboxProxyReadyNotification,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import {
  Client,
  StreamableHTTPClientTransport,
  type Tool,
} from "@modelcontextprotocol/client";
import {
  applyDocumentTheme,
  applyHostStyleVariables,
  type McpUiTheme,
} from "@modelcontextprotocol/ext-apps";
import { AGENTAREA_STYLE_VARIABLES } from "./host-styles.ts";

type HostConfig = { mcpUrl: string; sandboxUrl: string; entryTool: string };
type View = { html: string; csp?: McpUiResourceCsp; permissions?: McpUiResourcePermissions };

const HOST_INFO = { name: "AgentArea MCP Apps test host", version: "0.1.0" };

const titleEl = document.getElementById("app-title")!;
const sourceEl = document.getElementById("app-source")!;
const statusEl = document.getElementById("status")!;
const slotEl = document.getElementById("app-slot")!;
const logEl = document.getElementById("log")!;
const logCountEl = document.getElementById("log-count")!;
const themeButtons = document.querySelectorAll<HTMLButtonElement>("[data-theme-choice]");

let theme: McpUiTheme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
// Set once the view has initialized; theme changes before that ride in the
// initial host context instead.
let runningBridge: AppBridge | undefined;

function setTheme(next: McpUiTheme) {
  theme = next;
  applyDocumentTheme(next);
  for (const button of themeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === next));
  }
  if (runningBridge) {
    Promise.resolve(runningBridge.sendHostContextChange({ theme: next })).catch(console.error);
  }
}

applyHostStyleVariables(AGENTAREA_STYLE_VARIABLES);
setTheme(theme);
for (const button of themeButtons) {
  button.addEventListener("click", () => setTheme(button.dataset.themeChoice as McpUiTheme));
}

function setState(state: "connecting" | "running" | "failed", label: string) {
  statusEl.dataset.state = state;
  statusEl.textContent = label;
}

function log(kind: string, message: string, detail?: unknown) {
  const item = document.createElement("li");
  const kindEl = document.createElement("span");
  kindEl.className = "kind";
  kindEl.textContent = kind;
  if (kind.startsWith("app")) kindEl.dataset.flow = "app";
  const messageEl = document.createElement("span");
  messageEl.textContent = message;
  item.append(kindEl, messageEl);
  if (detail !== undefined) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "payload";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(detail, null, 2);
    details.append(summary, pre);
    item.append(details);
  }
  logEl.append(item);
  logCountEl.textContent = String(logEl.childElementCount);
}

async function readView(client: Client, uri: string): Promise<View> {
  const { contents } = await client.readResource({ uri });
  if (contents.length !== 1) {
    throw new Error(`${uri}: expected one content item, got ${contents.length}`);
  }
  const [content] = contents;
  if (content.mimeType !== RESOURCE_MIME_TYPE) {
    throw new Error(`${uri}: unsupported MIME type ${content.mimeType}`);
  }
  const html = "text" in content ? content.text : atob(content.blob);
  const ui = (content._meta as { ui?: { csp?: McpUiResourceCsp; permissions?: McpUiResourcePermissions } } | undefined)?.ui;
  return { html, csp: ui?.csp, permissions: ui?.permissions };
}

/**
 * Load the sandbox proxy: a page on a separate origin whose inner frame will
 * run the view. The host page and the app never share an origin.
 */
function loadSandboxProxy(iframe: HTMLIFrameElement, sandboxUrl: string, view: View): Promise<void> {
  iframe.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
  const allow = buildAllowAttribute(view.permissions);
  if (allow) iframe.setAttribute("allow", allow);

  const ready: McpUiSandboxProxyReadyNotification["method"] = "ui/notifications/sandbox-proxy-ready";
  const loaded = new Promise<void>((resolve) => {
    const listener = ({ source, data }: MessageEvent) => {
      if (source === iframe.contentWindow && data?.method === ready) {
        window.removeEventListener("message", listener);
        resolve();
      }
    };
    window.addEventListener("message", listener);
  });

  const url = new URL(sandboxUrl);
  if (view.csp) url.searchParams.set("csp", JSON.stringify(view.csp));
  iframe.src = url.href;
  return loaded;
}

async function main() {
  const config: HostConfig = await (await fetch("/config.json")).json();
  // `?tool=show_lead_card&contact_id=ct_042` picks another entry tool and its
  // arguments, the same shape AgentArea's `agentarea-app://` links carry.
  const query = new URLSearchParams(location.search);
  const ENTRY_TOOL = query.get("tool") ?? config.entryTool;
  query.delete("tool");

  const client = new Client(HOST_INFO, { versionNegotiation: { mode: "auto" } });
  await client.connect(new StreamableHTTPClientTransport(new URL(config.mcpUrl)));
  const serverName = client.getServerVersion()?.name ?? config.mcpUrl;
  const { tools } = await client.listTools();
  const toolsByName = new Map<string, Tool>(tools.map((tool) => [tool.name, tool]));
  log("host", `connected to ${serverName}`, tools.map((tool) => tool.name));
  titleEl.textContent = serverName;

  const entryTool = toolsByName.get(ENTRY_TOOL);
  const viewUri = entryTool && getToolUiResourceUri(entryTool);
  if (!viewUri) {
    throw new Error(`${serverName} has no ${ENTRY_TOOL} tool with a UI resource`);
  }

  // Start the tool call and the view fetch together, as a chat host would:
  // the view renders while the result is still on its way.
  const input: Record<string, string> = Object.fromEntries(query);
  log("host → server", `tools/call ${ENTRY_TOOL}`, input);
  const resultPromise = client.callTool({ name: ENTRY_TOOL, arguments: input });
  const view = await readView(client, viewUri);
  log("host", `read ${viewUri} (${view.html.length} bytes of HTML, no data inside)`);
  const sandboxOrigin = new URL(config.sandboxUrl).origin;
  sourceEl.textContent = `${viewUri} · sandboxed at ${sandboxOrigin}`;

  const iframe = document.createElement("iframe");
  iframe.title = "MCP App";
  slotEl.replaceChildren(iframe);
  await loadSandboxProxy(iframe, config.sandboxUrl, view);

  // No client is handed to the bridge, so nothing is forwarded implicitly: the
  // host decides what the view may call and sees every call it makes.
  const bridge = new AppBridge(
    null,
    HOST_INFO,
    { serverTools: client.getServerCapabilities()?.tools, openLinks: {} },
    {
      hostContext: {
        theme,
        styles: { variables: AGENTAREA_STYLE_VARIABLES },
        platform: "web",
        displayMode: "inline",
        availableDisplayModes: ["inline"],
        containerDimensions: { maxWidth: 1600 },
      },
    },
  );
  bridge.oncalltool = async (params, extra) => {
    const tool = toolsByName.get(params.name);
    if (!tool || isToolVisibilityModelOnly(tool)) {
      log("host", `refused ${params.name}: not callable from the app`);
      throw new Error(`Tool ${params.name} is not available to this app`);
    }
    log("app → server", `tools/call ${params.name}`, params.arguments);
    const result = await client.callTool(params, { signal: extra.mcpReq.signal });
    log("server → app", result.isError ? "error" : "result", result.structuredContent ?? result.content);
    return result;
  };
  bridge.onsizechange = ({ height }) => {
    if (height !== undefined) iframe.style.height = `${height}px`;
  };
  // Mirrors AgentArea: `agentarea-app://<tool>?<args>` opens another view of
  // this connection (here in a new tab); other links open normally.
  bridge.onopenlink = async ({ url }) => {
    const target = new URL(url);
    if (target.protocol === "agentarea-app:") {
      const next = new URLSearchParams(target.search);
      next.set("tool", target.hostname);
      log("app → host", `open view ${url}`);
      window.open(`/?${next}`, "_blank");
      return {};
    }
    if (target.protocol !== "http:" && target.protocol !== "https:") return { isError: true };
    window.open(target.href, "_blank", "noopener,noreferrer");
    return {};
  };
  bridge.onloggingmessage = (params) => log("app log", String(params.data));
  const initialized = new Promise<void>((resolve) => {
    bridge.oninitialized = () => resolve();
  });

  await bridge.connect(new PostMessageTransport(iframe.contentWindow!, iframe.contentWindow!));

  await bridge.sendSandboxResourceReady({ html: view.html, csp: view.csp, permissions: view.permissions });
  await initialized;
  runningBridge = bridge;
  // The user may have switched theme while the view was loading.
  await bridge.sendHostContextChange({ theme });
  setState("running", "Running");
  await bridge.sendToolInput({ arguments: input });

  try {
    const result = await resultPromise;
    log("server → host", `${ENTRY_TOOL} result`, result.structuredContent ?? result.content);
    await bridge.sendToolResult(result);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    log("host", `${ENTRY_TOOL} failed: ${reason}`);
    await bridge.sendToolCancelled({ reason });
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  setState("failed", "Failed");
  sourceEl.textContent = message;
  console.error(error);
});
