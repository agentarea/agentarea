"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Check,
  Container,
  Copy,
  Link as LinkIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Table from "@/components/Table/Table";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { MCPInstance, MCPServer } from "../types";
import { getMCPInstanceHealth } from "@/lib/api";
import MCPInstancePanel from "./MCPInstancePanel";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const t = useTranslations("MCPServersPage.instanceDetail");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(t("success.copied", { label: label || t("labels.value") }));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("errors.copyFailed"));
    }
  };

  return (
    <Button
      variant="outline"
      size="xs"
      onClick={handleCopy}
    >
      {copied ? (
        <Check className="h-4 w-4 text-green-500" />
      ) : (
        <Copy className="h-4 w-4" />
      )}
    </Button>
  );
}

export default function MCPInstanceDetail({ instance, serverSpec }: Props) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const router = useRouter();
  const [connectionUrl, setConnectionUrl] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);

  // Poll for status updates during transient states
  useEffect(() => {
    const transient = ["starting", "stopping", "pending", "validating"];
    if (!transient.includes(instance.status)) return;

    const interval = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(interval);
  }, [instance.status, router]);

  // Fetch connection URL when instance is running (skip for URL-type — it has its own endpoint)
  const jsonSpecType = (instance.json_spec?.type as string) || "docker";
  useEffect(() => {
    if (jsonSpecType === "url") return; // URL-type uses endpoint_url directly
    if (instance.status === "running" && instance.name) {
      setIsLoadingUrl(true);
      getMCPInstanceHealth(instance.name)
        .then(({ health_check }) => {
          if (health_check?.details?.proxy_url) {
            setConnectionUrl(health_check.details.proxy_url);
          } else if (health_check?.url) {
            setConnectionUrl(health_check.url);
          }
        })
        .catch(console.error)
        .finally(() => setIsLoadingUrl(false));
    }
  }, [instance.status, instance.name, jsonSpecType]);

  const envVars = (instance.json_spec?.environment ?? {}) as Record<string, string>;
  const containerImage = instance.json_spec?.image as string | undefined;
  const containerPort = instance.json_spec?.port as number | undefined;
  const tools = (instance.json_spec?.available_tools ?? []) as Array<{name: string; description: string}>;

  // Determine MCP type
  const specType = (instance.json_spec?.type as string) || "docker";
  const isUrlType = specType === "url";
  const isCommandType = specType === "command";

  // Command-type fields
  const commandStr = instance.json_spec?.command as string | undefined;
  const commandArgs = (instance.json_spec?.args ?? []) as string[];

  // URL-type fields
  const endpointUrl = instance.json_spec?.endpoint_url as string | undefined;
  const customHeaders = (instance.json_spec?.headers ?? {}) as Record<string, string>;

  // Generate SSE endpoint URL from connection URL
  const effectiveConnectionUrl = isUrlType ? endpointUrl : connectionUrl;
  const sseUrl = effectiveConnectionUrl ? `${effectiveConnectionUrl.replace(/\/$/, "")}/sse` : null;

  const toolsTableData = tools.map((tool) => ({
    id: tool.name,
    name: tool.name,
    description: tool.description,
  }));

  const envTableData = Object.entries(envVars).map(([key, value]) => ({
    id: key,
    key,
    value,
  }));

  return (
    <div className="flex h-full w-full">
      <div className="flex-1">
        <div className="relative h-full overflow-auto px-4 py-5">
          <div className="mx-auto w-full max-w-5xl space-y-6">
            {/* Connection URL - Show when running, or always for URL-type */}
            {(instance.status === "running" || isUrlType) && (
              <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
                <div className="flex items-center gap-2">
                  <LinkIcon className="h-4 w-4 text-muted-foreground" />
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t("connection.title")}
                  </div>
                </div>

                {!isUrlType && isLoadingUrl ? (
                  <div className="note">{t("connection.loading")}</div>
                ) : effectiveConnectionUrl ? (
                  <div className="space-y-3">
                    {/* Main connection URL */}
                    <div className="space-y-1.5">
                      <div className="text-xs text-muted-foreground">
                        {isUrlType
                          ? t("connection.externalEndpoint")
                          : t("connection.mcpEndpoint")}
                      </div>
                      <div className="flex gap-2">
                        <Input
                          value={effectiveConnectionUrl}
                          readOnly
                          className="font-mono text-sm"
                        />
                        <CopyButton
                          text={effectiveConnectionUrl}
                          label={t("labels.connectionUrl")}
                        />
                      </div>
                    </div>

                    {/* SSE endpoint URL */}
                    {sseUrl && !isUrlType && (
                      <div className="space-y-1.5">
                        <div className="text-xs text-muted-foreground">
                          {t("connection.sseEndpoint")}
                        </div>
                        <div className="flex gap-2">
                          <Input
                            value={sseUrl}
                            readOnly
                            className="font-mono text-sm"
                          />
                          <CopyButton text={sseUrl} label={t("labels.sseUrl")} />
                        </div>
                      </div>
                    )}

                    <p className="note">
                      {isUrlType
                        ? t("connection.noteExternal")
                        : t("connection.note")}
                    </p>
                  </div>
                ) : (
                  <div className="note">{t("connection.notAvailable")}</div>
                )}
              </div>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              {!isCommandType &&
                !isUrlType &&
                (containerImage || containerPort) && (
                  <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                        {t("container.title")}
                      </div>
                      <Badge variant="outline" size="sm">
                        {t("types.docker")}
                      </Badge>
                    </div>
                    <div className="space-y-2 text-sm">
                      {containerImage && (
                        <div className="flex items-start gap-2">
                          <Container className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="break-all font-mono">
                            {containerImage}
                          </span>
                        </div>
                      )}
                      {containerPort && (
                        <div className="text-muted-foreground">
                          {t("container.port")}:{" "}
                          <span className="font-mono">{containerPort}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

              {/* Configuration info - type-aware */}
              {isCommandType && commandStr && (
                <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t("command.title")}
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="rounded bg-muted/40 p-2 font-mono break-all">
                      {commandStr} {commandArgs.join(" ")}
                    </div>
                    <p className="note">{t("command.note")}</p>
                  </div>
                </div>
              )}

              {isUrlType && (
                <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t("external.title")}
                  </div>
                  <div className="space-y-2 text-sm">
                    {endpointUrl && (
                      <div className="rounded bg-muted/40 p-2 font-mono break-all">
                        {endpointUrl}
                      </div>
                    )}
                    {Object.keys(customHeaders).length > 0 && (
                      <div>
                        <p className="note mb-1">{t("external.customHeaders")}</p>
                        {Object.entries(customHeaders).map(([key]) => (
                          <div key={key} className="font-mono text-xs">
                            {key}: ••••••
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {tools.length > 0 && (
              <div className="space-y-3">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("tools.title", { count: tools.length })}
                </div>
                <Table
                  data={toolsTableData}
                  columns={[
                    {
                      header: t("tools.columns.name"),
                      accessor: "name",
                      render: (value: string) => (
                        <span className="font-mono text-sm font-medium">
                          {value}
                        </span>
                      ),
                    },
                    {
                      header: t("tools.columns.description"),
                      accessor: "description",
                      render: (value: string) => (
                        <span className="text-sm text-muted-foreground">
                          {value || "-"}
                        </span>
                      ),
                    },
                  ]}
                />
              </div>
            )}

            {Object.keys(envVars).length > 0 && (
              <div className="space-y-3">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("env.title")}
                </div>
                <Table
                  data={envTableData}
                  columns={[
                    {
                      header: t("env.columns.key"),
                      accessor: "key",
                      render: (value: string) => (
                        <span className="font-mono text-xs text-muted-foreground">
                          {value}
                        </span>
                      ),
                    },
                    {
                      header: t("env.columns.value"),
                      accessor: "value",
                      render: (value: string) =>
                        value ? (
                          <span className="font-mono text-xs">{value}</span>
                        ) : (
                          <span className="text-xs italic text-muted-foreground">
                            {t("env.notSet")}
                          </span>
                        ),
                    },
                  ]}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <TaskInfoPanelDock
        storageKey="mcp-instance-panel"
        panel={<MCPInstancePanel instance={instance} serverSpec={serverSpec} />}
      />
    </div>
  );
}
