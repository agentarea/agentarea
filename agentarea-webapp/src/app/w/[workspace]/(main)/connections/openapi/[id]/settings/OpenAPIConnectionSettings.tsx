"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { KeyRound, SlidersHorizontal } from "lucide-react";
import FormError from "@/components/FormError";
import {
  EmptyRow,
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { updateOpenAPIConnectionAction } from "@/lib/server-actions";
import { ConnectionCostSection } from "../../../components/ConnectionCostSection";
import {
  cleanHeaderRows,
  CustomHeadersEditor,
  toHeaderRows,
} from "../../../components/CustomHeadersEditor";
import { CustomHeadersList } from "../../../components/CustomHeadersList";
import {
  cleanQueryParamRows,
  CustomQueryParamsEditor,
  toQueryParamRows,
} from "../../../components/CustomQueryParamsEditor";
import type { HeaderRow } from "../../../components/HeaderRows";
import type { SecretRow } from "../../../components/SecretRows";
import { SectionEditAction } from "../../../components/SectionEditAction";
import { OAuthConnectPanel } from "../../../OAuthConnectPanel";
import type { OpenAPIConnection } from "../../../types";

type Section = "headers" | "queryParams";

export default function OpenAPIConnectionSettings({
  connection,
}: {
  connection: OpenAPIConnection;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tDetail = useTranslations("MCPServersPage.instanceDetail");
  const tConn = useTranslations("OpenAPIConnection");
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
      router.replace(`/connections/openapi/${connection.id}/settings`, {
        scroll: false,
      });
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

  const headers = connection.custom_headers ?? [];
  const queryParams = connection.custom_query_params ?? [];
  // A catalog API signed in to with OAuth, or still waiting for its first sign-in;
  // an API-key one has neither.
  const signsInWithOAuth =
    Boolean(connection.registry_item_id) &&
    (Boolean(connection.auth_config_id) || connection.status === "pending");

  return (
    <div className="h-full overflow-y-auto bg-muted/20 px-4 py-5 font-inter">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
        {oauthError && (
          <FormError>{t("oauthError", { reason: oauthError })}</FormError>
        )}
        {error && <FormError>{error}</FormError>}

        {signsInWithOAuth && (
          <SectionCard>
            <SectionCardHead
              icon={<KeyRound />}
              title={tDetail("authorization.title")}
            />
            <div className="space-y-2 px-[15px] py-3">
              <OAuthConnectPanel
                target={{
                  kind: "api_connection",
                  connectionId: connection.id,
                }}
                isUrlType
                bare
              />
            </div>
          </SectionCard>
        )}

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
                    {
                      custom_query_params: cleanQueryParamRows(
                        queryDraft ?? []
                      ),
                    },
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

        <ConnectionCostSection
          cost={connection.cost}
          managedBy={connection.managed_by}
          onSave={(cost) =>
            updateOpenAPIConnectionAction(connection.id, { cost })
          }
          onSaved={() => router.refresh()}
        />
      </div>
    </div>
  );
}
