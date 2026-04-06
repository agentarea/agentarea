"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  Check,
  Container,
  Copy,
  Link as LinkIcon,
  Pencil,
  Play,
  ExternalLink,
  Github,
  Globe,
  RefreshCw,
  Server,
  Square,
  Trash2,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Table from "@/components/Table/Table";
import { ToolsTable } from "../components/ToolsTable";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { MCPInstance, MCPServer } from "../types";
import { getMCPInstanceHealth } from "@/lib/api";
import {
  discoverMCPInstanceToolsAction as discoverMCPInstanceTools,
} from "@/lib/server-actions";
import MCPInstancePanel from "./MCPInstancePanel";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
  memberNames?: Record<string, string>;
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

export default function MCPInstanceDetail({ instance, serverSpec, memberNames = {} }: Props) {
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

  const canStart = instance.status !== "running" && instance.status !== "starting" && instance.status !== "connected";
  const canStop = instance.status === "running" || instance.status === "starting";


  // Editable config state
  const [isEditingConfig, setIsEditingConfig] = useState(false);
  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [editHeaders, setEditHeaders] = useState<Record<string, string>>(
    (instance.json_spec?.headers ?? {}) as Record<string, string>
  );

  const handleSaveConfig = async () => {
    setIsSavingConfig(true);
    try {
      const { updateMCPServerInstanceAction } = await import("@/lib/server-actions");
      await updateMCPServerInstanceAction(instance.id, {
        json_spec: {
          ...instance.json_spec,
          headers: editHeaders,
        },
      });
      setIsEditingConfig(false);
      router.refresh();
    } catch {
      // Error is visible through unchanged config on page
    } finally {
      setIsSavingConfig(false);
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

  const plainEnvVars = (instance.json_spec?.environment ?? {}) as Record<string, string>;
  const secretEnvNames = (instance.json_spec?.env_vars ?? []) as string[];
  // Merge non-secret env vars with secret env vars (masked)
  const envVars: Record<string, string> = { ...plainEnvVars };
  for (const name of secretEnvNames) {
    if (!(name in envVars)) {
      envVars[name] = "******";
    }
  }
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

  // AgentArea proxy URL — how other agents/tools connect to this MCP through AgentArea
  const apiBaseUrl = typeof window !== "undefined"
    ? (window as any).__ENV__?.CLIENT_API_URL || ""
    : "";
  const agentareaProxyUrl = `${apiBaseUrl}/mcp/${instance.id}`;

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
              {canStart && !isUrlType && !isBundleType && (
                <Button size="sm" variant="outline" disabled>
                  <Play className="mr-1.5 h-3.5 w-3.5" />
                  Start
                </Button>
              )}
              {canStop && !isUrlType && !isBundleType && (
                <Button size="sm" variant="outline" disabled>
                  <Square className="mr-1.5 h-3.5 w-3.5" />
                  Stop
                </Button>
              )}
            </div>

            {/* Spec info — repo, website, description from server spec */}
            {serverSpec && (() => {
              const spec = (serverSpec as any).json_spec as Record<string, any> | undefined;
              const repoUrl = spec?.repository?.url as string | undefined;
              const repoSource = spec?.repository?.source as string | undefined;
              const websiteUrl = spec?.websiteUrl as string | undefined;
              const specTitle = spec?.title || serverSpec.name;
              const specIcon = spec?.icons?.[0]?.src as string | undefined;
              const specDesc = serverSpec.description;

              if (!repoUrl && !websiteUrl && !specDesc) return null;

              return (
                <div className="rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40 space-y-2">
                  <div className="flex items-center gap-3">
                    {specIcon && (
                      <img src={specIcon} alt="" className="h-8 w-8 rounded object-contain shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-sm">{specTitle}</div>
                      {specDesc && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{specDesc}</p>
                      )}
                    </div>
                  </div>
                  {(repoUrl || websiteUrl) && (
                    <div className="flex items-center gap-3 pt-1">
                      {repoUrl && (
                        <a href={repoUrl} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                          {repoSource === "github" ? <Github className="h-3.5 w-3.5" /> : <Globe className="h-3.5 w-3.5" />}
                          {repoSource === "github" ? "GitHub" : "Repository"}
                        </a>
                      )}
                      {websiteUrl && (
                        <a href={websiteUrl} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                          <ExternalLink className="h-3.5 w-3.5" />
                          Website
                        </a>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* AgentArea proxy URL - always shown so agents can connect through AgentArea */}
            <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
              <div className="flex items-center gap-2">
                <LinkIcon className="h-4 w-4 text-muted-foreground" />
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  AgentArea Proxy URL
                </div>
              </div>
              <div className="space-y-1.5">
                <div className="text-xs text-muted-foreground">
                  Connect to this MCP server through AgentArea
                </div>
                <div className="flex gap-2">
                  <Input
                    value={agentareaProxyUrl}
                    readOnly
                    className="font-mono text-sm"
                  />
                  <CopyButton text={agentareaProxyUrl} label="proxy URL" />
                </div>
              </div>
            </div>

            {/* Connection URL - Show when running/connected, or always for URL-type/bundle-type */}
            {(instance.status === "running" || instance.status === "connected" || isUrlType || isBundleType) && (
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
                  <div className="flex items-center justify-between">
                    <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {t("external.title")}
                    </div>
                    {!isEditingConfig && (
                      <Button variant="ghost" size="xs" onClick={() => setIsEditingConfig(true)}>
                        <Pencil className="h-3 w-3 mr-1" /> Edit
                      </Button>
                    )}
                  </div>
                  {isEditingConfig ? (
                    <div className="space-y-3">
                      {Object.entries(editHeaders).map(([key, val]) => {
                        const fieldMeta = (
                          (serverSpec as any)?.json_spec?.remotes?.[0]?.headers ||
                          (serverSpec?.env_schema as any[]) ||
                          []
                        ).find((h: any) => h.name === key);
                        return (
                          <div key={key} className="space-y-1">
                            <label className="text-xs font-medium">{key}</label>
                            {fieldMeta?.description && (
                              <p className="text-xs text-muted-foreground">{fieldMeta.description}</p>
                            )}
                            <Input
                              type={fieldMeta?.isSecret !== false ? "password" : "text"}
                              value={val}
                              placeholder={fieldMeta?.placeholder || ""}
                              onChange={(e) => setEditHeaders((prev) => ({ ...prev, [key]: e.target.value }))}
                            />
                          </div>
                        );
                      })}
                      <div className="flex gap-2">
                        <Button size="sm" onClick={handleSaveConfig} disabled={isSavingConfig}>
                          {isSavingConfig ? "Saving..." : "Save"}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => { setIsEditingConfig(false); setEditHeaders(customHeaders); }}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
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
                  )}
                </div>
              )}
            </div>

            {isBundleType && bundleMembers.length > 0 && (
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("bundle.members")}
                </div>
                <div className="space-y-1.5">
                  {bundleMembers.map((memberId: string) => (
                    <Link
                      key={memberId}
                      href={`/mcp-servers/${memberId}`}
                      className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <Server className="h-3.5 w-3.5 shrink-0" />
                      <span>{memberNames[memberId] || memberId}</span>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {tools.length > 0 && (
              <ToolsTable tools={tools} label={t("tools.title", { count: tools.length })} />
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
