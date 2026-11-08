"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type {
  ClientMcpInstanceRef,
  ClientPlatformToolsetRef,
  PlatformToolsetResponse,
} from "@/api/client";
import FormError from "@/components/FormError";
import { EmptyRow } from "@/components/Overview/OverviewCard";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";
import {
  addMcpInstanceToClientAction,
  addPlatformToolsetToClientAction,
} from "@/lib/server-actions";
import {
  MethodsList,
  type Method,
} from "../../agents/create/components/MethodsList";

type SaveResult = { error?: unknown };

/** An attached MCP instance's reported tools, or why they could not be read. */
export type McpToolsResult = { tools: Method[] } | { error: string };

/**
 * Checkboxes over a harness attachment's tools. A toggle saves at once; the
 * box flips before the write lands and flips back, with the error, if it fails.
 */
function ToolChecklist({
  id,
  tools,
  enabled,
  save,
  onSaved,
}: {
  id: string;
  tools: Method[];
  enabled: string[];
  save: (enabled: string[]) => Promise<SaveResult>;
  onSaved: () => void;
}) {
  const t = useTranslations("ClientsPage.tools");
  const [selected, setSelected] = useState(() => new Set(enabled));
  const [error, setError] = useState<string | null>(null);

  const apply = async (next: Set<string>) => {
    const previous = selected;
    setSelected(next);
    setError(null);
    try {
      const result = await save(
        tools.map((tool) => tool.name).filter((name) => next.has(name))
      );
      if (result?.error) {
        setSelected(previous);
        setError(apiErrorMessage(result as ApiResultLike, t("saveFailed")));
        return;
      }
    } catch (err) {
      console.error("Failed to save the harness tool selection", err);
      setSelected(previous);
      setError(`${t("saveFailed")}: ${formatApiError(err)}`);
      return;
    }
    onSaved();
  };

  return (
    <div className="space-y-2">
      {error && <FormError>{error}</FormError>}
      <MethodsList
        toolName={id}
        label={t("served", { selected: selected.size, total: tools.length })}
        methods={tools}
        selectedMethods={Object.fromEntries(
          tools.map((tool) => [tool.name, selected.has(tool.name)])
        )}
        onMethodToggle={(name, checked) => {
          const next = new Set(selected);
          if (checked) next.add(name);
          else next.delete(name);
          void apply(next);
        }}
        showSelectAll
        onSelectAll={(checked) =>
          void apply(new Set(checked ? tools.map((tool) => tool.name) : []))
        }
        wide
      />
    </div>
  );
}

/** The methods of an attached platform toolset the harness serves. */
export function PlatformToolsetMethods({
  clientId,
  attachment,
  toolset,
  onSaved,
}: {
  clientId: string;
  attachment: ClientPlatformToolsetRef;
  toolset: PlatformToolsetResponse | undefined;
  onSaved: () => void;
}) {
  const t = useTranslations("ClientsPage.tools");
  if (!toolset) {
    return <EmptyRow text={t("toolsetGone")} />;
  }
  const disabled = new Set(attachment.disabled_methods ?? []);
  return (
    <div className="space-y-2 px-[15px] py-3">
      {toolset.description && <p className="note">{toolset.description}</p>}
      <ToolChecklist
        id={`platform-${toolset.name}`}
        tools={toolset.methods}
        enabled={toolset.methods
          .map((method) => method.name)
          .filter((name) => !disabled.has(name))}
        save={(enabled) => {
          const off = toolset.methods
            .map((method) => method.name)
            .filter((name) => !enabled.includes(name));
          return addPlatformToolsetToClientAction(
            clientId,
            toolset.name,
            off.length > 0 ? off : null
          );
        }}
        onSaved={onSaved}
      />
    </div>
  );
}

/** The tools of an attached MCP instance the harness serves. */
export function McpInstanceTools({
  clientId,
  attachment,
  result,
  onSaved,
}: {
  clientId: string;
  attachment: ClientMcpInstanceRef;
  result: McpToolsResult | undefined;
  onSaved: () => void;
}) {
  const t = useTranslations("ClientsPage.tools");
  if (!result || "error" in result) {
    return (
      <div className="px-[15px] py-3">
        <FormError>{result?.error ?? t("mcpToolsFailed")}</FormError>
      </div>
    );
  }
  if (result.tools.length === 0) {
    return <EmptyRow text={t("mcpNoTools")} />;
  }
  const names = result.tools.map((tool) => tool.name);
  return (
    <div className="px-[15px] py-3">
      <ToolChecklist
        id={`mcp-${attachment.id}`}
        tools={result.tools}
        enabled={attachment.allowed_tools ?? names}
        save={(enabled) =>
          addMcpInstanceToClientAction(
            clientId,
            attachment.id,
            attachment.namespace_prefix,
            enabled.length === names.length ? null : enabled
          )
        }
        onSaved={onSaved}
      />
    </div>
  );
}
