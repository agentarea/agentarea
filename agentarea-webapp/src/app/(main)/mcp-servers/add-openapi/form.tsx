"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Plus, Trash2, Lock, Unlock, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  createOpenAPIConnection,
  discoverOpenAPITools,
  previewOpenAPISpec,
} from "@/lib/browser-api";

type SpecMode = "url" | "json";

interface HeaderRow {
  name: string;
  value: string;
}

interface PreviewTool {
  name: string;
  description: string;
}

/** Well-known headers that are never sensitive. */
const SAFE_HEADERS = new Set([
  "accept",
  "accept-charset",
  "accept-encoding",
  "accept-language",
  "cache-control",
  "content-type",
  "if-match",
  "if-none-match",
  "user-agent",
  "x-correlation-id",
  "x-request-id",
]);

function isSecretHeader(name: string) {
  return !SAFE_HEADERS.has(name.toLowerCase().trim());
}

/** Client-side OpenAPI 3.x metadata + tool extraction. */
function extractFromSpec(spec: Record<string, any>) {
  const info = spec.info || {};
  const servers = spec.servers || [];
  const tools: PreviewTool[] = [];

  if (spec.openapi && String(spec.openapi).startsWith("3.")) {
    const paths = spec.paths || {};
    const methods = ["get", "post", "put", "patch", "delete", "head", "options"];
    for (const [path, pathItem] of Object.entries(paths)) {
      if (!pathItem || typeof pathItem !== "object") continue;
      for (const method of methods) {
        const op = (pathItem as any)[method];
        if (!op) continue;
        tools.push({
          name:
            op.operationId ||
            `${method}_${path
              .replace(/[{}]/g, "")
              .split("/")
              .filter(Boolean)
              .join("_")}`,
          description: op.summary || op.description || "",
        });
      }
    }
  }

  return {
    title: info.title || null,
    description: info.description || null,
    version: info.version || null,
    base_url: servers[0]?.url || null,
    tools,
  };
}

export function AddOpenAPIForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [specMode, setSpecMode] = useState<SpecMode>("url");
  const [specUrl, setSpecUrl] = useState("");
  const [specJson, setSpecJson] = useState("");
  const [description, setDescription] = useState("");
  const [headers, setHeaders] = useState<HeaderRow[]>([]);
  const [previewTools, setPreviewTools] = useState<PreviewTool[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  // Track whether fields were auto-filled (so we don't overwrite user edits)
  const autoFilledRef = useRef(false);

  const addHeader = () => setHeaders([...headers, { name: "", value: "" }]);
  const removeHeader = (i: number) =>
    setHeaders(headers.filter((_, idx) => idx !== i));
  const updateHeader = (i: number, field: keyof HeaderRow, val: string) => {
    const next = [...headers];
    next[i] = { ...next[i], [field]: val };
    setHeaders(next);
  };

  /** Apply preview data to the form fields. */
  const applyPreview = useCallback(
    (data: {
      title?: string | null;
      description?: string | null;
      base_url?: string | null;
      version?: string | null;
      tools: PreviewTool[];
    }) => {
      if (data.title && !name) setName(data.title);
      if (data.description && !description) setDescription(data.description);
      if (data.base_url && !baseUrl) setBaseUrl(data.base_url);
      setPreviewTools(data.tools);
      autoFilledRef.current = true;
    },
    [name, description, baseUrl],
  );

  /** Fetch spec from URL and auto-populate. */
  const fetchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);
    };
  }, []);

  const handleSpecUrlChange = useCallback(
    (url: string) => {
      setSpecUrl(url);
      setPreviewTools([]);
      setPreviewError(null);

      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);

      if (!url.trim()) return;

      // Immediately infer base URL from the spec URL origin
      try {
        const parsed = new URL(url);
        if (!baseUrl) setBaseUrl(parsed.origin);
      } catch {
        // Not a valid URL yet — ignore
      }

      // Debounce 800ms after pasting/typing a URL
      fetchTimerRef.current = setTimeout(async () => {
        setFetching(true);
        setPreviewError(null);
        try {
          const { data, error: fetchErr } = await previewOpenAPISpec({
            spec_url: url,
          });
          if (fetchErr) {
            setPreviewError(
              (fetchErr as any)?.detail || "Failed to fetch spec",
            );
          } else if (data) {
            applyPreview(data as any);
          }
        } catch {
          setPreviewError("Failed to fetch spec");
        } finally {
          setFetching(false);
        }
      }, 800);
    },
    [applyPreview, baseUrl],
  );

  /** Parse pasted JSON and auto-populate. */
  const parseJsonPreview = useCallback(
    (raw: string) => {
      setSpecJson(raw);
      setPreviewTools([]);
      setPreviewError(null);
      if (!raw.trim()) return;
      try {
        const parsed = JSON.parse(raw);
        const result = extractFromSpec(parsed);
        if (result.tools.length > 0) {
          applyPreview(result);
        } else {
          setPreviewError(
            "Valid JSON but no OpenAPI 3.x operations found.",
          );
          // Still try to fill metadata
          if (result.title && !name) setName(result.title);
          if (result.description && !description)
            setDescription(result.description);
          if (result.base_url && !baseUrl) setBaseUrl(result.base_url);
        }
      } catch {
        setPreviewError("Invalid JSON");
      }
    },
    [applyPreview, name, description, baseUrl],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    let specContent: Record<string, unknown> | undefined;
    if (specMode === "json" && specJson.trim()) {
      try {
        specContent = JSON.parse(specJson);
      } catch {
        setError("Invalid JSON. Please check the spec content.");
        setLoading(false);
        return;
      }
    }

    const nonEmptyHeaders = headers.filter((h) => h.name.trim());

    try {
      const { data, error: createError } = await createOpenAPIConnection({
        name,
        base_url: baseUrl,
        description: description || undefined,
        spec_url: specMode === "url" ? specUrl || undefined : undefined,
        spec_content: specContent,
        custom_headers:
          nonEmptyHeaders.length > 0 ? nonEmptyHeaders : undefined,
      });

      if (createError) {
        setError(
          (createError as any)?.detail || "Failed to create connection",
        );
        return;
      }

      // Auto-discover tools if spec was provided
      const hasSpec =
        (specMode === "url" && specUrl) ||
        (specMode === "json" && specContent);
      if (hasSpec && data?.id) {
        try {
          await discoverOpenAPITools(data.id);
        } catch {
          // Non-fatal — tools can be discovered later
        }
      }

      router.push("/mcp-servers");
      router.refresh();
    } catch (err) {
      setError("Failed to create connection");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-xl space-y-6">
      {/* Spec first — so it can auto-fill the rest */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>OpenAPI Spec</Label>
          <div className="flex gap-1 rounded-md border p-0.5 text-xs">
            <button
              type="button"
              className={`rounded px-2 py-0.5 transition-colors ${specMode === "url" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setSpecMode("url")}
            >
              URL
            </button>
            <button
              type="button"
              className={`rounded px-2 py-0.5 transition-colors ${specMode === "json" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => setSpecMode("json")}
            >
              Paste JSON
            </button>
          </div>
        </div>

        {specMode === "url" ? (
          <>
            <div className="relative">
              <Input
                id="spec_url"
                placeholder="https://petstore3.swagger.io/api/v3/openapi.json"
                value={specUrl}
                onChange={(e) => handleSpecUrlChange(e.target.value)}
                type="url"
              />
              {fetching && (
                <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Paste a URL to auto-detect name, base URL, and available tools.
            </p>
          </>
        ) : (
          <>
            <Textarea
              id="spec_json"
              placeholder="Paste your OpenAPI 3.x spec JSON here..."
              value={specJson}
              onChange={(e) => parseJsonPreview(e.target.value)}
              rows={10}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              Paste the full OpenAPI 3.x JSON. Name, base URL, and tools will
              be auto-detected.
            </p>
          </>
        )}
        {previewError && (
          <p className="text-xs text-amber-600">{previewError}</p>
        )}
      </div>

      {/* Tool Preview */}
      {previewTools.length > 0 && (
        <div className="rounded-lg border p-4">
          <h4 className="mb-2 text-sm font-medium">
            Detected Tools ({previewTools.length})
          </h4>
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {previewTools.map((tool) => (
              <div
                key={tool.name}
                className="flex items-start gap-2 rounded-md border px-2 py-1.5"
              >
                <Badge
                  variant="outline"
                  className="mt-0.5 shrink-0 text-[10px]"
                >
                  tool
                </Badge>
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{tool.name}</p>
                  {tool.description && (
                    <p className="truncate text-[11px] text-muted-foreground">
                      {tool.description}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Name, Base URL, Description — below spec so they can be auto-filled */}
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          placeholder="e.g. Stripe API"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="base_url">Base URL</Label>
        <Input
          id="base_url"
          placeholder="https://api.stripe.com"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          required
          type="url"
        />
        <p className="text-xs text-muted-foreground">
          The base URL for API requests
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description (optional)</Label>
        <Input
          id="description"
          placeholder="Payment processing API"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {/* Custom Headers */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Custom Headers (optional)</Label>
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={addHeader}
          >
            <Plus className="mr-1 h-3 w-3" />
            Add Header
          </Button>
        </div>
        {headers.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Add headers for authentication or custom API requirements.
          </p>
        )}
        {headers.map((h, i) => {
          const secret = h.name.trim() ? isSecretHeader(h.name) : false;
          return (
            <div key={i} className="flex items-center gap-2">
              <Input
                placeholder="Header name"
                value={h.name}
                onChange={(e) => updateHeader(i, "name", e.target.value)}
                className="flex-1"
              />
              <div className="relative flex-1">
                <Input
                  placeholder="Value"
                  value={h.value}
                  onChange={(e) => updateHeader(i, "value", e.target.value)}
                  type={secret ? "password" : "text"}
                  className="pr-8"
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                  {secret ? (
                    <Lock className="h-3.5 w-3.5" />
                  ) : (
                    <Unlock className="h-3.5 w-3.5" />
                  )}
                </div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => removeHeader(i)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          );
        })}
        {headers.some((h) => h.name.trim() && isSecretHeader(h.name)) && (
          <p className="text-xs text-muted-foreground">
            <Lock className="mr-1 inline h-3 w-3" />
            Secret headers are encrypted and never returned in API responses.
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={loading || !name || !baseUrl}>
          {loading ? "Creating..." : "Create Connection"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push("/mcp-servers")}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
