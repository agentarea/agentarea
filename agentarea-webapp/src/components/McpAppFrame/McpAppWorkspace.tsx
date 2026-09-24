"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import {
  openMcpAppLinkAction,
  type OpenedMcpApp,
} from "@/app/(main)/apps/actions";
import { Button } from "@/components/ui/button";
import type { McpAppLink } from "@/lib/mcp-apps/links";
import type { McpAppUiResource } from "@/lib/mcp-apps/tools";
import McpAppFrame from "./McpAppFrame";

type McpAppWorkspaceProps = {
  instanceId: string;
  toolName: string;
  title: string;
  resource: McpAppUiResource;
};

type SidePanel =
  | { state: "opening"; toolName: string }
  | { state: "open"; app: OpenedMcpApp; key: number }
  | { state: "failed"; toolName: string; error: string };

// Stable identity: a fresh `{}` on every render would restart the main app.
const NO_ARGUMENTS: Record<string, unknown> = {};

/**
 * One app, plus a side panel for the other UIs of the same connection that it
 * opens through app links. A new link replaces the panel's UI.
 */
export default function McpAppWorkspace({
  instanceId,
  toolName,
  title,
  resource,
}: McpAppWorkspaceProps) {
  const t = useTranslations("AppsPage");
  const [panel, setPanel] = useState<SidePanel | null>(null);

  const openApp = useCallback(
    async (link: McpAppLink) => {
      setPanel({ state: "opening", toolName: link.toolName });
      const opened = await openMcpAppLinkAction(
        instanceId,
        link.toolName,
        link.params
      ).catch((error: unknown) => ({
        ok: false as const,
        error: error instanceof Error ? error.message : String(error),
      }));
      setPanel(
        opened.ok
          ? { state: "open", app: opened.app, key: Date.now() }
          : { state: "failed", toolName: link.toolName, error: opened.error }
      );
    },
    [instanceId]
  );

  const panelTitle =
    panel === null
      ? ""
      : panel.state === "open"
        ? panel.app.title
        : panel.toolName;

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <McpAppFrame
          instanceId={instanceId}
          toolName={toolName}
          title={title}
          resource={resource}
          entryArguments={NO_ARGUMENTS}
          onOpenApp={openApp}
        />
      </div>
      {panel && (
        <aside
          aria-label={panelTitle}
          className="flex min-h-0 w-[42%] min-w-[360px] max-w-[720px] flex-col border-l border-border/70"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/70 bg-muted/20 px-4 py-2">
            <h2 className="truncate text-sm font-semibold">{panelTitle}</h2>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              aria-label={t("closePanel")}
              onClick={() => setPanel(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          {panel.state === "opening" && (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              {t("loading")}
            </div>
          )}
          {panel.state === "failed" && (
            <div className="flex flex-1 items-center justify-center p-6">
              <div
                role="alert"
                className="max-w-sm rounded-lg border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive"
              >
                <p className="font-medium">{t("openAppError")}</p>
                <p className="mt-2 break-words">{panel.error}</p>
              </div>
            </div>
          )}
          {panel.state === "open" && (
            <McpAppFrame
              key={panel.key}
              instanceId={instanceId}
              toolName={panel.app.toolName}
              title={panel.app.title}
              resource={panel.app.resource}
              entryArguments={panel.app.arguments}
              onOpenApp={openApp}
            />
          )}
        </aside>
      )}
    </div>
  );
}
