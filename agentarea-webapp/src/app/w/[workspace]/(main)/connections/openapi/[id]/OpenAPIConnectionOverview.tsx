"use client";

import { useLocale, useNow, useTranslations } from "next-intl";
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
import { DetailsCard } from "@/components/Overview/DetailsCard";
import {
  CardField,
  HeroMeta,
  SectionCard,
  SectionCardHead,
  Stat,
  StatStrip,
} from "@/components/Overview/OverviewCard";
import { OverviewHero } from "@/components/Overview/OverviewHero";
import { CopyableText } from "@/components/ui/copyable-text";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getOpenApiConnectionDisplayStatus } from "@/lib/status";
import { useClientApiUrl } from "@/lib/use-client-api-url";
import { OpenAPIConnectionMark } from "../../components/MCPCard";
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

export default function OpenAPIConnectionOverview({
  connection,
}: {
  connection: OpenAPIConnection;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tDetail = useTranslations("MCPServersPage.instanceDetail");
  const tState = useTranslations("MCPServersPage.state");
  const locale = useLocale();
  const now = useNow({ updateInterval: 60_000 });
  const apiBaseUrl = useClientApiUrl();
  // The address every connection answers MCP at; a platform-managed one has none.
  const connectUrl =
    connection.managed_by === "platform"
      ? null
      : `${apiBaseUrl}/v1/mcp/${connection.id}/mcp`;

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
            {connection.base_url && (
              <HeroMeta icon={<Globe />}>
                {hostOf(connection.base_url)}
              </HeroMeta>
            )}
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

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip>
          <Stat
            icon={<Wrench />}
            label={tDetail("stats.tools")}
            value={toolCount}
            bar={null}
            sub={
              connection.spec_url
                ? t("stats.fromSpecUrl")
                : t("stats.fromSpecJson")
            }
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
                  kind={
                    lastDispatch.status === "succeeded" ? "active" : "failed"
                  }
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
            <SectionCard>
              <SectionCardHead
                icon={<Link2 />}
                title={tDetail("connection.title")}
              />
              {connectUrl && (
                <CardField label={tDetail("connection.connectUrl")}>
                  <CopyableText text={connectUrl} />
                  <p className="note">{tDetail("connection.connectUrlHint")}</p>
                </CardField>
              )}
              <CardField label={t("baseUrl")}>
                {connection.base_url ? (
                  <CopyableText text={connection.base_url} />
                ) : (
                  <p className="text-[12.5px] text-muted-foreground">
                    {t("baseUrlByPlatform")}
                  </p>
                )}
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
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <DetailsCard
              idLabel={tDetail("details.id")}
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
