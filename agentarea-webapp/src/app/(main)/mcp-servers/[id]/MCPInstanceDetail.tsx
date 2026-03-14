"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  AlertCircle,
  Check,
  CheckCircle,
  Clock,
  Container,
  Copy,
  Link as LinkIcon,
  Play,
  Square,
  Trash2,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { MCPInstance, MCPServer } from "../types";
import { startInstance, stopInstance, deleteInstance } from "./actions";
import { getMCPInstanceHealth } from "@/lib/api";

interface Props {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "running":
    case "healthy":
      return (
        <Badge variant="success">
          <CheckCircle className="mr-1 h-3 w-3" />
          Running
        </Badge>
      );
    case "stopped":
      return (
        <Badge variant="secondary">
          <Square className="mr-1 h-3 w-3" />
          Stopped
        </Badge>
      );
    case "error":
    case "unhealthy":
      return (
        <Badge variant="destructive">
          <XCircle className="mr-1 h-3 w-3" />
          Error
        </Badge>
      );
    case "starting":
      return (
        <Badge variant="yellow">
          <Clock className="mr-1 h-3 w-3" />
          Starting
        </Badge>
      );
    default:
      return (
        <Badge variant="yellow">
          <AlertCircle className="mr-1 h-3 w-3" />
          {status || "Unknown"}
        </Badge>
      );
  }
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success(`${label || "URL"} copied to clipboard`);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy");
    }
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 px-2"
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

export default function MCPInstanceDetail({ instance, serverSpec }: Props) {
  const router = useRouter();
  const [isActioning, setIsActioning] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [connectionUrl, setConnectionUrl] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);

  const canStart = instance.status !== "running" && instance.status !== "starting";
  const canStop = instance.status === "running" || instance.status === "starting";

  // Poll for status updates during transient states
  useEffect(() => {
    const transient = ["starting", "stopping", "pending", "validating"];
    if (!transient.includes(instance.status)) return;

    const interval = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(interval);
  }, [instance.status, router]);

  // Fetch connection URL when instance is running (skip for URL-type — it has its own endpoint)
  const jsonSpecType = (instance.json_spec?.type as string) || "docker";
  useEffect(() => {
    if (jsonSpecType === "url") return; // URL-type uses endpoint_url directly
    if (instance.status === "running" && instance.name) {
      setIsLoadingUrl(true);
      getMCPInstanceHealth(instance.name)
        .then(({ health_check }) => {
          if (health_check?.details?.proxy_url) {
            setConnectionUrl(health_check.details.proxy_url);
          } else if (health_check?.url) {
            setConnectionUrl(health_check.url);
          }
        })
        .catch(console.error)
        .finally(() => setIsLoadingUrl(false));
    }
  }, [instance.status, instance.name, jsonSpecType]);

  const handleStart = async () => {
    setIsActioning(true);
    try {
      const { error } = await startInstance(instance.id);
      if (error) throw new Error(typeof error === "object" && "detail" in error ? String(error.detail) : "Failed to start");
      toast.success(`Starting ${instance.name}…`);
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start instance");
    } finally {
      setIsActioning(false);
    }
  };

  const handleStop = async () => {
    setIsActioning(true);
    try {
      const { error } = await stopInstance(instance.id);
      if (error) throw new Error(typeof error === "object" && "detail" in error ? String(error.detail) : "Failed to stop");
      toast.success(`Stopped ${instance.name}`);
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to stop instance");
    } finally {
      setIsActioning(false);
    }
  };

  const handleDelete = async () => {
    setIsActioning(true);
    try {
      const { error } = await deleteInstance(instance.id);
      if (error) throw new Error(typeof error === "object" && "detail" in error ? String(error.detail) : "Failed to delete");
      toast.success(`Deleted ${instance.name}`);
      router.push("/mcp-servers");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete instance");
      setIsActioning(false);
    }
  };

  const envVars = (instance.json_spec?.environment ?? {}) as Record<string, string>;
  const containerImage = instance.json_spec?.image as string | undefined;
  const containerPort = instance.json_spec?.port as number | undefined;
  const tools = (instance.json_spec?.available_tools ?? []) as Array<{name: string; description: string}>;

  // Determine MCP type
  const specType = (instance.json_spec?.type as string) || "docker";
  const isUrlType = specType === "url";
  const isCommandType = specType === "command";

  // Command-type fields
  const commandStr = instance.json_spec?.command as string | undefined;
  const commandArgs = (instance.json_spec?.args ?? []) as string[];

  // URL-type fields
  const endpointUrl = instance.json_spec?.endpoint_url as string | undefined;
  const customHeaders = (instance.json_spec?.headers ?? {}) as Record<string, string>;

  // Generate SSE endpoint URL from connection URL
  const effectiveConnectionUrl = isUrlType ? endpointUrl : connectionUrl;
  const sseUrl = effectiveConnectionUrl ? `${effectiveConnectionUrl.replace(/\/$/, "")}/sse` : null;

  return (
    <div className="space-y-6 p-6">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold">{instance.name}</h2>
            <StatusBadge status={instance.status} />
            <Badge variant="outline" size="sm">
              {isCommandType ? "Command" : isUrlType ? "External URL" : "Docker"}
            </Badge>
          </div>
          {instance.description && (
            <p className="text-sm text-muted-foreground">{instance.description}</p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {canStart && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleStart}
              disabled={isActioning}
            >
              <Play className="mr-1.5 h-3.5 w-3.5" />
              Start
            </Button>
          )}
          {canStop && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleStop}
              disabled={isActioning}
            >
              <Square className="mr-1.5 h-3.5 w-3.5" />
              Stop
            </Button>
          )}
          <Button
            size="sm"
            variant="destructive"
            disabled={isActioning}
            onClick={() => setShowDeleteDialog(true)}
          >
            <Trash2 className="mr-1.5 h-3.5 w-3.5" />
            Delete
          </Button>

          <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Delete instance?</DialogTitle>
                <DialogDescription>
                  This will permanently delete <strong>{instance.name}</strong> and stop its container. This action cannot be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setShowDeleteDialog(false)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={handleDelete} disabled={isActioning}>
                  Delete
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Connection URL - Show when running, or always for URL-type */}
      {(instance.status === "running" || isUrlType) && (
        <Card className="p-4 space-y-4 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-900/10">
          <div className="flex items-center gap-2">
            <LinkIcon className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            <h3 className="text-sm font-medium text-blue-900 dark:text-blue-100">
              Connection URL
            </h3>
          </div>

          {!isUrlType && isLoadingUrl ? (
            <div className="text-sm text-muted-foreground">Loading connection details...</div>
          ) : effectiveConnectionUrl ? (
            <div className="space-y-3">
              {/* Main connection URL */}
              <div className="space-y-1.5">
                <label className="text-xs text-muted-foreground">
                  {isUrlType ? "External Endpoint" : "MCP Endpoint"}
                </label>
                <div className="flex gap-2">
                  <Input
                    value={effectiveConnectionUrl}
                    readOnly
                    className="font-mono text-sm bg-white dark:bg-slate-950"
                  />
                  <CopyButton text={effectiveConnectionUrl} label="Connection URL" />
                </div>
              </div>

              {/* SSE endpoint URL */}
              {sseUrl && !isUrlType && (
                <div className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">SSE Endpoint (for MCP clients)</label>
                  <div className="flex gap-2">
                    <Input
                      value={sseUrl}
                      readOnly
                      className="font-mono text-sm bg-white dark:bg-slate-950"
                    />
                    <CopyButton text={sseUrl} label="SSE URL" />
                  </div>
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                {isUrlType
                  ? "This MCP server is hosted externally at the URL above."
                  : "Use these URLs to connect your MCP client to this server instance."}
              </p>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              Connection URL not available. The instance may still be initializing.
            </div>
          )}
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* Server spec info */}
        {serverSpec && (
          <Card className="p-4 space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              Server Spec
            </h3>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="font-medium">{serverSpec.name}</span>
                {serverSpec.version && (
                  <Badge size="sm">v{serverSpec.version}</Badge>
                )}
              </div>
              {serverSpec.description && (
                <p className="text-sm text-muted-foreground">{serverSpec.description}</p>
              )}
            </div>
          </Card>
        )}

        {/* Configuration info - type-aware */}
        {isCommandType && commandStr && (
          <Card className="p-4 space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              Command
            </h3>
            <div className="space-y-2 text-sm">
              <div className="font-mono bg-muted rounded p-2 break-all">
                {commandStr} {commandArgs.join(" ")}
              </div>
              <p className="text-xs text-muted-foreground">
                Runs in a sandbox container via mcp-bridge.
              </p>
            </div>
          </Card>
        )}

        {isUrlType && (
          <Card className="p-4 space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              External Server
            </h3>
            <div className="space-y-2 text-sm">
              {endpointUrl && (
                <div className="font-mono bg-muted rounded p-2 break-all">
                  {endpointUrl}
                </div>
              )}
              {Object.keys(customHeaders).length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Custom Headers</p>
                  {Object.entries(customHeaders).map(([key]) => (
                    <div key={key} className="font-mono text-xs">
                      {key}: ••••••
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>
        )}

        {!isCommandType && !isUrlType && (containerImage || containerPort) && (
          <Card className="p-4 space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
              Container
            </h3>
            <div className="space-y-2 text-sm">
              {containerImage && (
                <div className="flex items-start gap-2">
                  <Container className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="font-mono break-all">{containerImage}</span>
                </div>
              )}
              {containerPort && (
                <div className="text-muted-foreground">
                  Port: <span className="font-mono">{containerPort}</span>
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* Available Tools */}
      {tools.length > 0 && (
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
            Available Tools ({tools.length})
          </h3>
          <div className="divide-y">
            {tools.map((tool) => (
              <div key={tool.name} className="py-2">
                <div className="font-mono text-sm font-medium">{tool.name}</div>
                {tool.description && (
                  <p className="text-sm text-muted-foreground">{tool.description}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Environment variables */}
      {Object.keys(envVars).length > 0 && (
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
            Environment Variables
          </h3>
          <div className="divide-y">
            {Object.entries(envVars).map(([key, value]) => (
              <div key={key} className="flex items-center gap-4 py-2 text-sm">
                <span className="w-48 shrink-0 font-mono text-muted-foreground">{key}</span>
                <span className="font-mono truncate">
                  {value ? (
                    <span className="text-foreground">{value}</span>
                  ) : (
                    <span className="italic text-muted-foreground">not set</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Metadata */}
      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
          Details
        </h3>
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <span className="text-muted-foreground">ID</span>
            <p className="font-mono text-xs mt-0.5">{instance.id}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Created</span>
            <p className="mt-0.5">
              {new Date(instance.created_at).toLocaleString()}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Updated</span>
            <p className="mt-0.5">
              {new Date(instance.updated_at).toLocaleString()}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
