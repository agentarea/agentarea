"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { useSearchParams } from "next/navigation";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  Check,
  Clock,
  Container,
  Copy,
  ExternalLink,
  Github,
  Globe,
  Hash,
  Link as LinkIcon,
  Pencil,
  RefreshCw,
  Server,
} from "lucide-react";
import EntityMark from "@/components/EntityMark";
import FormError from "@/components/FormError";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { mcpIdentity } from "@/lib/entity-identity";
import { getMCPInstanceConsumers, type MCPInstanceConsumer } from "@/lib/api";
import { getMcpVerificationStatusPresentation } from "@/lib/status";
import { discoverMCPInstanceToolsAction as discoverMCPInstanceTools } from "@/lib/server-actions";
import { OAuthConnectPanel } from "../OAuthConnectPanel";
import {
  summarizeAuthorization,
  type OAuthConnectState,
} from "../oauth-connect-state";
import { ToolsTable } from "../components/ToolsTable";
import { ConsumersSection } from "./ConsumersSection";
import { InstanceActivitySection } from "./InstanceActivitySection";
import { MCPInstance, MCPServer } from "../types";
import { getEffectiveMCPVerificationStatus } from "../utils";
import { verifyInstance } from "./actions";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
  memberNames?: Record<string, string>;
}

const MCP_TRANSPORT = {
  url: "url",
  bundle: "bundle",
  command: "command",
  docker: "docker",
} as const;

interface McpHeaderField {
  name: string;
  description?: string;
  isSecret?: boolean;
  placeholder?: string;
}

interface McpServerJsonSpec {
  type?: string;
  remotes?: Array<{ url?: string; headers?: McpHeaderField[] }>;
  repository?: { url?: string; source?: string };
  websiteUrl?: string;
  title?: string;
  icons?: Array<{ src?: string }>;
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const t = useTranslations("MCPServersPage.instanceDetail");
  const tCommon = useTranslations("Common");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyFailed(false);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy to clipboard", err);
      setCopyFailed(true);
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="xs"
        onClick={handleCopy}
        aria-label={label || t("labels.value")}
      >
        {copied ? (
          <Check className="text-green-500" />
        ) : (
          <Copy />
        )}
      </Button>
      {copyFailed && (
        <span role="alert" className="text-xs text-destructive">
          {tCommon("copyFailed")}
        </span>
      )}
    </>
  );
}

export default function MCPInstanceDetail({
  instance,
  serverSpec,
  memberNames = {},
}: Props) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const [isRefreshingTools, setIsRefreshingTools] = useState(false);
  const [discovery, setDiscovery] = useState<
    { kind: "succeeded"; count: number } | { kind: "failed"; message: string } | null
  >(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [saveConfigError, setSaveConfigError] = useState<string | null>(null);
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError, setOauthError] = useState<string | null>(() =>
    searchParams.get("oauth") === "error"
      ? searchParams.get("reason") || "unknown"
      : null
  );

  // Stuck detection: in_progress verification older than 30s
  const verification = instance.verification as
    | {
        status: string;
        at?: string | null;
        error?: { message: string; code?: string | null } | null;
      }
    | null
    | undefined;
  const effectiveVerificationStatus =
    getEffectiveMCPVerificationStatus(instance);

  const isStuck =
    verification?.status === "in_progress" &&
    verification.at &&
    Date.now() - new Date(verification.at).getTime() > 30_000;

  const [isVerifying, setIsVerifying] = useState(false);
  const [oauthState, setOauthState] = useState<OAuthConnectState | undefined>();

  // One fetch for both the tools table (principals per tool) and the consumers
  // section (tools per agent) — the endpoint scans every agent in the
  // workspace, so it must not be called twice for the same page.
  const [consumers, setConsumers] = useState<MCPInstanceConsumer[] | null>(null);
  const [consumersError, setConsumersError] = useState<string | null>(null);
  const [consumersAttempt, setConsumersAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setConsumersError(null);
    getMCPInstanceConsumers(instance.id)
      .then((result) => {
        if (!active) return;
        if (result.error || !result.data) {
          setConsumersError(
            apiErrorMessage(result, t("errors.consumersLoadFailed"))
          );
          return;
        }
        setConsumers(result.data);
      })
      .catch((err) => {
        console.error("Failed to load MCP instance consumers", err);
        if (active) {
          setConsumersError(
            `${t("errors.consumersLoadFailed")}: ${formatApiError(err)}`
          );
        }
      });
    return () => {
      active = false;
    };
  }, [instance.id, consumersAttempt, t]);

  const handleVerify = async () => {
    setIsVerifying(true);
    setVerifyError(null);
    try {
      const result = await verifyInstance(instance.id);
      if (result.error) {
        setVerifyError(apiErrorMessage(result, t("errors.verifyFailed")));
        return;
      }
      router.refresh();
    } catch (err) {
      console.error("Failed to verify MCP instance", err);
      setVerifyError(`${t("errors.verifyFailed")}: ${formatApiError(err)}`);
    } finally {
      setIsVerifying(false);
    }
  };

  // Editable config state
  const [isEditingConfig, setIsEditingConfig] = useState(false);
  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [editHeaders, setEditHeaders] = useState<Record<string, string>>(
    (instance.json_spec?.headers ?? {}) as Record<string, string>
  );

  const handleSaveConfig = async () => {
    setIsSavingConfig(true);
    setSaveConfigError(null);
    try {
      const { updateMCPServerInstanceAction } = await import(
        "@/lib/server-actions"
      );
      const result = await updateMCPServerInstanceAction(instance.id, {
        json_spec: {
          ...instance.json_spec,
          headers: editHeaders,
        },
      });
      if (result.error) {
        setSaveConfigError(
          apiErrorMessage(result, t("errors.saveConfigFailed"))
        );
        return;
      }
      setIsEditingConfig(false);
      router.refresh();
    } catch (err) {
      console.error("Failed to save MCP instance config", err);
      setSaveConfigError(
        `${t("errors.saveConfigFailed")}: ${formatApiError(err)}`
      );
    } finally {
      setIsSavingConfig(false);
    }
  };

  const handleRefreshTools = async () => {
    setIsRefreshingTools(true);
    setDiscovery(null);
    try {
      const response = await discoverMCPInstanceTools(instance.id);
      if (response.error) {
        setDiscovery({
          kind: "failed",
          message: apiErrorMessage(response, t("tools.discoverFailed")),
        });
        return;
      }
      // The endpoint returns 200 with {tools, verification} even when verification
      // failed, so report based on the actual result, not the HTTP status.
      const result = response.data as
        | {
            tools?: unknown[];
            verification?: { status?: string; error?: { message?: string } };
          }
        | undefined;
      if (result?.verification?.status === "succeeded") {
        setDiscovery({ kind: "succeeded", count: result.tools?.length ?? 0 });
      } else {
        const reason = result?.verification?.error?.message;
        setDiscovery({
          kind: "failed",
          message: reason
            ? `${t("tools.discoverFailed")}: ${reason}`
            : t("tools.discoverUnverified"),
        });
      }
      router.refresh();
    } catch (err) {
      console.error("Failed to discover MCP instance tools", err);
      setDiscovery({
        kind: "failed",
        message: `${t("tools.discoverFailed")}: ${formatApiError(err)}`,
      });
    } finally {
      setIsRefreshingTools(false);
    }
  };

  // Drop the OAuth callback's query; the panel shows the authorized state and
  // a failure stays on the page through `oauthError`.
  useEffect(() => {
    if (searchParams.get("oauth")) {
      router.replace(`/connections/${instance.id}`, { scroll: false });
    }
  }, [searchParams, instance.id, router]);

  // Poll while verification is in_progress
  useEffect(() => {
    if (verification?.status !== "in_progress") return;
    const interval = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(interval);
  }, [verification?.status, router]);

  // Derive transport type. After PR #151 transport moved to MCPServer columns,
  // so instance.json_spec.type is empty for newly-created instances — fall back
  // to the parent server spec (remote_url → url, cmd → command, else docker).
  const derivedTransportType = ((): string => {
    const fromInstance = instance.json_spec?.type as string | undefined;
    if (fromInstance) return fromInstance;
    if (serverSpec?.remote_url) return MCP_TRANSPORT.url;
    const specJson = serverSpec?.json_spec as McpServerJsonSpec | undefined;
    if (specJson?.type) return specJson.type;
    if (serverSpec?.cmd) return MCP_TRANSPORT.command;
    return MCP_TRANSPORT.docker;
  })();

  const plainEnvVars = (instance.json_spec?.environment ?? {}) as Record<
    string,
    string
  >;
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
  const tools = (instance.tools ??
    instance.json_spec?.available_tools ??
    []) as Array<{ name: string; description: string }>;

  // Determine MCP type (uses derivedTransportType — see above)
  const specType = derivedTransportType;
  const isUrlType = specType === MCP_TRANSPORT.url;
  const isCommandType = specType === MCP_TRANSPORT.command;
  const isBundleType = specType === MCP_TRANSPORT.bundle;
  const bundleMembers = (instance.json_spec?.members ?? []) as string[];

  const authorization = summarizeAuthorization({
    isUrlType,
    verificationStatus: verification?.status,
    connected: !!instance.auth_config_id,
    oauthState: oauthState?.kind,
  });

  // Command-type fields
  const commandStr = instance.json_spec?.command as string | undefined;
  const commandArgs = (instance.json_spec?.args ?? []) as string[];

  // URL-type fields. Like derivedTransportType above, the endpoint lives on the
  // parent server spec for catalog instances (remote_url / remotes[].url), not in
  // the instance json_spec — fall back so the External Server card isn't empty.
  const endpointUrl = (instance.json_spec?.endpoint_url ||
    serverSpec?.remote_url ||
    (serverSpec?.json_spec as McpServerJsonSpec | undefined)?.remotes?.[0]
      ?.url) as string | undefined;
  const customHeaders = (instance.json_spec?.headers ?? {}) as Record<
    string,
    string
  >;

  // The one way in, for every transport: AgentArea's demand gateway, keyed by
  // instance id. It is what gives on-demand start, the request lease and idle
  // reclamation, so nothing here should ever offer a second, direct address —
  // the workload's own URL is the manager's business. Rendered as a compact
  // top-row so it stays discoverable without dominating the layout.
  const apiBaseUrl =
    typeof window !== "undefined"
      ? (window as unknown as { __ENV__?: { CLIENT_API_URL?: string } })
          .__ENV__?.CLIENT_API_URL || ""
      : "";
  const agentareaProxyUrl = `${apiBaseUrl}/v1/mcp/${instance.id}/mcp`;

  const envTableData = Object.entries(envVars).map(([key, value]) => ({
    id: key,
    key,
    value,
  }));

  const verificationPresentation = getMcpVerificationStatusPresentation(
    effectiveVerificationStatus
  );

  const specJson = serverSpec?.json_spec as McpServerJsonSpec | undefined;
  const repoUrl = specJson?.repository?.url as string | undefined;
  const repoSource = specJson?.repository?.source as string | undefined;
  const websiteUrl = specJson?.websiteUrl as string | undefined;
  const displayDescription = instance.description || serverSpec?.description;

  const discoveryResult =
    discovery?.kind === "failed" ? (
      <FormError>{discovery.message}</FormError>
    ) : discovery?.kind === "succeeded" ? (
      <p className="text-xs text-muted-foreground">
        {t("tools.discovered", { count: discovery.count })}
      </p>
    ) : null;

  return (
    <div className="relative h-full overflow-auto px-4 py-5">
      <div className="mx-auto w-full max-w-5xl space-y-6">
            {/* Connection identity — the primary "what am I looking at" block:
                name, spec, status, and the connect URL clients need. */}
            <div className="space-y-4 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <EntityMark
                    identity={mcpIdentity(instance, serverSpec, endpointUrl)}
                    className="h-10 w-10 shrink-0 rounded"
                  />
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-base font-semibold text-foreground">
                        {instance.name || t("header.untitled")}
                      </h2>
                      {serverSpec?.version && (
                        <span className="note">v{serverSpec.version}</span>
                      )}
                    </div>
                    {displayDescription && (
                      <p className="text-sm text-muted-foreground">
                        {displayDescription}
                      </p>
                    )}
                    {(repoUrl || websiteUrl) && (
                      <div className="flex items-center gap-3 pt-0.5">
                        {repoUrl && (
                          <a
                            href={repoUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                          >
                            {repoSource === "github" ? (
                              <Github className="h-3.5 w-3.5" />
                            ) : (
                              <Globe className="h-3.5 w-3.5" />
                            )}
                            {repoSource === "github" ? "GitHub" : "Repository"}
                          </a>
                        )}
                        {websiteUrl && (
                          <a
                            href={websiteUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                            Website
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <StatusIndicator
                  size="sm"
                  kind={verificationPresentation.kind}
                >
                  {verificationPresentation.label}
                </StatusIndicator>
              </div>

              {/* Connect URL — proxy URL for outbound MCP clients. Rendered as
                  plain wrapping text (not an input) so the full URL stays visible
                  and never overflows the column. */}
              <div className="flex items-start gap-2 border-t border-border/50 pt-3">
                <div className="mt-1 flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <LinkIcon className="h-3.5 w-3.5" />
                  <span>Connect URL</span>
                </div>
                <code className="min-w-0 flex-1 break-all rounded bg-muted/40 px-2 py-1 font-mono text-xs">
                  {agentareaProxyUrl}
                </code>
                <CopyButton text={agentareaProxyUrl} label="Connect URL" />
              </div>
            </div>

            {/* Authorization — the one place this connection is connected from.
                Rendered from the API preflight, so a provider that needs the
                workspace's own OAuth app asks for it here instead of offering a
                Connect that can only fail. */}
            {oauthError && (
              <FormError>{t("oauth.connectError", { reason: oauthError })}</FormError>
            )}

            {isUrlType && (
              <div className="space-y-2">
                {authorization.reachableButUnauthorized && (
                  <p className="text-xs text-muted-foreground">
                    {t("oauth.unauthorizedNote")}
                  </p>
                )}
                <OAuthConnectPanel
                  target={{ kind: "instance", instanceId: instance.id }}
                  isUrlType={isUrlType}
                  onStateChange={setOauthState}
                  onConnectStart={() => setOauthError(null)}
                />
              </div>
            )}

            {/* Stuck verification banner */}
            {isStuck && (
              <div
                role="alert"
                className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-900/50 dark:bg-amber-950/30"
              >
                <StatusIndicator kind="attention" size="sm">
                  Verification may be stuck. You can retry manually.
                </StatusIndicator>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={handleVerify}
                  isLoading={isVerifying}
                  disabled={isVerifying}
                >
                  Verify
                </Button>
              </div>
            )}

            {verifyError && <FormError>{verifyError}</FormError>}

            {/* Failed verification banner */}
            {verification?.status === "failed" && verification.error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 space-y-2"
              >
                <StatusIndicator
                  kind="failed"
                  size="sm"
                  iconClassName="h-4 w-4"
                >
                  Verification failed
                </StatusIndicator>
                <p className="text-sm text-destructive/80">
                  {verification.error.message}
                </p>
                {verification.error.code && (
                  <p className="font-mono text-xs text-destructive/60">
                    Code: {verification.error.code}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={handleVerify}
                    isLoading={isVerifying}
                    disabled={isVerifying}
                  >
                    Retry Verification
                  </Button>
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
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => setIsEditingConfig(true)}
                      >
                        <Pencil className="mr-1" /> Edit
                      </Button>
                    )}
                  </div>
                  {isEditingConfig ? (
                    <div className="space-y-3">
                      {Object.entries(editHeaders).map(([key, val]) => {
                        const fieldMeta = (
                          (serverSpec?.json_spec as McpServerJsonSpec | undefined)
                            ?.remotes?.[0]?.headers ||
                          (serverSpec?.env_schema as McpHeaderField[] | undefined) ||
                          []
                        ).find((h) => h.name === key);
                        return (
                          <div key={key} className="space-y-1">
                            <label className="text-xs font-medium">{key}</label>
                            {fieldMeta?.description && (
                              <p className="text-xs text-muted-foreground">
                                {fieldMeta.description}
                              </p>
                            )}
                            <Input
                              type={
                                fieldMeta?.isSecret !== false
                                  ? "password"
                                  : "text"
                              }
                              value={val}
                              placeholder={fieldMeta?.placeholder || ""}
                              onChange={(e) => {
                                setSaveConfigError(null);
                                setEditHeaders((prev) => ({
                                  ...prev,
                                  [key]: e.target.value,
                                }));
                              }}
                            />
                          </div>
                        );
                      })}
                      {saveConfigError && (
                        <FormError>{saveConfigError}</FormError>
                      )}
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={handleSaveConfig}
                          isLoading={isSavingConfig}
                          disabled={isSavingConfig}
                        >
                          {tCommon("save")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setIsEditingConfig(false);
                            setEditHeaders(customHeaders);
                            setSaveConfigError(null);
                          }}
                        >
                          {tCommon("cancel")}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2 text-sm">
                      {endpointUrl && (
                        <div className="flex gap-2">
                          <Input
                            value={endpointUrl}
                            readOnly
                            className="font-mono text-sm"
                          />
                          <CopyButton
                            text={endpointUrl}
                            label={t("labels.connectionUrl")}
                          />
                        </div>
                      )}
                      {Object.keys(customHeaders).length > 0 && (
                        <div>
                          <p className="note mb-1">
                            {t("external.customHeaders")}
                          </p>
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
                      href={`/connections/${memberId}`}
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
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {t("tools.title", { count: tools.length })}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleRefreshTools}
                    disabled={isRefreshingTools}
                  >
                    <RefreshCw
                      className={`mr-1.5 ${isRefreshingTools ? "animate-spin" : ""}`}
                    />
                    {t("tools.refresh")}
                  </Button>
                </div>
                {discoveryResult}
                <ToolsTable tools={tools} consumers={consumers} />
              </div>
            )}

            {tools.length === 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                  <span className="text-sm text-muted-foreground">
                    {t("tools.noneDiscovered")}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleRefreshTools}
                    disabled={isRefreshingTools}
                  >
                    <RefreshCw
                      className={`mr-1.5 ${isRefreshingTools ? "animate-spin" : ""}`}
                    />
                    {t("tools.discover")}
                  </Button>
                </div>
                {discoveryResult}
              </div>
            )}

            {consumersError ? (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
                <FormError className="flex-1">{consumersError}</FormError>
                <Button
                  size="xs"
                  variant="outline"
                  className="self-start"
                  onClick={() => setConsumersAttempt((n) => n + 1)}
                >
                  <RefreshCw />
                  {tCommon("retry")}
                </Button>
              </div>
            ) : (
              <ConsumersSection consumers={consumers} />
            )}

            <InstanceActivitySection instanceId={instance.id} />

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

            {/* Reference metadata — low-priority, kept at the bottom. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/50 pt-4 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Hash className="h-3 w-3" />
                <span className="font-mono">{instance.id}</span>
                <CopyButton text={instance.id} label={t("details.id")} />
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3 w-3" />
                {t("details.created")}:{" "}
                {new Date(instance.created_at).toLocaleString()}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3 w-3" />
                {t("details.updated")}:{" "}
                {new Date(instance.updated_at).toLocaleString()}
              </span>
            </div>
      </div>
    </div>
  );
}
