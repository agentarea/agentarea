"use client";

import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import type { McpServerResponse } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import {
  PICKER_BARE_EMPTY_STATE,
  PickerRow,
} from "@/components/ResourcePicker/PickerRow";
import { ResourcePickerList } from "@/components/ResourcePicker/ResourcePicker";
import { MenuSectionLabel } from "@/components/ui/menu-row";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import type { McpInstance } from "@/lib/mcp/resolveMcpRef";

const McpIcon = ENTITY_ICONS.mcp;

/** A server's logo on the row tile, or the MCP glyph when it has none. */
function mcpTile(src: string | null | undefined) {
  return {
    iconScale: src ? 0.62 : 0.45,
    icon: src ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt="" className="h-full w-full object-contain" />
    ) : (
      <McpIcon strokeWidth={1.85} />
    ),
  };
}

/**
 * The MCP tab of the agent's tools sheet: the workspace's connected servers to
 * tick, then the catalog, where a server is configured before it can be
 * attached — so its row opens the setup instead of ticking.
 */
export function McpToolsTab({
  query,
  instances,
  servers,
  selectedIds,
  onAdd,
  onRemove,
  onConfigure,
  instanceIconSrc,
  instanceSubtitle,
  serverIconSrc,
}: {
  query: string;
  instances: McpInstance[];
  servers: McpServerResponse[];
  selectedIds: string[];
  onAdd: (instance: McpInstance) => void;
  onRemove: (instance: McpInstance) => void;
  onConfigure: (server: McpServerResponse) => void;
  instanceIconSrc: (instance: McpInstance) => string | undefined;
  instanceSubtitle: (instance: McpInstance) => string | null;
  serverIconSrc: (server: McpServerResponse) => string | undefined;
}) {
  const t = useTranslations("AgentsPage.create");
  const needle = query.trim().toLowerCase();
  const catalog = needle
    ? servers.filter((server) =>
        [server.name, server.description].some((text) =>
          text?.toLowerCase().includes(needle)
        )
      )
    : servers;

  if (!instances.length && !servers.length) {
    return (
      <div className="flex h-full flex-col justify-center">
        <EmptyState
          iconsType="mcp"
          className={PICKER_BARE_EMPTY_STATE}
          title={t("noMcpServers")}
          description={t("noAvailableMcpServersDescription")}
        />
      </div>
    );
  }

  return (
    <>
      {instances.length > 0 && (
        <ResourcePickerList
          query={query}
          heading={t("activeMcpServers")}
          items={instances}
          selectedIds={selectedIds}
          onAdd={onAdd}
          onRemove={onRemove}
          extractTitle={(instance) => instance.name || instance.id}
          extractSubtitle={instanceSubtitle}
          extractIcon={() => <McpIcon strokeWidth={1.85} />}
          extractIconSrc={instanceIconSrc}
          loading={false}
          failed={false}
          onRefresh={() => undefined}
          emptyTitle={t("noMcpServers")}
          inline
        />
      )}
      {catalog.length > 0 && (
        <div className={instances.length ? "mt-3" : undefined}>
          <div className="px-3">
            <MenuSectionLabel>
              {t("availableMcpServers")} ({catalog.length})
            </MenuSectionLabel>
          </div>
          {catalog.map((server) => (
            <PickerRow
              key={server.id}
              {...mcpTile(serverIconSrc(server))}
              title={server.name}
              subtitle={server.description}
              selected={false}
              onToggle={() => onConfigure(server)}
              end={
                <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground group-hover:text-foreground">
                  {t("configureMcp")}
                  <ArrowRight className="h-3 w-3" />
                </span>
              }
            />
          ))}
        </div>
      )}
    </>
  );
}
