"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { FileJson2, Trash2, RefreshCw, ExternalLink, Lock } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getOpenAPIConnectionAction as getOpenAPIConnection,
  deleteOpenAPIConnectionAction as deleteOpenAPIConnection,
  discoverOpenAPIToolsAction as discoverOpenAPITools,
  testOpenAPIConnectionAction as testOpenAPIConnection,
} from "@/lib/server-actions";
import { OpenAPIConnection } from "../../types";

export default function OpenAPIConnectionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const connectionId = params.id as string;

  const [connection, setConnection] = useState<OpenAPIConnection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; status_code?: number; error?: string } | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const { data, error: loadError } = await getOpenAPIConnection(connectionId);
        if (loadError) {
          setError((loadError as any)?.detail || "Failed to load connection");
        } else {
          setConnection(data as any);
        }
      } catch {
        setError("Failed to load connection");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [connectionId]);

  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      await discoverOpenAPITools(connectionId);
      const { data, error: loadError } = await getOpenAPIConnection(connectionId);
      if (loadError) {
        setError((loadError as any)?.detail || "Failed to reload connection");
      } else {
        setConnection(data as any);
      }
    } catch {
      setError("Failed to discover tools");
    } finally {
      setDiscovering(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data, error: testError } = await testOpenAPIConnection(connectionId);
      if (testError) {
        setError((testError as any)?.detail || "Failed to test connection");
      } else {
        setTestResult(data as any);
      }
    } catch {
      setError("Failed to test connection");
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Delete this connection?")) return;
    setDeleting(true);
    try {
      await deleteOpenAPIConnection(connectionId);
      router.push("/mcp-servers");
      router.refresh();
    } catch {
      setError("Failed to delete connection");
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
    return <div className="p-8 text-center text-muted-foreground">Connection not found</div>;
  }

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
            <Button size="xs" variant="outline" onClick={handleTest} disabled={testing}>
              <ExternalLink className="mr-1 h-3.5 w-3.5" />
              {testing ? "Testing..." : "Test"}
            </Button>
            <Button size="xs" variant="outline" onClick={handleDiscover} disabled={discovering}>
              <RefreshCw className={`mr-1 h-3.5 w-3.5 ${discovering ? "animate-spin" : ""}`} />
              {discovering ? "Discovering..." : "Discover Tools"}
            </Button>
            <Button size="xs" variant="destructive" onClick={handleDelete} disabled={deleting}>
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
              <FileJson2 className="h-4 w-4 text-orange-500" />
              <Badge variant="outline" className="text-orange-600 border-orange-300">OpenAPI</Badge>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Status</p>
            <Badge variant={connection.status === "active" ? "success" : "destructive"} className="mt-1">
              {connection.status}
            </Badge>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Base URL</p>
            <p className="mt-1 font-mono text-sm">{connection.base_url}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Spec URL</p>
            <p className="mt-1 font-mono text-sm truncate">{connection.spec_url || "—"}</p>
          </div>
        </div>

        {/* Test result */}
        {testResult && (
          <div className={`rounded-lg border p-4 ${
            testResult.status === "reachable"
              ? "border-green-300 bg-green-50 dark:bg-green-950/20"
              : testResult.status === "auth_error"
                ? "border-amber-300 bg-amber-50 dark:bg-amber-950/20"
                : "border-red-300 bg-red-50 dark:bg-red-950/20"
          }`}>
            <p className="text-sm font-medium">
              {testResult.status === "reachable"
                ? `Reachable (HTTP ${testResult.status_code})`
                : testResult.status === "auth_error"
                  ? `Authentication error (HTTP ${testResult.status_code}) — check your headers`
                  : testResult.status === "server_error"
                    ? `Server error (HTTP ${testResult.status_code})`
                    : `Unreachable: ${testResult.error}`}
            </p>
          </div>
        )}

        {/* Tools */}
        <div>
          <h3 className="mb-3 text-sm font-medium">
            Available Tools ({connection.available_tools.length})
          </h3>
          {connection.available_tools.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No tools discovered yet. Click &quot;Discover Tools&quot; to parse the OpenAPI spec.
            </p>
          ) : (
            <div className="grid gap-2">
              {connection.available_tools.map((tool) => (
                <div key={tool.name} className="rounded-md border px-3 py-2">
                  <p className="text-sm font-medium">{tool.name}</p>
                  {tool.description && (
                    <p className="text-xs text-muted-foreground">{tool.description}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Custom Headers */}
        {connection.custom_headers && connection.custom_headers.length > 0 && (
          <div>
            <h3 className="mb-3 text-sm font-medium">
              Custom Headers ({connection.custom_headers.length})
            </h3>
            <div className="grid gap-2">
              {connection.custom_headers.map((header) => (
                <div key={header.name} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <p className="font-mono text-sm">{header.name}</p>
                  <div className="flex items-center gap-1.5">
                    {header.secret ? (
                      <>
                        <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-mono text-sm text-muted-foreground">••••••••</span>
                      </>
                    ) : (
                      <span className="font-mono text-sm">{header.value ?? ""}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </ContentBlock>
  );
}
