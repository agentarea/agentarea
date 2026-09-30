"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { FileX, Pencil, RefreshCw, Trash2 } from "lucide-react";
import BaseModal from "@/components/BaseModal";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import FormError from "@/components/FormError";
import { DetailSkeleton } from "@/components/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { apiErrorMessage, formatApiError, isApiNotFound } from "@/lib/api-errors";
import {
  getOpenApiConnectionDisplayStatus,
  getOpenApiConnectionStatusPresentation,
} from "@/lib/status";
import {
  deleteOpenAPIConnectionAction as deleteOpenAPIConnection,
  discoverOpenAPIToolsAction as discoverOpenAPITools,
  getOpenAPIConnectionAction as getOpenAPIConnection,
  updateOpenAPIConnectionAction as updateOpenAPIConnection,
} from "@/lib/server-actions";
import { CustomHeadersEditor } from "../../components/CustomHeadersEditor";
import { CustomHeadersList } from "../../components/CustomHeadersList";
import { OpenAPIConnectionMark } from "../../components/MCPCard";
import { ToolsTable } from "../../components/ToolsTable";
import { OpenAPIConnection } from "../../types";

export default function OpenAPIConnectionDetailPage() {
  const params = useParams();
  const router = useWorkspaceRouter();
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tPage = useTranslations("MCPServersPage");
  const tCommon = useTranslations("Common");
  const connectionId = params.id as string;

  const [connection, setConnection] = useState<OpenAPIConnection | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingHeaders, setEditingHeaders] = useState(false);
  const [savingHeaders, setSavingHeaders] = useState(false);
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError, setOauthError] = useState<string | null>(null);

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const oauthResult = searchParams.get("oauth");
    if (!oauthResult) return;
    if (oauthResult === "error") {
      setOauthError(searchParams.get("reason") || "unknown");
    }
    router.replace(`/connections/openapi/${connectionId}`, { scroll: false });
  }, [connectionId, router]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setLoadError(null);
      setNotFound(false);
      try {
        const result = await getOpenAPIConnection(connectionId);
        if (result.error || !result.data) {
          if (isApiNotFound(result)) setNotFound(true);
          else setLoadError(apiErrorMessage(result, t("errors.loadFailed")));
        } else {
          setConnection(result.data as OpenAPIConnection);
        }
      } catch (err) {
        console.error("Failed to load OpenAPI connection", err);
        setLoadError(`${t("errors.loadFailed")}: ${formatApiError(err)}`);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [connectionId, reloadKey, t]);

  const reloadConnection = async () => {
    const result = await getOpenAPIConnection(connectionId);
    if (result.error || !result.data) {
      setError(apiErrorMessage(result, t("errors.reloadFailed")));
      return false;
    }
    setConnection(result.data as OpenAPIConnection);
    return true;
  };

  const handleDiscover = async () => {
    setDiscovering(true);
    setError(null);
    setOauthError(null);
    try {
      const result = await discoverOpenAPITools(connectionId);
      if (result.error) {
        setError(apiErrorMessage(result, t("errors.discoverFailed")));
        return;
      }
      await reloadConnection();
    } catch (err) {
      console.error("Failed to discover tools", err);
      setError(`${t("errors.discoverFailed")}: ${formatApiError(err)}`);
    } finally {
      setDiscovering(false);
    }
  };

  const handleSaveHeaders = async (rows: { name: string; value: string }[]) => {
    setSavingHeaders(true);
    setError(null);
    try {
      const result = await updateOpenAPIConnection(connectionId, {
        custom_headers: rows,
      });
      if (result.error) {
        setError(apiErrorMessage(result, t("errors.saveHeadersFailed")));
        return;
      }
      if (await reloadConnection()) setEditingHeaders(false);
    } catch (err) {
      console.error("Failed to save headers", err);
      setError(`${t("errors.saveHeadersFailed")}: ${formatApiError(err)}`);
    } finally {
      setSavingHeaders(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      const result = await deleteOpenAPIConnection(connectionId);
      if (result.error) {
        setError(apiErrorMessage(result, t("errors.deleteFailed")));
        setDeleting(false);
        return;
      }
      router.push("/connections");
      router.refresh();
    } catch (err) {
      console.error("Failed to delete connection", err);
      setError(`${t("errors.deleteFailed")}: ${formatApiError(err)}`);
      setDeleting(false);
    }
  };

  const breadcrumbRoot = { label: tPage("title"), href: "/connections" };

  if (loading) {
    return (
      <ContentBlock header={{ breadcrumb: [breadcrumbRoot] }}>
        <DetailSkeleton />
      </ContentBlock>
    );
  }

  if (!connection) {
    return (
      <ContentBlock header={{ breadcrumb: [breadcrumbRoot] }}>
        <div className="flex h-64 items-center justify-center">
          {loadError ? (
            <EmptyState
              title={t("errors.loadFailed")}
              description={loadError}
              icons={[FileX]}
              action={{
                label: tCommon("retry"),
                onClick: () => setReloadKey((key) => key + 1),
              }}
            />
          ) : (
            <EmptyState
              title={notFound ? t("notFound") : t("errors.loadFailed")}
              description=""
              icons={[FileX]}
              action={{
                label: t("back"),
                onClick: () => router.push("/connections"),
              }}
            />
          )}
        </div>
      </ContentBlock>
    );
  }

  const statusPresentation = getOpenApiConnectionStatusPresentation(
    getOpenApiConnectionDisplayStatus(
      connection.status,
      connection.available_tools.length
    )
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [breadcrumbRoot, { label: connection.name }],
        description: connection.description || connection.base_url,
        backLink: { label: t("back"), href: "/connections" },
        controls: (
          <div className="flex gap-2">
            {connection.spec_url && (
              <Button
                size="xs"
                variant="outline"
                onClick={handleDiscover}
                disabled={discovering}
              >
                <RefreshCw
                  className={`mr-1 ${discovering ? "animate-spin" : ""}`}
                />
                {discovering ? t("refreshing") : t("refreshFromSpec")}
              </Button>
            )}
            <BaseModal
              type="delete"
              title={t("deleteTitle")}
              description={tCommon("deleteDescription", {
                itemName: connection.name,
              })}
              onConfirm={handleDelete}
            >
              <Button size="xs" variant="destructive" disabled={deleting}>
                <Trash2 className="mr-1" />
                {deleting ? t("deleting") : tCommon("delete")}
              </Button>
            </BaseModal>
          </div>
        ),
      }}
    >
      <div className="space-y-6">
        {oauthError && (
          <FormError>{t("oauthError", { reason: oauthError })}</FormError>
        )}
        {error && <FormError>{error}</FormError>}

        {/* Info */}
        <div className="grid grid-cols-2 gap-4 rounded-lg border p-4">
          <div>
            <p className="text-xs text-muted-foreground">{t("type")}</p>
            <div className="mt-1 flex items-center gap-1.5">
              <OpenAPIConnectionMark
                connection={connection}
                className="h-4 w-4 rounded-sm text-[6px]"
              />
              <Badge
                variant="outline"
                className="border-orange-300 text-orange-600"
              >
                OpenAPI
              </Badge>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("status")}</p>
            <div className="mt-1">
              <StatusIndicator kind={statusPresentation.kind}>
                {statusPresentation.label}
              </StatusIndicator>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("baseUrl")}</p>
            <p className="mt-1 font-mono text-sm">{connection.base_url}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{t("specUrl")}</p>
            <p className="mt-1 font-mono text-sm truncate">
              {connection.spec_url || "—"}
            </p>
          </div>
        </div>

        {/* Custom Headers */}
        <div className="space-y-2">
          {editingHeaders ? (
            <CustomHeadersEditor
              initial={connection.custom_headers || []}
              saving={savingHeaders}
              onSave={handleSaveHeaders}
              onCancel={() => setEditingHeaders(false)}
            />
          ) : (
            <>
              <div className="flex items-center justify-between">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {t("customHeaders", {
                    count: connection.custom_headers?.length ?? 0,
                  })}
                </div>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => setEditingHeaders(true)}
                >
                  <Pencil className="mr-1" />
                  {connection.custom_headers &&
                  connection.custom_headers.length > 0
                    ? tCommon("edit")
                    : tCommon("add")}
                </Button>
              </div>
              {connection.custom_headers &&
              connection.custom_headers.length > 0 ? (
                <CustomHeadersList headers={connection.custom_headers} />
              ) : (
                <p className="text-xs text-muted-foreground">
                  {t("noCustomHeaders")}
                </p>
              )}
            </>
          )}
        </div>

        {/* Tools */}
        {connection.available_tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {connection.spec_url ? t("noToolsWithSpec") : t("noTools")}
          </p>
        ) : (
          <ToolsTable
            tools={connection.available_tools}
            label={t("availableTools", {
              count: connection.available_tools.length,
            })}
          />
        )}
      </div>
    </ContentBlock>
  );
}
