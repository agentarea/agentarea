"use client";

import { useState } from "react";
import Link from "@/components/WorkspaceLink";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { MCPInstanceConsumer } from "@/lib/api";

// How many tool badges a row shows before collapsing. A connection granted with
// `all tools` is one badge, but an explicit grant can carry hundreds — those
// must not paint as hundreds of badges.
const VISIBLE_TOOL_BADGES = 12;

function ConsumerTools({ consumer }: { consumer: MCPInstanceConsumer }) {
  const t = useTranslations("MCPServersPage.instanceDetail.consumers");
  const [expanded, setExpanded] = useState(false);

  if (consumer.enabled_tools == null) {
    return (
      <Badge variant="slate" size="sm">
        {t("allTools")}
      </Badge>
    );
  }

  if (consumer.enabled_tools.length === 0) {
    return <span className="text-xs italic text-muted-foreground">{t("none")}</span>;
  }

  const hidden = consumer.enabled_tools.length - VISIBLE_TOOL_BADGES;
  const visible =
    expanded || hidden <= 0
      ? consumer.enabled_tools
      : consumer.enabled_tools.slice(0, VISIBLE_TOOL_BADGES);

  return (
    <>
      {visible.map((tool) => {
        const needsConfirm = consumer.confirm_tools?.includes(tool) ?? false;
        return (
          <Badge key={tool} variant={needsConfirm ? "amber" : "success"} size="sm">
            {tool}
            {needsConfirm ? t("confirmSuffix") : ""}
          </Badge>
        );
      })}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-[11px] text-muted-foreground underline-offset-2 hover:underline"
        >
          {expanded ? t("collapse") : t("more", { count: hidden })}
        </button>
      )}
    </>
  );
}

// Reverse lookup: which agents attach this MCP instance, and which of its tools
// each one enabled. Read-only — the enabled subset is owned by each agent's tool
// config, this just surfaces it in one MCP-centric place. Consumers are fetched
// once by the parent and shared with the tools table, which resolves the same
// data per tool.
export function ConsumersSection({
  consumers,
}: {
  /** `null` while the parent is still loading. */
  consumers: MCPInstanceConsumer[] | null;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.consumers");

  if (consumers === null) {
    return (
      <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
        {t("loading")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium">
          {t("title", { count: consumers.length })}
        </h3>
      </div>

      {consumers.length === 0 ? (
        <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
          {t("empty")}
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <div className="grid grid-cols-[minmax(160px,220px)_1fr] gap-3 bg-muted/40 px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <span>{t("columns.agent")}</span>
            <span>{t("columns.tools")}</span>
          </div>
          {consumers.map((c) => (
            <div
              key={c.agent_id}
              className="grid grid-cols-[minmax(160px,220px)_1fr] items-start gap-3 border-t px-3 py-2 first:border-t-0"
            >
              <div className="min-w-0 pt-0.5">
                <Link
                  href={`/agents/${c.agent_slug ?? c.agent_id}`}
                  className="text-sm font-medium hover:underline break-words"
                >
                  {c.agent_name}
                </Link>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <ConsumerTools consumer={c} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
