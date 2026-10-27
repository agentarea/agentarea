"use client";

import { useTranslations } from "next-intl";
import { Switch } from "@/components/ui/switch";
import type { McpAvailableTool } from "@/lib/mcp/resolveMcpRef";
import type { MCPToolConfig } from "../types";
import { MethodsList } from "./MethodsList";

export type McpToolState = "disabled" | "enabled" | "approval_required";

/** How many of an MCP's tools the agent gets; null allowed means all of them. */
export function enabledMcpToolCount(
  tools: McpAvailableTool[],
  allowed: MCPToolConfig[] | null
) {
  if (allowed === null) return tools.length;
  return tools.filter((tool) =>
    allowed.some((config) => config.tool_name === tool.name)
  ).length;
}

/**
 * What an attached MCP server lets the agent call: every tool including later
 * ones, or a ticked list, each tool either run on its own or held for approval.
 */
export function McpToolSettings({
  id,
  tools,
  allowed,
  onAllToolsChange,
  onToolStateChange,
}: {
  id: string;
  tools: McpAvailableTool[];
  /** null: every tool, including ones the server adds later. */
  allowed: MCPToolConfig[] | null;
  onAllToolsChange: (all: boolean) => void;
  onToolStateChange: (toolName: string, state: McpToolState) => void;
}) {
  const t = useTranslations("AgentsPage");
  const tMethods = useTranslations("MethodsList");

  const enabled = (name: string) =>
    allowed === null || allowed.some((config) => config.tool_name === name);
  const approval = (name: string) =>
    allowed?.find((config) => config.tool_name === name)
      ?.requires_user_confirmation ?? false;

  return (
    <>
      <div className="flex items-center gap-2">
        <Switch
          id={`${id}-all-tools`}
          size="xs"
          checked={allowed === null}
          onCheckedChange={onAllToolsChange}
        />
        <label
          htmlFor={`${id}-all-tools`}
          className="cursor-pointer text-xs text-foreground"
        >
          {t("create.allToolsIncludingNew")}
        </label>
      </div>
      {tools.length > 0 && (
        <MethodsList
          methods={tools}
          selectedMethods={Object.fromEntries(
            tools.map((tool) => [tool.name, enabled(tool.name)])
          )}
          onMethodToggle={(name, checked) =>
            onToolStateChange(name, checked ? "enabled" : "disabled")
          }
          toolName={id}
          showSelectAll
          onSelectAll={(checked) =>
            tools.forEach((tool) =>
              onToolStateChange(tool.name, checked ? "enabled" : "disabled")
            )
          }
          approvalStates={Object.fromEntries(
            tools.map((tool) => [tool.name, approval(tool.name)])
          )}
          onApprovalToggle={(name, requiresApproval) =>
            onToolStateChange(
              name,
              requiresApproval ? "approval_required" : "enabled"
            )
          }
          label={tMethods("availableTools", {
            enabled: enabledMcpToolCount(tools, allowed),
            total: tools.length,
          })}
        />
      )}
    </>
  );
}
