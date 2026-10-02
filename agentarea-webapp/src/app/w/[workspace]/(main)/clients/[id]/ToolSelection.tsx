"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type {
  ClientMcpInstanceRef,
  ClientPlatformToolsetRef,
  PlatformToolsetResponse,
} from "@/api/client";
import FormError from "@/components/FormError";
import Note from "@/components/ui/note";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";
import {
  addMcpInstanceToClientAction,
  addPlatformToolsetToClientAction,
  listMcpInstanceToolsAction,
} from "@/lib/server-actions";
import {
  MethodsList,
  type Method,
} from "../../agents/create/components/MethodsList";

type SaveResult = { error?: unknown };

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
  onSaved: () => Promise<void>;
}) {
  const [selected, setSelected] = useState(() => new Set(enabled));
  const [error, setError] = useState<string | null>(null);

  const apply = async (next: Set<string>) => {
    const previous = selected;
    setSelected(next);
    setError(null);
    try {
      const result = await save(
        tools.map((t) => t.name).filter((n) => next.has(n))
      );
      if (result?.error) {
        setSelected(previous);
        setError(
          apiErrorMessage(
            result as ApiResultLike,
            "Couldn’t save the tool selection"
          )
        );
        return;
      }
    } catch (err) {
      console.error("Failed to save the harness tool selection", err);
      setSelected(previous);
      setError(`Couldn’t save the tool selection: ${formatApiError(err)}`);
      return;
    }
    await onSaved();
  };

  return (
    <div className="space-y-2">
      {error && <FormError>{error}</FormError>}
      <MethodsList
        toolName={id}
        label={`Served tools (${selected.size}/${tools.length})`}
        methods={tools}
        selectedMethods={Object.fromEntries(
          tools.map((t) => [t.name, selected.has(t.name)])
        )}
        onMethodToggle={(name, checked) => {
          const next = new Set(selected);
          if (checked) next.add(name);
          else next.delete(name);
          void apply(next);
        }}
        showSelectAll
        onSelectAll={(checked) =>
          void apply(new Set(checked ? tools.map((t) => t.name) : []))
        }
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
  onSaved: () => Promise<void>;
}) {
  if (!toolset) {
    return (
      <p className="text-xs text-muted-foreground">
        The platform no longer serves this toolset. Remove it from the harness.
      </p>
    );
  }
  const disabled = new Set(attachment.disabled_methods ?? []);
  return (
    <div className="space-y-2">
      {toolset.description && (
        <p className="text-xs text-muted-foreground">{toolset.description}</p>
      )}
      <ToolChecklist
        id={`platform-${toolset.name}`}
        tools={toolset.methods}
        enabled={toolset.methods
          .map((m) => m.name)
          .filter((n) => !disabled.has(n))}
        save={(enabled) => {
          const off = toolset.methods
            .map((m) => m.name)
            .filter((n) => !enabled.includes(n));
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
  onSaved,
}: {
  clientId: string;
  attachment: ClientMcpInstanceRef;
  onSaved: () => Promise<void>;
}) {
  const [tools, setTools] = useState<Method[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const result = await listMcpInstanceToolsAction(attachment.id);
        if (cancelled) return;
        if (result.error || !result.data) {
          setError(
            apiErrorMessage(result, "Couldn’t load the instance’s tools")
          );
          return;
        }
        setTools(
          result.data.map((tool) => ({
            name: tool.name,
            description: tool.description,
          }))
        );
      } catch (err) {
        console.error("Failed to load MCP instance tools", err);
        if (!cancelled) {
          setError(
            `Couldn’t load the instance’s tools: ${formatApiError(err)}`
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attachment.id]);

  if (error) return <FormError>{error}</FormError>;
  if (!tools) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }
  if (tools.length === 0) {
    return (
      <Note>
        <p>
          This instance has not reported any tools yet, so the harness serves
          whatever it exposes.
        </p>
      </Note>
    );
  }
  const names = tools.map((t) => t.name);
  return (
    <ToolChecklist
      id={`mcp-${attachment.id}`}
      tools={tools}
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
  );
}
