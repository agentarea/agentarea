"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import FormError from "@/components/FormError";
import {
  EmptyRow,
  FactRow,
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { ConnectionCostSection } from "../../components/ConnectionCostSection";
import {
  CustomHeadersEditor,
  toHeaderRows,
} from "../../components/CustomHeadersEditor";
import { CustomHeadersList } from "../../components/CustomHeadersList";
import { EgressExitSection } from "../../components/EgressExitSection";
import type { HeaderRow } from "../../components/HeaderRows";
import { SectionEditAction } from "../../components/SectionEditAction";
import {
  headersUpdateSpec,
  remoteHeaderFields,
  storedHeaders,
} from "../../credential-fields";
import { boundEgressExit, type EgressExitChoices } from "../../egress-exit";
import {
  summarizeAuthorization,
  type OAuthConnectState,
} from "../../oauth-connect-state";
import { OAuthConnectPanel } from "../../OAuthConnectPanel";
import type { MCPInstance, MCPServer } from "../../types";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
  /** Null when the connection cannot have one or the deployment has none. */
  egressExits: EgressExitChoices | null;
}

export default function MCPInstanceSettings({
  instance,
  serverSpec,
  egressExits,
}: Props) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const tConn = useTranslations("OpenAPIConnection");
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError, setOauthError] = useState<string | null>(() =>
    searchParams.get("oauth") === "error"
      ? searchParams.get("reason") || "unknown"
      : null
  );
  const [oauthState, setOauthState] = useState<OAuthConnectState | undefined>();
  // The headers draft, null while they are not being edited.
  const [headersDraft, setHeadersDraft] = useState<HeaderRow[] | null>(null);
  const [isSavingHeaders, setIsSavingHeaders] = useState(false);
  const [saveConfigError, setSaveConfigError] = useState<string | null>(null);

  useEffect(() => {
    if (searchParams.get("oauth")) {
      router.replace(`/connections/${instance.id}/settings`, { scroll: false });
    }
  }, [searchParams, instance.id, router]);

  const isUrlType = instance.transport === "url";
  const headers = storedHeaders(instance.json_spec ?? {});
  const authorization = summarizeAuthorization({
    isUrlType,
    verificationStatus: (
      instance.verification as { status?: string } | null | undefined
    )?.status,
    connected: !!instance.auth_config_id,
    oauthState: oauthState?.kind,
  });

  const plainEnvVars = (instance.json_spec?.environment ?? {}) as Record<
    string,
    string | { secret_name?: string }
  >;
  const secretEnvNames = (instance.json_spec?.env_vars ?? []) as string[];
  // Merge non-secret env vars with secret env vars (masked); a workspace
  // secret reference shows as the ${secret.<name>} it was written as.
  const envVars: Record<string, string> = Object.fromEntries(
    Object.entries(plainEnvVars).map(([name, value]) => [
      name,
      typeof value === "string"
        ? value
        : `\${secret.${value?.secret_name ?? ""}}`,
    ])
  );
  for (const name of secretEnvNames) {
    if (!(name in envVars)) {
      envVars[name] = "******";
    }
  }

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
        json_spec: headersUpdateSpec(
          instance.json_spec ?? {},
          headersDraft ?? []
        ),
      });
      if (result.error) {
        setSaveConfigError(
          apiErrorMessage(result, t("errors.saveConfigFailed"))
        );
        return;
      }
      setHeadersDraft(null);
      router.refresh();
    } catch (err) {
      console.error("Failed to save MCP instance headers", err);
      setSaveConfigError(
        `${t("errors.saveConfigFailed")}: ${formatApiError(err)}`
      );
    } finally {
      setIsSavingHeaders(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-muted/20 px-4 py-5 font-inter">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
        {oauthError && (
          <FormError>
            {t("oauth.connectError", { reason: oauthError })}
          </FormError>
        )}

        {isUrlType && (
          <SectionCard>
            <SectionCardHead
              icon={<KeyRound />}
              title={t("authorization.title")}
            />
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

        {egressExits && (
          <EgressExitSection
            instanceId={instance.id}
            boundExitId={boundEgressExit(instance.json_spec ?? {})}
            choices={egressExits}
          />
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
    </div>
  );
}
