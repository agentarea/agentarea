"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  Check,
  Container,
  Copy,
  Link as LinkIcon,
  Play,
  RefreshCw,
  Square,
  Trash2,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Table from "@/components/Table/Table";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { MCPInstance, MCPServer } from "../types";
import { getMCPInstanceHealth } from "@/lib/api";
import {
  discoverMCPInstanceToolsAction as discoverMCPInstanceTools,
  startBundleProxyAction,
  stopBundleProxyAction,
} from "@/lib/server-actions";
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

  const [isRefreshingTools, setIsRefreshingTools] = useState(false);
  const [health, setHealth] = useState<{
    healthy: boolean;
    response_time_ms: number;
    container_status: string;
  } | null>(null);

  const canStart = instance.status !== "running" && instance.status !== "starting";
  const canStop = instance.status === "running" || instance.status === "starting";

  const [isBundleStarting, setIsBundleStarting] = useState(false);
  const [isBundleStopping, setIsBundleStopping] = useState(false);

  const handleStartBundle = async () => {
    setIsBundleStarting(true);
    try {
      const { error } = await startBundleProxyAction(instance.id);
      if (error) throw new Error(error);
      toast.success("Server started");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start server");
    } finally {
      setIsBundleStarting(false);
    }
  };

  const handleStopBundle = async () => {
    setIsBundleStopping(true);
    try {
      const { error } = await stopBundleProxyAction(instance.id);
      if (error) throw new Error(error);
      toast.success("Server stopped");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to stop server");
    } finally {
      setIsBundleStopping(false);
    }
  };

  const handleRefreshTools = async () => {
    setIsRefreshingTools(true);
    try {
      const { error } = await discoverMCPInstanceTools(instance.id);
      if (error) throw new Error(typeof error === "object" && "detail" in error ? String(error.detail) : "Failed to refresh tools");
      toast.success("Tools refreshed successfully");
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to refresh tools");
    } finally {
      setIsRefreshingTools(false);
    }
  };

  // Handle OAuth redirect result
  const searchParams = useSearchParams();
  useEffect(() => {
    const oauthResult = searchParams.get("oauth");
    if (oauthResult === "success") {
      toast.success(t("oauth.connectSuccess"));
      router.replace(`/mcp-servers/${instance.id}`, { scroll: false });
    } else if (oauthResult === "error") {
      const reason = searchParams.get("reason") || "unknown";
      toast.error(t("oauth.connectError", { reason }));
      router.replace(`/mcp-servers/${instance.id}`, { scroll: false });
    }
  }, [searchParams, instance.id, router, t]);

  // Poll for status updates during transient states
  useEffect(() => {
    const transient = ["starting", "stopping", "pending", "validating"];
    if (!transient.includes(instance.status)) return;

    const interval = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(interval);
  }, [instance.status, router]);

  // Fetch connection URL when instance is running (skip for URL-type and bundle-type)
  const jsonSpecType = (instance.json_spec?.type as string) || "docker";
  useEffect(() => {
    if (jsonSpecType === "url" || jsonSpecType === "bundle") return;
    if (instance.status === "running" && instance.name) {
      setIsLoadingUrl(true);
      getMCPInstanceHealth(instance.name)
        .then(({ health_check }) => {
          if (health_check?.details?.proxy_url) {
            setConnectionUrl(health_check.details.proxy_url);
          } else if (health_check?.url) {
            setConnectionUrl(health_check.url);
          }
          if (health_check) {
            setHealth({
              healthy: health_check.healthy,
              response_time_ms: health_check.response_time_ms,
              container_status: health_check.container_status,
            });
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
  const isBundleType = specType === "bundle";
  const bundleMembers = (instance.json_spec?.members ?? []) as string[];

  // Command-type fields
  const commandStr = instance.json_spec?.command as string | undefined;
  const commandArgs = (instance.json_spec?.args ?? []) as string[];

  // URL-type fields
  const endpointUrl = instance.json_spec?.endpoint_url as string | undefined;
  const customHeaders = (instance.json_spec?.headers ?? {}) as Record<string, string>;

  // Generate SSE endpoint URL from connection URL
  const bundleEndpointUrl = isBundleType ? `/mcp/${instance.id}` : null;
  const effectiveConnectionUrl = isUrlType ? endpointUrl : isBundleType ? bundleEndpointUrl : connectionUrl;
  const sseUrl = effectiveConnectionUrl && !isBundleType ? `${effectiveConnectionUrl.replace(/\/$/, "")}/sse` : null;

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
            {/* Refresh Tools button */}
            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={handleRefreshTools}
                disabled={isRefreshingTools}
              >
                <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isRefreshingTools ? "animate-spin" : ""}`} />
                Refresh Tools
              </Button>
              {canStart && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!isBundleType || isBundleStarting}
                  onClick={isBundleType ? handleStartBundle : undefined}
                >
                  <Play className={`mr-1.5 h-3.5 w-3.5 ${isBundleStarting ? "animate-spin" : ""}`} />
                  {isBundleStarting ? "Starting..." : "Start"}
                </Button>
              )}
              {canStop && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!isBundleType || isBundleStopping}
                  onClick={isBundleType ? handleStopBundle : undefined}
                >
                  <Square className="mr-1.5 h-3.5 w-3.5" />
                  {isBundleStopping ? "Stopping..." : "Stop"}
                </Button>
              )}
            </div>

            {/* Connection URL - Show when running, or always for URL-type/bundle-type */}
            {(instance.status === "running" || isUrlType || isBundleType) && (
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

            {/* Health info */}
            {health && (
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Health
                </div>
                <div className="grid gap-2 text-sm sm:grid-cols-3">
                  <div>
                    <span className="text-muted-foreground">Status</span>
                    <p className="mt-0.5">
                      {health.healthy ? (
                        <span className="flex items-center gap-1 text-green-600">
                          Healthy
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red-600">
                          <XCircle className="h-3.5 w-3.5" /> Unhealthy
                        </span>
                      )}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Response Time</span>
                    <p className="mt-0.5 font-mono">{health.response_time_ms}ms</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Container</span>
                    <p className="mt-0.5 capitalize">{health.container_status}</p>
                  </div>
                </div>
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

            {isBundleType && bundleMembers.length > 0 && (
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Sources
                </div>
                <div className="space-y-1">
                  {bundleMembers.map((memberId: string) => (
                    <div key={memberId} className="text-sm text-muted-foreground font-mono">
                      {memberId}
                    </div>
                  ))}
                </div>
              </div>
            )}

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
