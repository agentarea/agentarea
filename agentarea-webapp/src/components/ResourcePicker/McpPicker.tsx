"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { resolveMcpRef, type McpInstance } from "@/lib/mcp/resolveMcpRef";
import { ResourcePicker } from "./ResourcePicker";

const McpIcon = ENTITY_ICONS.mcp;

/** Pick MCP servers to attach. Everywhere, this means configured instances.
 *
 * Name and icon come from `resolveMcpRef`, the same resolver the runtime's
 * lookup mirrors, so an entry reads identically here, on an agent and in the
 * connections list.
 */
export function McpPicker({
  title,
  description,
  resources,
  selectedIds,
  onAdd,
  onRemove,
}: {
  title: ReactNode;
  description: ReactNode;
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
      title={title}
      description={description}
      items={mcpInstances}
      selectedIds={selectedIds}
      onAdd={onAdd}
      onRemove={onRemove}
      loading={loading}
      failed={failed.includes("mcps")}
      onRefresh={refresh}
      iconsType="mcp"
      emptyTitle={t("emptyMcpsTitle")}
      emptyHint={t("emptyMcpsHint")}
      createText={t("manageMcps")}
      createHref="/connections"
      manageText={t("manageMcpsLink")}
      manageHref="/connections"
      heading={t("mcpsHeading")}
      extractTitle={(instance) => resolve(instance).displayName}
      extractSubtitle={(instance) => {
        const resolved = resolve(instance);
        return resolved.status === "instance" ? resolved.server?.name : null;
      }}
      extractIcon={() => <McpIcon strokeWidth={1.85} />}
      extractIconSrc={(instance) => {
        const resolved = resolve(instance);
        return resolved.status === "unresolved" ? null : resolved.iconSrc;
      }}
    />
  );
}
