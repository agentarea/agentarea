"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { Check, Clock, Copy, Hash, Link as LinkIcon } from "lucide-react";
import { toast } from "sonner";
import {
  InfoPanelBody,
  InfoPanelField,
  InfoPanelHeader,
  InfoPanelSection,
  InfoPanelShell,
  InfoPanelValueBox,
} from "@/components/InfoPanel";
import { AgentAvatar } from "@/components/AgentAvatar";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { renderTriggerIcon } from "../components/triggerDisplay";

interface TriggerDetailProps {
  trigger: any;
  agentName: string;
  catalogEntry: any | null;
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(`${label || "Value"} copied`);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy");
    }
  };

  return (
    <Button variant="outline" size="xs" onClick={handleCopy}>
      {copied ? (
        <Check className="h-4 w-4 text-green-500" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );
}

function TriggerInfoPanel({
  trigger,
  catalogEntry,
  agentName,
}: {
  trigger: any;
  catalogEntry: any | null;
  agentName: string;
}) {
  const isActive = trigger.is_active;
  const statusVariant = isActive ? "success" : "secondary";
  const statusLabel = isActive ? "Active" : "Inactive";

  const displayName =
    catalogEntry?.name ??
    (trigger.trigger_type === "cron" ? "Cron" : "Webhook");

  return (
    <InfoPanelShell>
      <InfoPanelHeader
        label="Trigger"
        title={trigger.name}
        right={
          <Badge variant={statusVariant as any} size="sm">
            {statusLabel}
          </Badge>
        }
      />
      <InfoPanelBody>
        <InfoPanelSection title="Details" contentClassName="space-y-3 text-xs">
          <div className="space-y-1">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Type
            </div>
            <div className="text-sm font-semibold text-foreground">
              <span className="inline-flex items-center gap-1.5">
                {renderTriggerIcon(catalogEntry, trigger, "h-3.5 w-3.5")}
                {displayName}
              </span>
            </div>
          </div>

          <div className="space-y-1">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Agent
            </div>
            <div className="flex items-center gap-1.5 text-sm text-foreground">
              <AgentAvatar agent={{ id: trigger.agent_id || agentName, name: agentName }} size="xs" />
              {agentName}
            </div>
          </div>

          <InfoPanelField label="ID" icon={Hash}>
            <InfoPanelValueBox mono className="break-all">
              {trigger.id}
            </InfoPanelValueBox>
          </InfoPanelField>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Clock className="h-3 w-3 text-primary" />
                Created
              </div>
              <div className="text-[13px] font-medium text-foreground">
                {new Date(trigger.created_at).toLocaleString()}
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Clock className="h-3 w-3 text-muted-foreground" />
                Updated
              </div>
              <div className="text-[13px] font-medium text-foreground">
                {new Date(trigger.updated_at).toLocaleString()}
              </div>
            </div>
          </div>
        </InfoPanelSection>

        {catalogEntry?.description && (
          <InfoPanelSection title="About" contentClassName="text-xs">
            <p className="text-sm text-muted-foreground">
              {catalogEntry.description}
            </p>
          </InfoPanelSection>
        )}
      </InfoPanelBody>
    </InfoPanelShell>
  );
}

export default function TriggerDetail({
  trigger,
  agentName,
  catalogEntry,
}: TriggerDetailProps) {
  const isCron = trigger.trigger_type === "cron";
  const webhookUrl = trigger.webhook_url as string | undefined;

  const displayName = catalogEntry?.name ?? (isCron ? "Cron" : "Webhook");
  const description = catalogEntry?.description ?? null;

  return (
    <div className="flex h-full w-full">
      <div className="flex-1">
        <div className="relative h-full overflow-auto px-4 py-5">
          <div className="mx-auto w-full max-w-5xl space-y-6">
            {/* Catalog info card — similar to MCP spec info */}
            <div className="rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40 space-y-2">
              <div className="flex items-center gap-3">
                {renderTriggerIcon(
                  catalogEntry,
                  trigger,
                  "h-8 w-8 text-primary"
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium text-sm">{displayName}</div>
                    <Badge
                      variant={trigger.is_active ? "success" : "secondary"}
                      size="sm"
                    >
                      {trigger.is_active ? "Active" : "Inactive"}
                    </Badge>
                    {catalogEntry?.kind && (
                      <Badge variant="outline" size="sm" className="capitalize">
                        {catalogEntry.kind}
                      </Badge>
                    )}
                  </div>
                  {description && (
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {description}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Webhook URL — prominent section for webhook triggers */}
            {!isCron && webhookUrl && (
              <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
                <div className="flex items-center gap-2">
                  <LinkIcon className="h-4 w-4 text-muted-foreground" />
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Webhook URL
                  </div>
                </div>
                <div className="space-y-1.5">
                  <div className="text-xs text-muted-foreground">
                    Send requests to this URL to trigger the agent
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={webhookUrl}
                      readOnly
                      className="font-mono text-sm"
                    />
                    <CopyButton text={webhookUrl} label="Webhook URL" />
                  </div>
                </div>
              </div>
            )}

            {/* Cron schedule info */}
            {isCron && trigger.config?.cron_expression && (
              <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Schedule
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <div className="text-xs text-muted-foreground">
                      Cron expression
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 rounded-md border border-border/60 bg-background px-3 py-2 font-mono text-sm">
                        {trigger.config.cron_expression}
                      </div>
                      <CopyButton
                        text={trigger.config.cron_expression}
                        label="Cron expression"
                      />
                    </div>
                    {trigger.config.timezone && (
                      <div className="text-xs text-muted-foreground">
                        Timezone:{" "}
                        <span className="font-mono">
                          {trigger.config.timezone}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
                        Last run
                      </div>
                      <div className="text-sm">
                        {trigger.last_run_at ? (
                          formatDistanceToNow(new Date(trigger.last_run_at), {
                            addSuffix: true,
                          })
                        ) : (
                          <span className="text-muted-foreground">Never</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1">
                        Next run
                      </div>
                      <div className="text-sm">
                        {trigger.next_run_at ? (
                          formatDistanceToNow(new Date(trigger.next_run_at), {
                            addSuffix: true,
                          })
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Configuration details grid */}
            <div className="grid gap-4 md:grid-cols-2">
              {/* Agent info */}
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Agent
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <AgentAvatar agent={{ id: trigger.agent_id || agentName, name: agentName }} size="sm" />
                  <span>{agentName}</span>
                </div>
              </div>

              {/* Webhook-specific info */}
              {!isCron && trigger.webhook_type && (
                <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Configuration
                  </div>
                  <div className="space-y-2 text-sm">
                    <div>
                      <span className="text-muted-foreground">
                        Webhook type:{" "}
                      </span>
                      <span className="capitalize font-mono">
                        {trigger.webhook_type}
                      </span>
                    </div>
                    {trigger.last_run_at && (
                      <div>
                        <span className="text-muted-foreground">
                          Last triggered:{" "}
                        </span>
                        <span>
                          {formatDistanceToNow(new Date(trigger.last_run_at), {
                            addSuffix: true,
                          })}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Event type filters */}
            {trigger.event_types && trigger.event_types.length > 0 && (
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Event Filters
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {trigger.event_types.map((event: string) => (
                    <Badge
                      key={event}
                      variant="outline"
                      className="text-xs font-mono"
                    >
                      {event}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Task parameters */}
            {trigger.task_parameters &&
              Object.keys(trigger.task_parameters).length > 0 && (
                <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Task Parameters
                  </div>
                  <pre className="overflow-auto rounded-md bg-muted/40 p-3 text-xs font-mono">
                    {JSON.stringify(trigger.task_parameters, null, 2)}
                  </pre>
                </div>
              )}
          </div>
        </div>
      </div>

      <TaskInfoPanelDock
        storageKey="trigger-detail-panel"
        panel={
          <TriggerInfoPanel
            trigger={trigger}
            catalogEntry={catalogEntry}
            agentName={agentName}
          />
        }
      />
    </div>
  );
}
