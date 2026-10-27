import "server-only";
import { createHmac } from "node:crypto";
import type { AnalyticsResponse } from "@/api/client";
import { getAnalyticsConfig } from "@/lib/api";
import { APP_VERSION } from "@/lib/app-version";
import {
  PAGE_VIEW_IDENTITY_HEADER,
  PAGE_VIEW_PATH_HEADER,
  routePattern,
} from "./route-pattern";

const CONFIG_TTL_MS = 10 * 60 * 1000;
const FLUSH_INTERVAL_MS = 60 * 60 * 1000;
const FLUSH_SIZE = 500;
const SEND_TIMEOUT_MS = 10_000;
// A router.refresh(), a reload or a poll of the page someone is already on is
// the view counted when they opened it.
const REPEAT_WINDOW_MS = 30 * 60 * 1000;

// Router prefetches never resolve metadata, so never get here; Next hides its
// own router headers from headers(). What remains to skip: a server action
// re-rendering the page it was called from, and a browser-level prefetch.
const ACTION_HEADER = "next-action";
const PURPOSE_HEADERS = ["purpose", "sec-purpose"];

interface PageViewed {
  event: "page_viewed";
  occurred_at: string;
  user_id: string;
  properties: { route: string };
  context: {
    install_id: string;
    version: string;
    edition: string | null;
    surface: "webapp";
  };
}

let config: { value: AnalyticsResponse | null; at: number } | null = null;
let configLoad: Promise<AnalyticsResponse | null> | null = null;
let buffer: PageViewed[] = [];
const lastViews = new Map<string, { path: string; at: number }>();
let flushTimer: ReturnType<typeof setInterval> | null = null;

function loadConfig(): Promise<AnalyticsResponse | null> {
  if (config && Date.now() - config.at < CONFIG_TTL_MS) {
    return Promise.resolve(config.value);
  }
  configLoad ??= getAnalyticsConfig()
    .then(({ data, error, status }) => {
      if (!data) {
        console.error("[analytics] GET /v1/analytics failed:", status, error);
      }
      return data ?? null;
    })
    .catch((error: unknown) => {
      console.error("[analytics] GET /v1/analytics failed:", error);
      return null;
    })
    .then((value) => {
      config = { value, at: Date.now() };
      configLoad = null;
      return value;
    });
  return configLoad;
}

function pseudonymize(installId: string, identityId: string): string {
  return createHmac("sha256", installId)
    .update(identityId)
    .digest("hex")
    .slice(0, 16);
}

function isRepeat(userId: string, path: string, now: number): boolean {
  const last = lastViews.get(userId);
  lastViews.set(userId, { path, at: now });
  return last?.path === path && now - last.at < REPEAT_WINDOW_MS;
}

async function flush(): Promise<void> {
  const events = buffer;
  buffer = [];
  const now = Date.now();
  for (const [userId, view] of lastViews) {
    if (now - view.at >= REPEAT_WINDOW_MS) lastViews.delete(userId);
  }

  const current = config?.value;
  if (
    events.length === 0 ||
    !current?.enabled ||
    !current.collector_url
  ) {
    return;
  }
  try {
    const response = await fetch(`${current.collector_url}/v1/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(events),
      signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
    });
    if (!response.ok) {
      console.error(
        "[analytics] collector refused page views:",
        response.status
      );
    }
  } catch (error) {
    console.error("[analytics] sending page views failed:", error);
  }
}

function bufferView(
  current: AnalyticsResponse | null,
  identityId: string,
  path: string,
  route: string,
  occurredAt: Date
) {
  if (!current?.enabled || !current.install_id) return;
  const userId = pseudonymize(current.install_id, identityId);
  if (isRepeat(userId, path, occurredAt.getTime())) return;

  buffer.push({
    event: "page_viewed",
    occurred_at: occurredAt.toISOString(),
    user_id: userId,
    properties: { route },
    context: {
      install_id: current.install_id,
      version: APP_VERSION,
      edition: current.edition,
      surface: "webapp",
    },
  });
  if (!flushTimer) {
    flushTimer = setInterval(() => void flush(), FLUSH_INTERVAL_MS);
    flushTimer.unref();
  }
  if (buffer.length >= FLUSH_SIZE) void flush();
}

/**
 * Count the page this request renders for a signed-in person. Returns at
 * once: the config and the collector are reached off the request path, and a
 * failure is logged and dropped.
 */
export function recordPageView(headers: Headers): void {
  if (headers.has(ACTION_HEADER)) return;
  if (PURPOSE_HEADERS.some((name) => headers.get(name)?.includes("prefetch"))) {
    return;
  }
  const path = headers.get(PAGE_VIEW_PATH_HEADER);
  const identityId = headers.get(PAGE_VIEW_IDENTITY_HEADER);
  const route = path ? routePattern(path) : null;
  if (!path || !route || !identityId) return;

  const occurredAt = new Date();
  loadConfig()
    .then((current) => bufferView(current, identityId, path, route, occurredAt))
    .catch((error: unknown) => {
      console.error("[analytics] recording a page view failed:", error);
    });
}
