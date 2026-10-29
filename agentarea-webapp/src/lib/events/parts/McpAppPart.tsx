"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import McpAppFrame from "@/components/McpAppFrame/McpAppFrame";
import {
  chatMcpApp,
  type ChatMcpApp,
  type ChatMcpAppResource,
} from "@/lib/apps/mcp/chat";
import { currentWorkspaceHeaders } from "@/lib/workspace-browser";
import type { Part } from "../contract";

type View =
  | { phase: "loading" }
  | { phase: "ready"; app: ChatMcpAppResource }
  | { phase: "failed"; error: string };

async function readAppResource(app: ChatMcpApp): Promise<View> {
  try {
    const response = await fetch(
      `/api/mcp-apps/${encodeURIComponent(app.instanceId)}/${encodeURIComponent(app.toolName)}`,
      { headers: currentWorkspaceHeaders(), cache: "no-store" }
    );
    if (response.ok) {
      return {
        phase: "ready",
        app: (await response.json()) as ChatMcpAppResource,
      };
    }
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    return {
      phase: "failed",
      error: body?.detail ?? `HTTP ${response.status}`,
    };
  } catch (error) {
    return {
      phase: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function ChatMcpAppView({ app }: { app: ChatMcpApp }) {
  const t = useTranslations("AppsPage");
  const [view, setView] = useState<View>({ phase: "loading" });

  useEffect(() => {
    let current = true;
    void readAppResource(app).then((next) => {
      if (current) setView(next);
    });
    return () => {
      current = false;
    };
  }, [app]);

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border">
      {view.phase === "ready" && (
        <div className="border-b border-border/70 bg-muted/20 px-3 py-1.5 text-[13px] font-medium text-foreground/80">
          {view.app.title}
        </div>
      )}
      {view.phase === "loading" && (
        <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
          {t("loading")}
        </div>
      )}
      {view.phase === "failed" && (
        <div role="alert" className="p-3 text-sm text-destructive">
          <p className="font-medium">{t("resourceError")}</p>
          <p className="mt-1 break-words text-muted-foreground">{view.error}</p>
        </div>
      )}
      {view.phase === "ready" && (
        <McpAppFrame
          instanceId={app.instanceId}
          toolName={app.toolName}
          title={view.app.title}
          resource={view.app.resource}
          entryArguments={app.arguments}
          toolResult={app.result}
          displayMode="inline"
        />
      )}
    </div>
  );
}

/**
 * The MCP App a tool result opens, shown over the agent's own call. The part
 * is rebuilt on every stream update, so the app is keyed by its content: the
 * frame restarts only when the call it shows changes.
 */
export const McpAppPart: React.FC<{ part: Part }> = ({ part }) => {
  const app = chatMcpApp(part);
  const identity = app ? JSON.stringify(app) : null;
  const stable = useMemo(
    () => (identity ? (JSON.parse(identity) as ChatMcpApp) : null),
    [identity]
  );
  return stable ? <ChatMcpAppView app={stable} /> : null;
};

export default McpAppPart;
