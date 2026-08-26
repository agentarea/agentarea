"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Loader2, Lock, Plus, Trash2, Unlock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatApiError } from "@/lib/api-errors";
import {
  createOpenAPIConnectionAction as createOpenAPIConnection,
  previewOpenAPISpecAction as previewOpenAPISpec,
} from "@/lib/server-actions";

type SpecMode = "url" | "json";

interface HeaderRow {
  name: string;
  value: string;
}

interface PreviewTool {
  name: string;
  description: string;
}

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

interface OpenAPIOperation {
  operationId?: string;
  summary?: string;
  description?: string;
}

interface OpenAPISpec {
  openapi?: string;
  info?: { title?: string; description?: string; version?: string };
  servers?: Array<{ url?: string }>;
  paths?: Record<
    string,
    Record<string, OpenAPIOperation | undefined> | null | undefined
  >;
}

function extractFromSpec(spec: OpenAPISpec) {
  const info = spec.info || {};
  const servers = spec.servers || [];
  const tools: PreviewTool[] = [];

  if (spec.openapi && String(spec.openapi).startsWith("3.")) {
    const paths = spec.paths || {};
    const methods = [
      "get",
      "post",
      "put",
      "patch",
      "delete",
      "head",
      "options",
    ];
    for (const [path, pathItem] of Object.entries(paths)) {
      if (!pathItem || typeof pathItem !== "object") continue;
      for (const method of methods) {
        const op = pathItem[method];
        if (!op) continue;
        tools.push({
          name:
            op.operationId ||
            `${method}_${path.replace(/[{}]/g, "").split("/").filter(Boolean).join("_")}`,
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
  const t = useTranslations("OpenAPIForm");
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
  const [specResolved, setSpecResolved] = useState(false);

  const addHeader = () => setHeaders([...headers, { name: "", value: "" }]);
  const removeHeader = (i: number) =>
    setHeaders(headers.filter((_, idx) => idx !== i));
  const updateHeader = (i: number, field: keyof HeaderRow, val: string) => {
    const next = [...headers];
    next[i] = { ...next[i], [field]: val };
    setHeaders(next);
  };

  const resetForm = () => {
    setName("");
    setBaseUrl("");
    setDescription("");
    setPreviewTools([]);
    setPreviewError(null);
    setSpecResolved(false);
  };

  const switchMode = (mode: SpecMode) => {
    setSpecMode(mode);
    setSpecUrl("");
    setSpecJson("");
    resetForm();
  };

  const applyPreview = useCallback(
    (data: {
      title?: string | null;
      description?: string | null;
      base_url?: string | null;
      version?: string | null;
      tools: PreviewTool[];
    }) => {
      if (data.title) setName(data.title);
      if (data.description) setDescription(data.description);
      if (data.base_url) setBaseUrl(data.base_url);
      setPreviewTools(data.tools);
      setSpecResolved(true);
    },
    []
  );

  const fetchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

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
      if (!url.trim()) {
        setSpecResolved(false);
        return;
      }

      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);

      // Immediately infer base URL from the spec URL origin
      try {
        const parsed = new URL(url);
        setBaseUrl(parsed.origin);
      } catch {
        // Not a valid URL yet
      }

      fetchTimerRef.current = setTimeout(async () => {
        setFetching(true);
        setPreviewError(null);
        try {
          const { data, error: fetchErr } = await previewOpenAPISpec({
            spec_url: url,
          });
          if (fetchErr) {
            setPreviewError(formatApiError(fetchErr));
          } else if (data) {
            applyPreview({
              title: data.title,
              description: data.description,
              base_url: data.base_url,
              version: data.version,
              tools: (data.tools ?? []).map((tool) => ({
                name: tool.name ?? "",
                description: tool.description ?? "",
              })),
            });
          }
        } catch {
          setPreviewError(t("failedToFetchSpec"));
        } finally {
          setFetching(false);
        }
      }, 800);
    },
    [applyPreview, t]
  );

  const parseJsonPreview = useCallback(
    (raw: string) => {
      setSpecJson(raw);
      setPreviewTools([]);
      setPreviewError(null);
      setSpecResolved(false);
      if (!raw.trim()) return;
      try {
        const parsed = JSON.parse(raw);
        const result = extractFromSpec(parsed);
        if (result.tools.length > 0) {
          applyPreview(result);
        } else {
          setPreviewError(t("validJsonNoOperations"));
          // Still try to fill metadata
          if (result.title) setName(result.title);
          if (result.description) setDescription(result.description);
          if (result.base_url) setBaseUrl(result.base_url);
          setSpecResolved(true);
        }
      } catch {
        setPreviewError(t("invalidJson"));
      }
    },
    [applyPreview, t]
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
        setError(t("invalidJsonHint"));
        setLoading(false);
        return;
      }
    }

    const nonEmptyHeaders = headers.filter((h) => h.name.trim());

    try {
      const { error: createError } = await createOpenAPIConnection({
        name,
        base_url: baseUrl,
        description: description || undefined,
        spec_url: specMode === "url" ? specUrl || undefined : undefined,
        spec_content: specContent,
        custom_headers:
          nonEmptyHeaders.length > 0 ? nonEmptyHeaders : undefined,
      });

      if (createError) {
        setError(formatApiError(createError));
        return;
      }

      // NB: do NOT call router.refresh() right after push() - the refresh aborts
      // the in-flight navigation, leaving the user stuck on this form after a
      // successful 201 (looks like a hang). The action revalidates /connections
      // server-side, so the new connection is present when we land there.
      router.push("/connections");
    } catch (err) {
      console.error("Failed to create OpenAPI connection", err);
      setError(
        err instanceof Error ? err.message : t("failedToCreate")
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-xl space-y-6">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>{t("openApiSpec")}</Label>
          <div className="flex gap-1 rounded-md border p-0.5 text-xs">
            <button
              type="button"
              className={`rounded px-2 py-0.5 transition-colors ${specMode === "url" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => switchMode("url")}
            >
              {t("url")}
            </button>
            <button
              type="button"
              className={`rounded px-2 py-0.5 transition-colors ${specMode === "json" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
              onClick={() => switchMode("json")}
            >
              {t("pasteJson")}
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
            <p className="text-xs text-muted-foreground">{t("urlHint")}</p>
          </>
        ) : (
          <>
            <Textarea
              id="spec_json"
              placeholder={t("jsonHint")}
              value={specJson}
              onChange={(e) => parseJsonPreview(e.target.value)}
              rows={10}
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">{t("jsonHint")}</p>
          </>
        )}
        {previewError && (
          <p className="text-xs text-amber-600">{previewError}</p>
        )}
      </div>

      {previewTools.length > 0 && (
        <div className="rounded-lg border p-4">
          <h4 className="mb-2 text-sm font-medium">
            {t("detectedTools")} ({previewTools.length})
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
                  {t("tool")}
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

      {specResolved && (
        <>
          <div className="space-y-2">
            <Label htmlFor="name">{t("name")}</Label>
            <Input
              id="name"
              placeholder="e.g. Stripe API"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="base_url">{t("baseUrl")}</Label>
            <Input
              id="base_url"
              placeholder="https://api.stripe.com"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              required
              type="url"
            />
            <p className="text-xs text-muted-foreground">{t("baseUrlHint")}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">{t("description")}</Label>
            <Input
              id="description"
              placeholder="Payment processing API"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t("customHeaders")}</Label>
              <Button
                type="button"
                variant="outline"
                size="xs"
                onClick={addHeader}
              >
                <Plus className="mr-1" />
                {t("addHeader")}
              </Button>
            </div>
            {headers.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t("headersHint")}
              </p>
            )}
            {headers.map((h, i) => {
              const secret = h.name.trim() ? isSecretHeader(h.name) : false;
              return (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    placeholder={t("headerName")}
                    value={h.name}
                    onChange={(e) => updateHeader(i, "name", e.target.value)}
                    className="flex-1"
                  />
                  <div className="relative flex-1">
                    <Input
                      placeholder={t("headerValue")}
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
                    <Trash2 />
                  </Button>
                </div>
              );
            })}
            {headers.some((h) => h.name.trim() && isSecretHeader(h.name)) && (
              <p className="text-xs text-muted-foreground">
                <Lock className="mr-1 inline h-3 w-3" />
                {t("secretHeadersHint")}
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
              {loading ? t("creating") : t("createConnection")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => router.push("/connections")}
            >
              {t("cancel")}
            </Button>
          </div>
        </>
      )}

      {!specResolved && (
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push("/connections")}
        >
          {t("cancel")}
        </Button>
      )}
    </form>
  );
}
