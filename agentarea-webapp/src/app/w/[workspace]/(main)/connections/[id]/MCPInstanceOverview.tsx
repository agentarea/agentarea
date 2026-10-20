"use client";

import { useEffect, useState } from "react";
import { useLocale, useNow, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  Activity,
  ExternalLink,
  Github,
  GitBranch,
  Globe,
  KeyRound,
  Link2,
  ShieldCheck,
  TriangleAlert,
  Users,
  Wrench,
} from "lucide-react";
import EntityMark from "@/components/EntityMark";
import FormError from "@/components/FormError";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import {
  EmptyRow,
  FactRow,
  GlanceRow,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  SoftTile,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import SectionLoadError from "@/components/SectionLoadError";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { MCPInstanceConsumer } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { mcpIdentity } from "@/lib/entity-identity";
import { useClientApiUrl } from "@/lib/use-client-api-url";
import { CustomHeadersEditor, toHeaderRows } from "../components/CustomHeadersEditor";
import { CustomHeadersList } from "../components/CustomHeadersList";
import type { HeaderRow } from "../components/HeaderRows";
import { SectionEditAction } from "../components/SectionEditAction";
import { headersUpdateSpec, remoteHeaderFields, storedHeaders } from "../credential-fields";
import { OAuthConnectPanel } from "../OAuthConnectPanel";
import { summarizeAuthorization, type OAuthConnectState } from "../oauth-connect-state";
import { getMcpConnectionState } from "../state";
import { MCPInstance, MCPServer } from "../types";
import { readLastDispatch } from "../usage";
import {
  getEffectiveMCPVerificationStatus,
  getMCPInstanceToolCount,
  TRANSPORT_LABEL,
} from "../utils";
import { CardField, ConnectionDetailsCard } from "../components/ConnectionCards";
import { ConnectionCostSection } from "../components/ConnectionCostSection";
import { relativeParts } from "../relative-parts";
import { verifyInstance } from "./actions";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
  memberNames?: Record<string, string>;
  consumers: MCPInstanceConsumer[] | null;
  consumersError: string | null;
}

interface McpServerJsonSpec {
  remotes?: Array<{ url?: string }>;
  repository?: { url?: string; source?: string };
  websiteUrl?: string;
}

const VERIFICATION_KINDS = {
  succeeded: "active",
  in_progress: "running",
  failed: "failed",
  never_attempted: "draft",
} as const;

type VerificationKey = keyof typeof VERIFICATION_KINDS;

/** An unknown status reads as "not verified" rather than a missing label. */
function verificationKey(status: string): VerificationKey {
  return status in VERIFICATION_KINDS ? (status as VerificationKey) : "never_attempted";
}

const externalLinkClass =
  "font-medium text-foreground/80 underline-offset-2 hover:underline";

export default function MCPInstanceOverview({
  instance,
  serverSpec,
  memberNames = {},
  consumers,
  consumersError,
}: Props) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const tState = useTranslations("MCPServersPage.state");
  const tConn = useTranslations("OpenAPIConnection");
  const locale = useLocale();
  const now = useNow({ updateInterval: 60_000 });
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const apiBaseUrl = useClientApiUrl();
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [saveConfigError, setSaveConfigError] = useState<string | null>(null);
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError, setOauthError] = useState<string | null>(() =>
    searchParams.get("oauth") === "error"
      ? searchParams.get("reason") || "unknown"
      : null
  );
  const [isVerifying, setIsVerifying] = useState(false);
  const [oauthState, setOauthState] = useState<OAuthConnectState | undefined>();

  const verification = instance.verification as
    | {
        status: string;
        at?: string | null;
        error?: { message: string; code?: string | null } | null;
      }
    | null
    | undefined;
  const verificationStatus = verificationKey(
    getEffectiveMCPVerificationStatus(instance)
  );

  // Stuck detection: in_progress verification older than 30s
  const isStuck =
    verification?.status === "in_progress" &&
    verification.at &&
    Date.now() - new Date(verification.at).getTime() > 30_000;

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

  // The headers draft, null while they are not being edited.
  const [headersDraft, setHeadersDraft] = useState<HeaderRow[] | null>(null);
  const [isSavingHeaders, setIsSavingHeaders] = useState(false);

  const handleSaveHeaders = async () => {
    setIsSavingHeaders(true);
    setSaveConfigError(null);
    try {
      const { updateMCPServerInstanceAction } = await import(
        "@/lib/server-actions"
      );
      // The update replaces json_spec; the helper leaves out the transport
      // fields the API refuses back and keeps a secret left blank.
      const result = await updateMCPServerInstanceAction(instance.id, {
        json_spec: headersUpdateSpec(instance.json_spec ?? {}, headersDraft ?? []),
      });
      if (result.error) {
        setSaveConfigError(apiErrorMessage(result, t("errors.saveConfigFailed")));
        return;
      }
      setHeadersDraft(null);
      router.refresh();
    } catch (err) {
      console.error("Failed to save MCP instance headers", err);
      setSaveConfigError(`${t("errors.saveConfigFailed")}: ${formatApiError(err)}`);
    } finally {
      setIsSavingHeaders(false);
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
  const toolCount = getMCPInstanceToolCount(instance);

  const isUrlType = instance.transport === "url";
  const isCommandType = instance.transport === "command";
  const isBundleType = instance.transport === "bundle";
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

  // URL-type fields. The endpoint lives on the parent server spec for catalog
  // instances (remote_url / remotes[].url), not in the instance json_spec —
  // fall back so the connection card isn't empty.
  const endpointUrl = (instance.json_spec?.endpoint_url ||
    serverSpec?.remote_url ||
    (serverSpec?.json_spec as McpServerJsonSpec | undefined)?.remotes?.[0]
      ?.url) as string | undefined;
  const headers = storedHeaders(instance.json_spec ?? {});
  // Nothing stored yet: start from the headers the server declares, if any.
  const openHeaders = () => {
    const declared = remoteHeaderFields(serverSpec);
    setSaveConfigError(null);
    setHeadersDraft(
      headers.length === 0 && declared.length > 0
        ? declared.map((field) => ({ name: field.name, value: "" }))
        : toHeaderRows(headers)
    );
  };

  // The one way in, for every transport: AgentArea's demand gateway, keyed by
  // instance id. It is what gives on-demand start, the request lease and idle
  // reclamation, so nothing here should ever offer a second, direct address —
  // the workload's own URL is the manager's business.
  const agentareaProxyUrl = `${apiBaseUrl}/v1/mcp/${instance.id}/mcp`;

  const specJson = serverSpec?.json_spec as McpServerJsonSpec | undefined;
  const repoUrl = specJson?.repository?.url;
  const repoSource = specJson?.repository?.source;
  const websiteUrl = specJson?.websiteUrl;
  const displayDescription = instance.description || serverSpec?.description;

  // The same verdict the connections list shows, so the two never disagree.
  const connectionState = getMcpConnectionState({
    verification: instance.verification,
    last_dispatch: instance.last_dispatch,
    toolCount,
  });
  const lastDispatch = readLastDispatch(instance.last_dispatch);


  const unrestrictedCount =
    consumers?.filter((consumer) => consumer.enabled_tools == null).length ?? 0;
  const lastCallAt = relativeParts(lastDispatch?.at, now, locale);
  const verifiedAt = relativeParts(verification?.at, now, locale);

  const consumerTools = (consumer: MCPInstanceConsumer) =>
    consumer.enabled_tools == null
      ? t("consumers.allTools")
      : t("consumers.toolCount", { count: consumer.enabled_tools.length });

  return (
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      <OverviewHero
        mark={
          <EntityMark
            identity={mcpIdentity(instance, serverSpec, endpointUrl)}
            className="mt-0.5 h-[34px] w-[34px] shrink-0 rounded-[5px]"
          />
        }
        title={instance.name || t("header.untitled")}
        status={
          <StatusIndicator
            kind={connectionState.kind}
            className="whitespace-nowrap text-[13px] font-medium"
          >
            {tState(connectionState.key)}
          </StatusIndicator>
        }
        description={displayDescription}
        showMoreLabel={t("showMore")}
        showLessLabel={t("showLess")}
        meta={
          <>
            <HeroMeta icon={<ENTITY_ICONS.mcp />}>
              {TRANSPORT_LABEL[instance.transport]}
            </HeroMeta>
            {serverSpec?.version && (
              <HeroMeta icon={<GitBranch />}>v{serverSpec.version}</HeroMeta>
            )}
            {repoUrl && (
              <HeroMeta icon={repoSource === "github" ? <Github /> : <Globe />}>
                <a
                  href={repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={externalLinkClass}
                >
                  {repoSource === "github" ? t("meta.github") : t("meta.repository")}
                </a>
              </HeroMeta>
            )}
            {websiteUrl && (
              <HeroMeta icon={<ExternalLink />}>
                <a
                  href={websiteUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={externalLinkClass}
                >
                  {t("meta.website")}
                </a>
              </HeroMeta>
            )}
          </>
        }
      />

      {/* What needs a hand before anything else on the page. */}
      {(oauthError || isStuck || verifyError ||
        (verification?.status === "failed" && verification.error)) && (
        <div className="mx-4 mt-3 space-y-2 md:shrink-0">
          {oauthError && (
            <FormError>{t("oauth.connectError", { reason: oauthError })}</FormError>
          )}
          {verifyError && <FormError>{verifyError}</FormError>}
          {isStuck && (
            <Alert className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2">
                <TriangleAlert className="h-4 w-4 shrink-0 text-amber-500" />
                {t("verify.stuck")}
              </span>
              <Button
                size="xs"
                variant="outline"
                onClick={handleVerify}
                isLoading={isVerifying}
                disabled={isVerifying}
              >
                {t("verify.verify")}
              </Button>
            </Alert>
          )}
          {verification?.status === "failed" && verification.error && (
            <Alert variant="destructive">
              <TriangleAlert className="h-4 w-4" />
              <AlertTitle>{t("verify.failedTitle")}</AlertTitle>
              <AlertDescription className="space-y-2">
                <p>{verification.error.message}</p>
                {verification.error.code && (
                  <p className="font-mono text-xs opacity-70">
                    {t("verify.code", { code: verification.error.code })}
                  </p>
                )}
                <Button
                  size="xs"
                  variant="outline"
                  onClick={handleVerify}
                  isLoading={isVerifying}
                  disabled={isVerifying}
                >
                  {t("verify.retry")}
                </Button>
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip>
          <Stat
            icon={<Wrench />}
            label={t("stats.tools")}
            value={toolCount}
            bar={null}
            sub={toolCount > 0 ? t("stats.toolsSub") : t("tools.noneDiscovered")}
          />
          <Stat
            icon={<Users />}
            label={t("stats.agents")}
            value={consumers ? consumers.length : "—"}
            bar={null}
            sub={
              !consumers
                ? t("stats.agentsUnknown")
                : consumers.length === 0
                  ? t("stats.agentsNone")
                  : unrestrictedCount > 0
                    ? t("stats.unrestricted", { count: unrestrictedCount })
                    : t("stats.restricted")
            }
          />
          <Stat
            icon={<Activity />}
            label={t("stats.lastCall")}
            value={lastCallAt?.value ?? "—"}
            unit={lastCallAt?.unit}
            bar={null}
            sub={
              lastDispatch ? (
                <StatusIndicator
                  kind={lastDispatch.status === "succeeded" ? "active" : "failed"}
                  size="sm"
                >
                  {lastDispatch.status === "succeeded"
                    ? t("stats.callSucceeded")
                    : t("stats.callFailed")}
                </StatusIndicator>
              ) : (
                tState("neverCalled")
              )
            }
          />
          <Stat
            icon={<ShieldCheck />}
            label={t("stats.verification")}
            value={verifiedAt?.value ?? "—"}
            unit={verifiedAt?.unit}
            bar={null}
            sub={
              <StatusIndicator
                kind={VERIFICATION_KINDS[verificationStatus]}
                size="sm"
              >
                {t(`verification.${verificationStatus}`)}
              </StatusIndicator>
            }
          />
        </StatStrip>

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard>
              <SectionCardHead
                icon={<Link2 />}
                title={t("connection.title")}
              />
              <CardField label={t("connection.connectUrl")}>
                <CopyableText text={agentareaProxyUrl} />
                <p className="note">{t("connection.connectUrlHint")}</p>
              </CardField>

              {isUrlType && endpointUrl && (
                <CardField label={t("connection.endpoint")}>
                  <CopyableText text={endpointUrl} />
                </CardField>
              )}

              {!isCommandType && !isUrlType && containerImage && (
                <CardField label={t("connection.image")}>
                  <CopyableText text={containerImage} />
                </CardField>
              )}
              {!isCommandType && !isUrlType && containerPort && (
                <CardField label={t("container.port")}>
                  <span className="font-mono text-[12.5px]">{containerPort}</span>
                </CardField>
              )}

              {isCommandType && commandStr && (
                <CardField label={t("connection.command")}>
                  <CopyableText text={`${commandStr} ${commandArgs.join(" ")}`.trim()} />
                  <p className="note">{t("command.note")}</p>
                </CardField>
              )}
            </SectionCard>

            {isUrlType && (
              <SectionCard>
                <SectionCardHead
                  icon={<KeyRound />}
                  title={t("connection.headers")}
                  count={headers.length}
                  action={
                    <SectionEditAction
                      open={headersDraft !== null}
                      hasRows={headers.length > 0}
                      busy={isSavingHeaders}
                      onOpen={openHeaders}
                      onCancel={() => setHeadersDraft(null)}
                      onSave={handleSaveHeaders}
                      saveLabel={tConn("saveHeaders")}
                    />
                  }
                />
                {headersDraft !== null ? (
                  <div className="space-y-3 px-[15px] py-3">
                    <CustomHeadersEditor
                      rows={headersDraft}
                      onChange={(rows) => {
                        setSaveConfigError(null);
                        setHeadersDraft(rows);
                      }}
                      stored={headers}
                      alwaysSecret
                    />
                    {saveConfigError && <FormError>{saveConfigError}</FormError>}
                  </div>
                ) : headers.length > 0 ? (
                  <CustomHeadersList headers={headers} />
                ) : (
                  <EmptyRow text={t("connection.noHeaders")} />
                )}
              </SectionCard>
            )}

            {isUrlType && (
              <SectionCard>
                <SectionCardHead icon={<KeyRound />} title={t("authorization.title")} />
                <div className="space-y-2 px-[15px] py-3">
                  {authorization.reachableButUnauthorized && (
                    <p className="note">{t("oauth.unauthorizedNote")}</p>
                  )}
                  <OAuthConnectPanel
                    target={{ kind: "instance", instanceId: instance.id }}
                    isUrlType={isUrlType}
                    onStateChange={setOauthState}
                    onConnectStart={() => setOauthError(null)}
                    bare
                  />
                </div>
              </SectionCard>
            )}

            {isBundleType && bundleMembers.length > 0 && (
              <SectionCard className="[&>a:last-child>div]:border-b-0">
                <SectionCardHead
                  icon={<ENTITY_ICONS.mcp />}
                  title={t("bundle.members")}
                  count={bundleMembers.length}
                />
                {bundleMembers.map((memberId) => (
                  <GlanceRow
                    key={memberId}
                    href={`/connections/${memberId}`}
                    tile={<SoftTile icon={<ENTITY_ICONS.mcp />} />}
                    title={memberNames[memberId] || memberId}
                    sub={t("bundle.memberSub")}
                  />
                ))}
              </SectionCard>
            )}

            <ConnectionCostSection
              cost={instance.cost}
              managedBy={instance.managed_by}
              onSave={async (cost) => {
                const { updateMCPServerInstanceAction } = await import(
                  "@/lib/server-actions"
                );
                return updateMCPServerInstanceAction(instance.id, { cost });
              }}
              onSaved={() => router.refresh()}
            />
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard className="[&>a:last-child>div]:border-b-0">
              <SectionCardHead
                icon={<Users />}
                title={t("consumers.heading")}
                count={consumers?.length}
                link={{
                  label: t("tabs.tools"),
                  href: `/connections/${instance.id}/tools`,
                }}
              />
              {consumersError ? (
                <div className="px-[15px] py-3 [&>div]:mb-0">
                  <SectionLoadError message={consumersError} />
                </div>
              ) : !consumers || consumers.length === 0 ? (
                <EmptyRow text={t("consumers.empty")} />
              ) : (
                consumers.map((consumer) => (
                  <GlanceRow
                    key={consumer.agent_id}
                    href={`/agents/${consumer.agent_slug ?? consumer.agent_id}`}
                    tile={<SoftTile icon={<ENTITY_ICONS.agent />} />}
                    title={consumer.agent_name}
                    sub={consumerTools(consumer)}
                  />
                ))
              )}
            </SectionCard>

            {Object.keys(envVars).length > 0 && (
              <SectionCard>
                <SectionCardHead
                  icon={<KeyRound />}
                  title={t("env.title")}
                  count={Object.keys(envVars).length}
                />
                {Object.entries(envVars).map(([key, value]) => (
                  <FactRow
                    key={key}
                    title={<span className="font-mono">{key}</span>}
                    trailing={
                      value ? (
                        <span className="font-mono">{value}</span>
                      ) : (
                        <span className="italic">{t("env.notSet")}</span>
                      )
                    }
                  />
                ))}
              </SectionCard>
            )}

            <ConnectionDetailsCard
              id={instance.id}
              createdAt={instance.created_at}
              updatedAt={instance.updated_at}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
