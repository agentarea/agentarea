"use client";

import { useEffect, useState } from "react";
import { useLocale, useNow, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import {
  Activity,
  ExternalLink,
  FileJson,
  Globe,
  KeyRound,
  Link2,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";
import FormError from "@/components/FormError";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import {
  EmptyRow,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import { CopyableText } from "@/components/ui/copyable-text";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { updateOpenAPIConnectionAction } from "@/lib/server-actions";
import { getOpenApiConnectionDisplayStatus } from "@/lib/status";
import { CardField, ConnectionDetailsCard } from "../../components/ConnectionCards";
import {
  cleanHeaderRows,
  CustomHeadersEditor,
  toHeaderRows,
} from "../../components/CustomHeadersEditor";
import { CustomHeadersList } from "../../components/CustomHeadersList";
import { SectionEditAction } from "../../components/SectionEditAction";
import {
  cleanQueryParamRows,
  CustomQueryParamsEditor,
  toQueryParamRows,
} from "../../components/CustomQueryParamsEditor";
import { OpenAPIConnectionMark } from "../../components/MCPCard";
import type { HeaderRow } from "../../components/HeaderRows";
import type { SecretRow } from "../../components/SecretRows";
import { relativeParts } from "../../relative-parts";
import { getOpenApiConnectionState } from "../../state";
import type { OpenAPIConnection } from "../../types";
import { readLastDispatch } from "../../usage";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0];
  }
}

const externalLinkClass =
  "font-medium text-foreground/80 underline-offset-2 hover:underline";

type Section = "headers" | "queryParams";

export default function OpenAPIConnectionOverview({
  connection,
}: {
  connection: OpenAPIConnection;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tDetail = useTranslations("MCPServersPage.instanceDetail");
  const tState = useTranslations("MCPServersPage.state");
  const tConn = useTranslations("OpenAPIConnection");
  const locale = useLocale();
  const now = useNow({ updateInterval: 60_000 });
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  // One draft per section, null while it is not being edited: the two edit
  // independently, so opening one never discards what is typed in the other.
  const [headersDraft, setHeadersDraft] = useState<HeaderRow[] | null>(null);
  const [queryDraft, setQueryDraft] = useState<SecretRow[] | null>(null);
  const [saving, setSaving] = useState<Section | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError] = useState<string | null>(() =>
    searchParams.get("oauth") === "error"
      ? searchParams.get("reason") || "unknown"
      : null
  );

  useEffect(() => {
    if (searchParams.get("oauth")) {
      router.replace(`/connections/openapi/${connection.id}`, { scroll: false });
    }
  }, [searchParams, connection.id, router]);

  const save = async (
    section: Section,
    body: Parameters<typeof updateOpenAPIConnectionAction>[1],
    close: () => void
  ) => {
    const failedKey =
      section === "headers" ? "saveHeadersFailed" : "saveQueryParamsFailed";
    setSaving(section);
    setError(null);
    try {
      const result = await updateOpenAPIConnectionAction(connection.id, body);
      if (result.error) {
        setError(apiErrorMessage(result, t(`errors.${failedKey}`)));
        return;
      }
      close();
      router.refresh();
    } catch (err) {
      console.error("Failed to save OpenAPI connection", err);
      setError(`${t(`errors.${failedKey}`)}: ${formatApiError(err)}`);
    } finally {
      setSaving(null);
    }
  };

  const toolCount = connection.available_tools.length;
  const headers = connection.custom_headers ?? [];
  const queryParams = connection.custom_query_params ?? [];
  const secretCount = (rows: { secret: boolean }[]) =>
    rows.filter((row) => row.secret).length;

  // The same verdict the connections list shows, so the two never disagree.
  const connectionState = getOpenApiConnectionState(
    getOpenApiConnectionDisplayStatus(connection.status, toolCount),
    toolCount,
    connection.last_dispatch
  );
  const lastDispatch = readLastDispatch(connection.last_dispatch);
  const lastCallAt = relativeParts(lastDispatch?.at, now, locale);

  return (
    <div className="font-inter md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden">
      <OverviewHero
        mark={
          <OpenAPIConnectionMark
            connection={connection}
            className="mt-0.5 h-[34px] w-[34px] rounded-[5px] text-[11px]"
          />
        }
        title={connection.name}
        status={
          <StatusIndicator
            kind={connectionState.kind}
            className="whitespace-nowrap text-[13px] font-medium"
          >
            {tState(connectionState.key)}
          </StatusIndicator>
        }
        description={connection.description}
        showMoreLabel={tDetail("showMore")}
        showLessLabel={tDetail("showLess")}
        meta={
          <>
            <HeroMeta icon={<FileJson />}>OpenAPI</HeroMeta>
            <HeroMeta icon={<Globe />}>{hostOf(connection.base_url)}</HeroMeta>
            {connection.spec_url && (
              <HeroMeta icon={<ExternalLink />}>
                <a
                  href={connection.spec_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={externalLinkClass}
                >
                  {t("specLink")}
                </a>
              </HeroMeta>
            )}
          </>
        }
      />

      {oauthError && (
        <div className="mx-4 mt-3 md:shrink-0">
          <FormError>{t("oauthError", { reason: oauthError })}</FormError>
        </div>
      )}

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip>
          <Stat
            icon={<Wrench />}
            label={tDetail("stats.tools")}
            value={toolCount}
            bar={null}
            sub={connection.spec_url ? t("stats.fromSpecUrl") : t("stats.fromSpecJson")}
          />
          <Stat
            icon={<Activity />}
            label={tDetail("stats.lastCall")}
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
                    ? tDetail("stats.callSucceeded")
                    : tDetail("stats.callFailed")}
                </StatusIndicator>
              ) : (
                tState("neverCalled")
              )
            }
          />
          <Stat
            icon={<KeyRound />}
            label={t("stats.headers")}
            value={headers.length}
            bar={null}
            sub={t("stats.secretCount", { count: secretCount(headers) })}
          />
          <Stat
            icon={<SlidersHorizontal />}
            label={t("stats.queryParams")}
            value={queryParams.length}
            bar={null}
            sub={t("stats.secretCount", { count: secretCount(queryParams) })}
          />
        </StatStrip>

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            {error && <FormError>{error}</FormError>}

            <SectionCard>
              <SectionCardHead icon={<Link2 />} title={tDetail("connection.title")} />
              <CardField label={t("baseUrl")}>
                <CopyableText text={connection.base_url} />
              </CardField>
              <CardField label={t("specUrl")}>
                {connection.spec_url ? (
                  <CopyableText text={connection.spec_url} />
                ) : (
                  <p className="text-[12.5px] text-muted-foreground">
                    {t("specPasted")}
                  </p>
                )}
              </CardField>
            </SectionCard>

            <SectionCard>
              <SectionCardHead
                icon={<KeyRound />}
                title={t("headersTitle")}
                count={headers.length}
                action={
                  <SectionEditAction
                    open={headersDraft !== null}
                    hasRows={headers.length > 0}
                    busy={saving === "headers"}
                    onOpen={() => {
                      setError(null);
                      setHeadersDraft(toHeaderRows(headers));
                    }}
                    onCancel={() => setHeadersDraft(null)}
                    onSave={() =>
                      save(
                        "headers",
                        { custom_headers: cleanHeaderRows(headersDraft ?? []) },
                        () => setHeadersDraft(null)
                      )
                    }
                    saveLabel={tConn("saveHeaders")}
                  />
                }
              />
              {headersDraft !== null ? (
                <div className="px-[15px] py-3">
                  <CustomHeadersEditor
                    rows={headersDraft}
                    onChange={setHeadersDraft}
                    stored={headers}
                  />
                </div>
              ) : headers.length > 0 ? (
                <CustomHeadersList headers={headers} />
              ) : (
                <EmptyRow text={t("noCustomHeaders")} />
              )}
            </SectionCard>

            <SectionCard>
              <SectionCardHead
                icon={<SlidersHorizontal />}
                title={t("queryParamsTitle")}
                count={queryParams.length}
                action={
                  <SectionEditAction
                    open={queryDraft !== null}
                    hasRows={queryParams.length > 0}
                    busy={saving === "queryParams"}
                    onOpen={() => {
                      setError(null);
                      setQueryDraft(toQueryParamRows(queryParams));
                    }}
                    onCancel={() => setQueryDraft(null)}
                    onSave={() =>
                      save(
                        "queryParams",
                        { custom_query_params: cleanQueryParamRows(queryDraft ?? []) },
                        () => setQueryDraft(null)
                      )
                    }
                    saveLabel={tConn("saveQueryParams")}
                  />
                }
              />
              {queryDraft !== null ? (
                <div className="px-[15px] py-3">
                  <CustomQueryParamsEditor
                    rows={queryDraft}
                    onChange={setQueryDraft}
                    stored={queryParams}
                  />
                </div>
              ) : queryParams.length > 0 ? (
                <CustomHeadersList headers={queryParams} />
              ) : (
                <EmptyRow text={t("noCustomQueryParams")} />
              )}
            </SectionCard>
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <ConnectionDetailsCard
              id={connection.id}
              createdAt={connection.created_at}
              updatedAt={connection.updated_at}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
