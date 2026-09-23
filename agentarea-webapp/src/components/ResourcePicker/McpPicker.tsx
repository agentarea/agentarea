"use client";

import { useTranslations } from "next-intl";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { resolveMcpRef, type McpInstance } from "@/lib/mcp/resolveMcpRef";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { ResourcePicker } from "./ResourcePicker";

const McpIcon = ENTITY_ICONS.mcp;

/** Pick MCP servers to attach. Everywhere, this means configured instances.
 *
 * Name and icon come from `resolveMcpRef`, the same resolver the runtime's
 * lookup mirrors, so an entry reads identically here, on an agent and in the
 * connections list.
 */
export function McpPicker({
  resources,
  selectedIds,
  onAdd,
  onRemove,
}: {
  resources: AttachableResources;
  selectedIds: string[];
  onAdd: (instance: McpInstance) => void;
  onRemove: (instance: McpInstance) => void;
}) {
  const t = useTranslations("Pickers");
  const { mcpInstances, mcpServers, loading, failed, refresh } = resources;

  const resolve = (instance: McpInstance) =>
    resolveMcpRef(instance.id, mcpInstances, mcpServers);

  return (
    <ResourcePicker
      items={mcpInstances}
      prefix="mcp"
      selectedIds={selectedIds}
      onAdd={onAdd}
      onRemove={onRemove}
      loading={loading}
      failed={failed.includes("mcps")}
      onRefresh={refresh}
      emptyText={t("noMcps")}
      manageText={t("manageMcps")}
      manageHref="/connections"
      extractIconSrc={(instance) => {
        const resolved = resolve(instance);
        return resolved.status === "unresolved"
          ? "/Icon.svg"
          : (resolved.iconSrc ?? "/Icon.svg");
      }}
      extractTitle={(instance) => (
        <span className="flex items-center gap-2">
          <McpIcon className="h-4 w-4" />
          {resolve(instance).displayName}
        </span>
      )}
    />
  );
}
