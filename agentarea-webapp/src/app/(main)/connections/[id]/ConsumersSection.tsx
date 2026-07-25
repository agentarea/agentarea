"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getMCPInstanceConsumers, type MCPInstanceConsumer } from "@/lib/api";

// Reverse lookup: which agents attach this MCP instance, and which of its tools
// each one enabled. Read-only — the enabled subset is owned by each agent's tool
// config, this just surfaces it in one MCP-centric place.
export function ConsumersSection({ instanceId }: { instanceId: string }) {
  const [consumers, setConsumers] = useState<MCPInstanceConsumer[] | null>(null);

  useEffect(() => {
    let active = true;
    getMCPInstanceConsumers(instanceId).then((data) => {
      if (active) setConsumers(data);
    });
    return () => {
      active = false;
    };
  }, [instanceId]);

  if (consumers === null) {
    return (
      <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
        Loading consumers…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium">Used by ({consumers.length})</h3>
      </div>

      {consumers.length === 0 ? (
        <div className="rounded-lg border border-border/60 bg-background p-4 text-sm text-muted-foreground dark:bg-zinc-900/30">
          No agents attach this MCP server yet.
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <div className="grid grid-cols-[minmax(160px,220px)_1fr] gap-3 bg-muted/40 px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <span>Agent</span>
            <span>Enabled tools</span>
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
                {c.enabled_tools == null ? (
                  <Badge variant="slate" size="sm">
                    all tools
                  </Badge>
                ) : c.enabled_tools.length === 0 ? (
                  <span className="text-xs italic text-muted-foreground">none</span>
                ) : (
                  c.enabled_tools.map((tool) => {
                    const needsConfirm = c.confirm_tools?.includes(tool) ?? false;
                    return (
                      <Badge
                        key={tool}
                        variant={needsConfirm ? "amber" : "success"}
                        size="sm"
                      >
                        {tool}
                        {needsConfirm ? " (confirm)" : ""}
                      </Badge>
                    );
                  })
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
