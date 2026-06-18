"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Pencil, RefreshCw, Trash2 } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { formatApiError } from "@/lib/api-errors";
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
  const router = useRouter();
  const connectionId = params.id as string;

  const [connection, setConnection] = useState<OpenAPIConnection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingHeaders, setEditingHeaders] = useState(false);
  const [savingHeaders, setSavingHeaders] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const result = await getOpenAPIConnection(connectionId);
        if (result.error || !result.data) {
          setError(
            result.status === 404
              ? "Connection not found"
              : `Failed to load connection${result.status ? ` (${result.status})` : ""}: ${formatApiError(result)}`
          );
        } else {
          setConnection(result.data as any);
        }
      } catch (err) {
        console.error("Failed to load OpenAPI connection", err);
        setError(
          err instanceof Error ? err.message : "Failed to load connection"
        );
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [connectionId]);

  const handleDiscover = async () => {
    setDiscovering(true);
    setError(null);
    try {
      const { error: discoverError } = await discoverOpenAPITools(connectionId);
      if (discoverError) {
        setError((discoverError as any)?.detail || "Failed to discover tools");
        return;
      }
      const result = await getOpenAPIConnection(connectionId);
      if (result.error || !result.data) {
        setError(
          result.status === 404
            ? "Connection not found"
            : `Failed to reload connection${result.status ? ` (${result.status})` : ""}: ${formatApiError(result)}`
        );
      } else {
        setConnection(result.data as any);
      }
    } catch (err) {
      console.error("Failed to discover tools", err);
      setError(err instanceof Error ? err.message : "Failed to discover tools");
    } finally {
      setDiscovering(false);
    }
  };

  const handleSaveHeaders = async (rows: { name: string; value: string }[]) => {
    setSavingHeaders(true);
    setError(null);
    try {
      const { error: saveError } = await updateOpenAPIConnection(connectionId, {
        custom_headers: rows,
      });
      if (saveError) {
        setError((saveError as any)?.detail || "Failed to save headers");
        return;
      }
      const result = await getOpenAPIConnection(connectionId);
      if (result.error || !result.data) {
        setError(
          result.status === 404
            ? "Connection not found"
            : `Failed to reload connection${result.status ? ` (${result.status})` : ""}: ${formatApiError(result)}`
        );
      } else {
        setConnection(result.data as any);
        setEditingHeaders(false);
      }
    } catch (err) {
      console.error("Failed to save headers", err);
      setError(err instanceof Error ? err.message : "Failed to save headers");
    } finally {
      setSavingHeaders(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Delete this connection?")) return;
    setDeleting(true);
    setError(null);
    try {
      const { error: deleteError } =
        await deleteOpenAPIConnection(connectionId);
      if (deleteError) {
        setError((deleteError as any)?.detail || "Failed to delete connection");
        setDeleting(false);
        return;
      }
      router.push("/mcp-servers");
      router.refresh();
    } catch (err) {
      console.error("Failed to delete connection", err);
      setError(
        err instanceof Error ? err.message : "Failed to delete connection"
      );
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !connection) {
    return <div className="p-8 text-center text-destructive">{error}</div>;
  }

  if (!connection) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        Connection not found
      </div>
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
        breadcrumb: [
          { label: "Connections", href: "/mcp-servers" },
          { label: connection.name },
        ],
        description: connection.description || connection.base_url,
        backLink: { label: "Back to Connections", href: "/mcp-servers" },
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
                  className={`mr-1 h-3.5 w-3.5 ${discovering ? "animate-spin" : ""}`}
                />
                {discovering ? "Refreshing..." : "Refresh from Spec URL"}
              </Button>
            )}
            <Button
              size="xs"
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </div>
        ),
      }}
    >
      <div className="space-y-6">
        {/* Error banner */}
        {error && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Info */}
        <div className="grid grid-cols-2 gap-4 rounded-lg border p-4">
          <div>
            <p className="text-xs text-muted-foreground">Type</p>
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
            <p className="text-xs text-muted-foreground">Status</p>
            <div className="mt-1">
              <StatusIndicator
                tone={statusPresentation.tone}
                pulse={statusPresentation.pulse}
              >
                {statusPresentation.label}
              </StatusIndicator>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Base URL</p>
            <p className="mt-1 font-mono text-sm">{connection.base_url}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Spec URL</p>
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
                  {`Custom Headers (${connection.custom_headers?.length ?? 0})`}
                </div>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => setEditingHeaders(true)}
                >
                  <Pencil className="mr-1 h-3 w-3" />
                  {connection.custom_headers &&
                  connection.custom_headers.length > 0
                    ? "Edit"
                    : "Add"}
                </Button>
              </div>
              {connection.custom_headers &&
              connection.custom_headers.length > 0 ? (
                <CustomHeadersList headers={connection.custom_headers} />
              ) : (
                <p className="text-xs text-muted-foreground">
                  No custom headers. Click Add to set Authorization or any other
                  request header your provider needs.
                </p>
              )}
            </>
          )}
        </div>

        {/* Tools */}
        {connection.available_tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {connection.spec_url
              ? "No tools discovered yet. Click \u201CRefresh from Spec URL\u201D to re-parse the spec."
              : "No tools parsed from this spec."}
          </p>
        ) : (
          <ToolsTable
            tools={connection.available_tools}
            label={`Available Tools (${connection.available_tools.length})`}
          />
        )}
      </div>
    </ContentBlock>
  );
}
