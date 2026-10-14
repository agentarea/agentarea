"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  Braces,
  FileJson,
  FileText,
  Globe,
  KeyRound,
  Link,
  Plus,
  SlidersHorizontal,
  Tag,
} from "lucide-react";
import { announceFormSubmitting } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Textarea } from "@/components/ui/textarea";
import { formatApiError } from "@/lib/api-errors";
import {
  createOpenAPIConnectionAction as createOpenAPIConnection,
  previewOpenAPISpecAction as previewOpenAPISpec,
} from "@/lib/server-actions";
import { CredentialEncryptionNote } from "../components/CredentialFields";
import { HeaderRows, type HeaderRow } from "../components/HeaderRows";
import { QueryParamRows, type QueryParamRow } from "../components/QueryParamRows";
import { ToolsTable } from "../components/ToolsTable";
import {
  isAbsoluteBaseUrl,
  previewFromOpenAPISpec,
  resolveOpenAPIServerUrl,
} from "./openapi-preview";
import type { PreviewTool } from "./openapi-preview";

/** The header's submit button targets the form by this id. */
export const OPENAPI_FORM_ID = "openapi-connection-form";

type SpecMode = "url" | "json";

export function AddOpenAPIForm() {
  const router = useWorkspaceRouter();
  const t = useTranslations("OpenAPIForm");
  const formRef = useRef<HTMLFormElement>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [specMode, setSpecMode] = useState<SpecMode>("url");
  const [specUrl, setSpecUrl] = useState("");
  const [specJson, setSpecJson] = useState("");
  const [description, setDescription] = useState("");
  const [headers, setHeaders] = useState<HeaderRow[]>([]);
  const [queryParams, setQueryParams] = useState<QueryParamRow[]>([]);
  const [previewTools, setPreviewTools] = useState<PreviewTool[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [specResolved, setSpecResolved] = useState(false);

  const baseUrlError =
    baseUrl.trim() && !isAbsoluteBaseUrl(baseUrl)
      ? t("baseUrlAbsoluteRequired")
      : null;

  const addHeader = () => setHeaders([...headers, { name: "", value: "" }]);

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
              base_url: resolveOpenAPIServerUrl(data.base_url ?? undefined, url),
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
        const result = previewFromOpenAPISpec(parsed);
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
    setError(null);
    // The submit button sits in the page header, so it is live before a spec
    // has filled in the fields below.
    if (!specResolved) {
      setError(t("specRequired"));
      return;
    }
    if (!name.trim()) {
      setError(t("nameRequired"));
      return;
    }
    if (!isAbsoluteBaseUrl(baseUrl)) {
      setError(t("baseUrlAbsoluteRequired"));
      return;
    }

    let specContent: Record<string, unknown> | undefined;
    if (specMode === "json" && specJson.trim()) {
      try {
        specContent = JSON.parse(specJson);
      } catch {
        setError(t("invalidJsonHint"));
        return;
      }
    }

    const nonEmptyHeaders = headers.filter((h) => h.name.trim());
    const nonEmptyQueryParams = queryParams
      .filter((p) => p.name.trim())
      .map((p) => ({ ...p, name: p.name.trim() }));

    announceFormSubmitting(formRef.current, true);
    let leaving = false;
    try {
      const { error: createError } = await createOpenAPIConnection({
        name,
        base_url: baseUrl,
        description: description || undefined,
        spec_url: specMode === "url" ? specUrl || undefined : undefined,
        spec_content: specContent,
        custom_headers:
          nonEmptyHeaders.length > 0 ? nonEmptyHeaders : undefined,
        custom_query_params:
          nonEmptyQueryParams.length > 0 ? nonEmptyQueryParams : undefined,
      });

      if (createError) {
        setError(formatApiError(createError));
        return;
      }

      // NB: do NOT call router.refresh() right after push() - the refresh aborts
      // the in-flight navigation, leaving the user stuck on this form after a
      // successful 201 (looks like a hang). The action revalidates /connections
      // server-side, so the new connection is present when we land there.
      // Keep the header button busy until the list opens.
      leaving = true;
      router.push("/connections");
    } catch (err) {
      console.error("Failed to create OpenAPI connection", err);
      setError(
        err instanceof Error ? err.message : t("failedToCreate")
      );
    } finally {
      if (!leaving) announceFormSubmitting(formRef.current, false);
    }
  };

  const specHint = specMode === "url" ? t("urlHint") : t("jsonHint");

  return (
    <form
      ref={formRef}
      id={OPENAPI_FORM_ID}
      onSubmit={handleSubmit}
      className="mx-auto w-full max-w-4xl"
    >
      <div className="form-content">
        {error && <FormError>{error}</FormError>}

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <FormLabel
              htmlFor={specMode === "url" ? "spec_url" : "spec_json"}
              icon={FileJson}
              required
            >
              {t("openApiSpec")}
            </FormLabel>
            <SegmentedControl<SpecMode>
              value={specMode}
              onChange={switchMode}
              layoutId="openapi-spec-mode-control"
              items={[
                {
                  value: "url",
                  label: (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <Link aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
                      {t("url")}
                    </span>
                  ),
                },
                {
                  value: "json",
                  label: (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <Braces aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
                      {t("pasteJson")}
                    </span>
                  ),
                },
              ]}
            />
          </div>

          {specMode === "url" ? (
            <div className="relative">
              <Input
                id="spec_url"
                placeholder="https://petstore3.swagger.io/api/v3/openapi.json"
                value={specUrl}
                onChange={(e) => handleSpecUrlChange(e.target.value)}
                type="url"
                autoFocus
                aria-invalid={Boolean(previewError)}
              />
              {fetching && (
                <StatusIndicator
                  kind="running"
                  size="sm"
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  aria-label={t("openApiSpec")}
                  title={t("openApiSpec")}
                />
              )}
            </div>
          ) : (
            <Textarea
              id="spec_json"
              placeholder='{ "openapi": "3.1.0", "paths": { … } }'
              value={specJson}
              onChange={(e) => parseJsonPreview(e.target.value)}
              className="h-[200px] resize-none font-mono text-xs"
              aria-invalid={Boolean(previewError)}
            />
          )}
          {previewError ? (
            <p className="form-error" role="alert">
              {previewError}
            </p>
          ) : (
            <p className="note">{specHint}</p>
          )}
        </div>

        {previewTools.length > 0 && (
          <ToolsTable
            tools={previewTools}
            label={`${t("detectedTools")} (${previewTools.length})`}
          />
        )}
      </div>

      {specResolved && (
        <>
          <Divider className="my-6" />

          <div className="form-content">
            <div className="space-y-2">
              <FormLabel htmlFor="name" icon={Tag} required>
                {t("name")}
              </FormLabel>
              <Input
                id="name"
                placeholder={t("namePlaceholder")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
              />
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="base_url" icon={Globe} required>
                {t("baseUrl")}
              </FormLabel>
              <Input
                id="base_url"
                placeholder="https://api.stripe.com"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                type="url"
                aria-invalid={Boolean(baseUrlError)}
                aria-describedby={baseUrlError ? "base_url-error" : undefined}
              />
              {baseUrlError ? (
                <p id="base_url-error" className="form-error" role="alert">
                  {baseUrlError}
                </p>
              ) : (
                <p className="note">{t("baseUrlHint")}</p>
              )}
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="description" icon={FileText} optional>
                {t("description")}
              </FormLabel>
              <Textarea
                id="description"
                placeholder={t("descriptionPlaceholder")}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="h-[100px] resize-none"
              />
            </div>
          </div>

          <Divider className="my-6" />

          <div className="form-content">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <FormLabel icon={KeyRound} optional>
                  {t("customHeaders")}
                </FormLabel>
                <Button type="button" variant="outline" size="xs" onClick={addHeader}>
                  <Plus />
                  {t("addHeader")}
                </Button>
              </div>
              {headers.length === 0 && (
                <p className="note">{t("headersHint")}</p>
              )}
              <HeaderRows rows={headers} onChange={setHeaders} />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <FormLabel icon={SlidersHorizontal} optional>
                  {t("customQueryParams")}
                </FormLabel>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={() =>
                    setQueryParams([
                      ...queryParams,
                      { name: "", value: "", secret: true },
                    ])
                  }
                >
                  <Plus />
                  {t("addQueryParam")}
                </Button>
              </div>
              {queryParams.length === 0 && (
                <p className="note">{t("queryParamsHint")}</p>
              )}
              <QueryParamRows rows={queryParams} onChange={setQueryParams} />
            </div>

            <CredentialEncryptionNote />
          </div>
        </>
      )}
    </form>
  );
}
