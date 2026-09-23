"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import Image from "next/image";
import {
  ExternalLink,
  Github,
  Globe,
  Key,
  KeyRound,
  Lock,
  ShieldCheck,
  Tag,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Badge, badgeVariants } from "@/components/ui/badge";
import { BlueprintBadge } from "@/components/ui/blueprint-badge";
import { Skeleton } from "@/components/ui/skeleton";
import Divider from "@/components/ui/divider";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import FormLabel from "@/components/FormLabel/FormLabel";
import FormError from "@/components/FormError";
import { cn } from "@/lib/utils";
import { ToolsTable } from "../../components/ToolsTable";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
  validateConnectionAction,
  oauthAuthorizeAction,
} from "@/lib/server-actions";
import type { MCPServer } from "../../types";
import { createMCPServerInstance } from "../../actions";
import { getConnectionType, MCP_CONSTANTS } from "../../utils";
import { VerifyingModal } from "../../components/VerifyingModal";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FieldSpec {
  name: string;
  description?: string;
  isRequired?: boolean;
  isSecret?: boolean;
  default?: string;
  placeholder?: string;
  choices?: string[];
}

/** Shape of `POST /mcp-server-instances/validate-connection`. */
interface ValidationResult {
  valid: boolean;
  errors?: string[];
  tool_count?: number;
  tools?: Array<{ name: string; description: string }>;
  /** Present on an auth failure: how the endpoint wants to be authorized. */
  auth_methods?: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Tags that describe the connection transport, not a functional category.
const TRANSPORT_TAGS = new Set(["url", "docker", "command", "remote", "mcp"]);

interface McpJsonSpec {
  icons?: Array<{ src: string }>;
  title?: string;
  version?: string;
  remotes?: Array<{ headers?: FieldSpec[] }>;
  repository?: { url?: string; source?: string };
  websiteUrl?: string;
  available_tools?: unknown[];
  /** Auth methods cached on the spec by a previous probe. */
  auth_methods?: string[];
}

function getSpec(server: MCPServer): McpJsonSpec {
  return (server.json_spec ?? {}) as unknown as McpJsonSpec;
}

function getIcon(server: MCPServer): string | null {
  return getSpec(server).icons?.[0]?.src ?? null;
}

function getTitle(server: MCPServer): string {
  return getSpec(server).title || server.name;
}

function getRemoteHeaders(server: MCPServer): FieldSpec[] {
  return (
    getSpec(server).remotes?.[0]?.headers ||
    (server.env_schema as unknown as FieldSpec[] | undefined)?.filter(
      (e) => e.name
    ) ||
    []
  );
}

function getRepoUrl(server: MCPServer): string | null {
  return getSpec(server).repository?.url ?? null;
}

function getWebsiteUrl(server: MCPServer): string | null {
  return getSpec(server).websiteUrl ?? null;
}

function getRepoSource(server: MCPServer): string | null {
  return getSpec(server).repository?.source ?? null;
}

function getVersion(server: MCPServer): string | null {
  return server.version || getSpec(server).version || null;
}

function getCategories(server: MCPServer): string[] {
  const tags = server.tags;
  if (!Array.isArray(tags)) return [];
  return tags
    .filter((t) => t && !TRANSPORT_TAGS.has(t.toLowerCase()))
    .slice(0, 4);
}

function getToolCount(server: MCPServer): number {
  const tools = getSpec(server).available_tools;
  return Array.isArray(tools) ? tools.length : 0;
}

// --- small identity building blocks (reuse our Badge) -----------------------

function StatusBadge({ verified }: { verified: boolean }) {
  return (
    <Badge variant="outline">
      <span
        className={cn(
          "h-[7px] w-[7px] rounded-full",
          verified ? "bg-green-500" : "bg-amber-500"
        )}
      />
      {verified ? "Verified" : "Needs verification"}
    </Badge>
  );
}

function LinkPill({
  href,
  icon: Icon,
  children,
}: {
  href: string;
  icon: typeof Github;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={badgeVariants({ variant: "outline", interactive: true })}
    >
      <Icon className="h-3.5 w-3.5" />
      {children}
    </a>
  );
}

function SpecHeader({
  server,
  verified,
}: {
  server: MCPServer;
  verified: boolean;
}) {
  const iconSrc = getIcon(server);
  const title = getTitle(server);
  const version = getVersion(server);
  const repoUrl = getRepoUrl(server);
  const websiteUrl = getWebsiteUrl(server);
  const repoSource = getRepoSource(server);
  const categories = getCategories(server);
  const toolCount = getToolCount(server);

  return (
    <div className="flex items-start gap-4">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg">
        {iconSrc ? (
          <Image
            src={iconSrc}
            alt={title}
            width={48}
            height={48}
            className="h-full w-full object-cover"
            unoptimized
          />
        ) : (
          <Globe className="h-6 w-6 text-muted-foreground" />
        )}
      </div>

      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {version && (
            <span className="font-mono text-[11px] text-muted-foreground">
              v{version.replace(/^v/, "")}
            </span>
          )}
        </div>

        {server.description && (
          <p className="mt-1.5 max-w-[54ch] text-sm text-muted-foreground">
            {server.description}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <StatusBadge verified={verified} />
          {repoUrl && (
            <LinkPill
              href={repoUrl}
              icon={repoSource === "github" ? Github : Globe}
            >
              {repoSource === "github" ? "GitHub" : "Repository"}
            </LinkPill>
          )}
          {websiteUrl && (
            <LinkPill href={websiteUrl} icon={ExternalLink}>
              Website
            </LinkPill>
          )}
        </div>

        {(categories.length > 0 || toolCount > 0) && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {categories.map((c) => (
              <Badge key={c} variant="gray">
                {c}
              </Badge>
            ))}
            {toolCount > 0 && <Badge variant="gray">{toolCount} tools</Badge>}
          </div>
        )}
      </div>
    </div>
  );
}

function EncryptionNote() {
  const t = useTranslations("MCPServersPage.createInstance.connect");
  return (
    <div className="mt-6 flex items-center gap-2 text-xs text-muted-foreground/60">
      <Lock className="h-3.5 w-3.5" />
      {t("encryptionNote")}
    </div>
  );
}

// ---------------------------------------------------------------------------
// URL-type connect form (react-hook-form)
// ---------------------------------------------------------------------------

interface UrlFormValues {
  instanceName: string;
  fields: Record<string, string>;
}

/**
 * How the endpoint wants to be authorized. Resolved on mount — from the spec's
 * cached `auth_methods`, or by validating the bare endpoint — so the user lands
 * on the right form immediately instead of discovering it after a first
 * "Connect" that has already created a (broken) instance.
 */
type AuthMode =
  | "loading" // probing the endpoint
  | "fields" // spec declares headers → fill them in, validate, create
  | "none" // endpoint is open → Connect creates the instance directly
  | "oauth" // OAuth only (manual entry offered as a fallback link)
  | "credentials" // manual credentials only
  | "both" // OAuth or manual, user picks
  | "error"; // probe failed → retry, or Force create from the subheader

const DEFAULT_CREDENTIAL_FIELD: FieldSpec = {
  name: "Authorization",
  isSecret: true,
  placeholder: "Bearer your-token",
};

function modeFromMethods(methods: string[]): AuthMode {
  const oauth = methods.includes("oauth");
  const credentials = methods.includes("credentials");
  if (oauth && credentials) return "both";
  if (oauth) return "oauth";
  if (credentials) return "credentials";
  return "none";
}

// Env vars a spec may declare for manual auth; shown as the credential inputs.
const CREDENTIAL_ENV_NAMES = new Set(["AUTHORIZATION", "API_KEY", "TOKEN"]);

function credentialFieldsFromSpec(server: MCPServer): FieldSpec[] {
  const named = ((server.env_schema ?? []) as unknown as FieldSpec[])
    .filter((e) => e.name && CREDENTIAL_ENV_NAMES.has(e.name.toUpperCase()))
    .map<FieldSpec>((e) => ({ ...e, isSecret: true }));
  return named.length > 0 ? named : [DEFAULT_CREDENTIAL_FIELD];
}

/** Server actions return the raw API body on failure; surface its `detail`. */
function apiErrorText(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const d = parsed.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && typeof d[0]?.msg === "string") return d[0].msg;
  } catch {
    /* not JSON — fall through to the raw text */
  }
  return raw;
}

function UrlConnectForm({ server }: { server: MCPServer }) {
  const router = useRouter();
  const t = useTranslations("MCPServersPage.createInstance.connect");
  const remoteHeaders = getRemoteHeaders(server);
  const hasFields = remoteHeaders.length > 0;
  const endpointUrl = server.remote_url || "";
  const cachedMethods = getSpec(server).auth_methods;

  const defaultFieldValues: Record<string, string> = {};
  for (const h of remoteHeaders) {
    defaultFieldValues[h.name] = h.default || "";
  }

  const { register, getValues, watch } = useForm<UrlFormValues>({
    defaultValues: {
      instanceName: getTitle(server),
      fields: defaultFieldValues,
    },
  });

  const [authMode, setAuthMode] = useState<AuthMode>(() => {
    if (hasFields) return "fields";
    if (Array.isArray(cachedMethods) && cachedMethods.length > 0) {
      return modeFromMethods(cachedMethods);
    }
    return "loading";
  });
  const credentialFields = credentialFieldsFromSpec(server);
  const [authTab, setAuthTab] = useState<"oauth" | "manual">("oauth");
  const [probeError, setProbeError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [createdInstanceId, setCreatedInstanceId] = useState<string | null>(
    null
  );
  const [isWorking, setIsWorking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{
    id: string;
    name: string;
  } | null>(null);

  // Detect the auth method up front by validating the bare endpoint (no
  // instance is created for this). An auth failure reports `auth_methods`.
  const probe = useCallback(async () => {
    setAuthMode("loading");
    setProbeError(null);
    const result = await validateConnectionAction(endpointUrl, {}, server.id);
    const data = result.data as ValidationResult | null;
    if (result.error || !data) {
      setProbeError(apiErrorText(result.error, t("probeFailed")));
      setAuthMode("error");
      return;
    }
    if (data.valid) {
      setAuthMode("none");
      return;
    }
    if (data.auth_methods && data.auth_methods.length > 0) {
      setAuthMode(modeFromMethods(data.auth_methods));
      return;
    }
    setProbeError(data.errors?.[0] || t("probeFailed"));
    setAuthMode("error");
  }, [endpointUrl, server.id, t]);

  const probedRef = useRef(false);
  useEffect(() => {
    if (authMode !== "loading" || probedRef.current) return;
    probedRef.current = true;
    void probe();
  }, [authMode, probe]);

  // Which header inputs are shown: the spec's own, or the probed credential hints.
  const activeFields = authMode === "fields" ? remoteHeaders : credentialFields;
  const showManualFields =
    authMode === "fields" ||
    authMode === "credentials" ||
    (authMode === "both" && authTab === "manual");
  const showOAuth =
    authMode === "oauth" || (authMode === "both" && authTab === "oauth");

  // Build headers dict from form field values
  const buildHeaders = (): Record<string, string> => {
    const vals = getValues("fields") ?? {};
    const headers: Record<string, string> = {};
    for (const [key, val] of Object.entries(vals)) {
      if (val?.trim()) headers[key] = val.trim();
    }
    return headers;
  };

  const createInstance = async (headers: Record<string, string>) => {
    const { instanceName } = getValues();
    const instanceResult = await createMCPServerInstance({
      name: instanceName,
      description: server.description,
      server_spec_id: server.id,
      json_spec: {
        type: "url",
        endpoint_url: endpointUrl,
        ...(Object.keys(headers).length > 0 ? { headers } : {}),
      },
    });

    if (instanceResult.error) {
      const d = instanceResult.error.detail;
      throw new Error(
        typeof d === "string"
          ? d
          : Array.isArray(d) && d[0]?.msg
            ? d[0].msg
            : t("createFailed")
      );
    }
    const created = instanceResult.data;
    if (!created) throw new Error(t("createFailed"));
    setCreatedInstanceId(created.id);
    return created;
  };

  // Validate the entered credentials against the endpoint (no instance yet).
  const handleValidate = async () => {
    setError(null);
    setValidation(null);
    setIsWorking(true);
    try {
      const result = await validateConnectionAction(
        endpointUrl,
        buildHeaders(),
        server.id
      );
      const data = result.data as ValidationResult | null;
      if (result.error || !data) {
        setError(apiErrorText(result.error, t("connectionFailed")));
        return;
      }
      if (!data.valid) {
        setError(data.errors?.[0] || t("connectionFailed"));
        return;
      }
      setValidation(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("connectionFailed"));
    } finally {
      setIsWorking(false);
    }
  };

  // Create the instance (after validation, or directly for open endpoints).
  const handleCreate = async () => {
    setIsWorking(true);
    setError(null);
    try {
      const { instanceName } = getValues();
      const created = await createInstance(buildHeaders());
      const vStatus = created.verification?.status;
      if (vStatus === "in_progress" || vStatus === "never_attempted") {
        setVerifyingInstance({ id: created.id, name: instanceName });
      } else {
        router.push(`/connections/${created.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("createFailed"));
    } finally {
      setIsWorking(false);
    }
  };

  // OAuth flow: the authorize endpoint is bound to an instance, so create it
  // (once) right before redirecting to the authorization server.
  const handleOAuth = async () => {
    setIsWorking(true);
    setError(null);
    try {
      const instanceId = createdInstanceId ?? (await createInstance({})).id;
      const result = await oauthAuthorizeAction({ instance_id: instanceId });
      if (result.error || !result.data?.authorize_url) {
        setError(apiErrorText(result.error, t("oauthDiscoveryFailed")));
        return;
      }
      window.location.href = result.data.authorize_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : t("oauthStartFailed"));
    } finally {
      setIsWorking(false);
    }
  };

  const verified = validation?.valid === true;

  // Create lives in the subheader (consistent with every other form). The body
  // "Connect" button only authorizes / validates the connection.
  const nameValue = watch("instanceName");
  const hasName = !!nameValue?.trim();
  const canCreate = hasName && verified;
  const canForce = hasName;

  const handleCreateRef = useRef<() => void>(() => {});
  handleCreateRef.current = handleCreate;

  const handleCreateSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!canCreate || isWorking) return;
    handleCreate();
  };

  // Keep the subheader Create / Force create buttons in sync with form state.
  useEffect(() => {
    document.dispatchEvent(
      new CustomEvent("mcp-create-state", {
        detail: {
          createEnabled: canCreate,
          forceEnabled: canForce,
          creating: isWorking,
        },
      })
    );
  }, [canCreate, canForce, isWorking]);

  // "Force create" in the subheader dispatches an event onto the form element.
  useEffect(() => {
    const form = document.getElementById("mcp-instance-form");
    if (!form) return;
    const handler = () => handleCreateRef.current();
    form.addEventListener("mcp-force-create", handler);
    return () => form.removeEventListener("mcp-force-create", handler);
  }, []);

  const segmentedItems = [
    {
      value: "oauth" as const,
      label: (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
          {t("oauthTab")}
        </span>
      ),
    },
    {
      value: "manual" as const,
      label: (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <KeyRound aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
          {t("manualTab")}
        </span>
      ),
    },
  ];

  return (
    <>
      {verifyingInstance && (
        <VerifyingModal
          instanceId={verifyingInstance.id}
          instanceName={verifyingInstance.name}
          onSuccess={(id) => router.push(`/connections/${id}`)}
          onDelete={() => router.push("/connections")}
          onEditRetry={(id) => {
            setVerifyingInstance(null);
            router.push(`/connections/${id}`);
          }}
        />
      )}
      <form
        id="mcp-instance-form"
        onSubmit={handleCreateSubmit}
        className="mx-auto w-full max-w-[600px] px-2 py-10"
      >
        <SpecHeader server={server} verified={verified} />

        <Divider className="my-6" />

        {/* Instance name */}
        <div className="flex flex-col gap-2">
          <FormLabel htmlFor="instance-name" icon={Tag} required>
            {t("nameLabel")}
          </FormLabel>
          <Input
            id="instance-name"
            autoComplete="off"
            {...register("instanceName", { required: true })}
          />
          <p className="text-xs text-muted-foreground/60">{t("nameHint")}</p>
        </div>

        {/* Error */}
        {error && <FormError className="mt-6">{error}</FormError>}

        {/* Probing the endpoint for its auth method */}
        {authMode === "loading" && (
          <div className="mt-6 space-y-3" aria-busy="true" aria-live="polite">
            <p className="text-sm text-muted-foreground">{t("detecting")}</p>
            <Skeleton className="h-9 w-[200px]" />
            <Skeleton className="h-9 w-full" />
          </div>
        )}

        {/* Probe failed: retry, or Force create from the subheader */}
        {authMode === "error" && (
          <div className="mt-6 flex flex-col gap-2">
            <FormError>{probeError ?? t("probeFailed")}</FormError>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full max-w-[200px]"
              onClick={() => void probe()}
            >
              {t("retryProbe")}
            </Button>
          </div>
        )}

        {/* OAuth / Manual switcher */}
        {authMode === "both" && (
          <div className="mt-6">
            <SegmentedControl
              items={segmentedItems}
              value={authTab}
              onChange={setAuthTab}
              layoutId="connection-auth-mode-control"
            />
          </div>
        )}

        {/* OAuth pane */}
        {showOAuth && (
          <div className="mt-6 space-y-3">
            <div className="flex items-center gap-2">
              <FormLabel icon={ShieldCheck}>{t("authorization")}</FormLabel>
              <BlueprintBadge>{t("oauthDetected")}</BlueprintBadge>
            </div>
            <StartAgentButton
              type="button"
              size="xs"
              className="w-auto"
              onClick={handleOAuth}
              isLoading={isWorking}
              disabled={isWorking || !hasName}
            >
              {t("authorizeOAuth")}
            </StartAgentButton>
            {authMode === "oauth" && (
              <button
                type="button"
                className="block text-xs text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => {
                  setAuthMode("both");
                  setAuthTab("manual");
                }}
              >
                {t("haveCredentials")}
              </button>
            )}
          </div>
        )}

        {/* Header / credential fields (spec-declared or probed) */}
        {showManualFields && !validation && (
          <div className="mt-6 space-y-4">
            {activeFields.map((field) => (
              <div key={field.name} className="flex flex-col gap-2">
                <FormLabel
                  htmlFor={`field-${field.name}`}
                  icon={field.isSecret ? Key : undefined}
                  required={field.isRequired !== false}
                >
                  {field.name}
                </FormLabel>
                {field.description && (
                  <p className="text-xs text-muted-foreground">
                    {field.description}
                  </p>
                )}
                {field.choices && field.choices.length > 0 ? (
                  <select
                    id={`field-${field.name}`}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    {...register(`fields.${field.name}`)}
                  >
                    <option value="">Select...</option>
                    {field.choices.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id={`field-${field.name}`}
                    type={field.isSecret ? "password" : "text"}
                    placeholder={field.placeholder || ""}
                    {...register(`fields.${field.name}`)}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Open endpoint: nothing to enter */}
        {authMode === "none" && !validation && (
          <p className="mt-6 text-sm text-muted-foreground">{t("openEndpoint")}</p>
        )}

        {/* Validation success — discovered tools preview. Creation itself is
            triggered from the subheader (Create instance / Force create). */}
        {validation?.valid &&
          validation.tools &&
          validation.tools.length > 0 && (
            <div className="mt-6">
              <ToolsTable
                tools={validation.tools}
                label={t("toolsFound", { count: validation.tools.length })}
              />
            </div>
          )}

        {/* Connect: validates entered credentials, or creates directly for an
            open endpoint. Try Again stacks below, same width. */}
        {(showManualFields || authMode === "none") && !validation && (
          <div className="mt-6 flex flex-col gap-2">
            <StartAgentButton
              type="button"
              size="xs"
              className="max-w-[200px]"
              onClick={authMode === "none" ? handleCreate : handleValidate}
              isLoading={isWorking}
              disabled={isWorking || !hasName}
            >
              {isWorking ? t("connecting") : t("connect")}
            </StartAgentButton>
            {error && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full max-w-[200px]"
                onClick={() => {
                  setError(null);
                  setValidation(null);
                }}
              >
                {t("tryAgain")}
              </Button>
            )}
          </div>
        )}

        <EncryptionNote />
      </form>
    </>
  );
}

// ---------------------------------------------------------------------------
// Docker/Command form (existing MCPInstanceConfigForm)
// ---------------------------------------------------------------------------

function DockerCommandForm({ server }: { server: MCPServer }) {
  const router = useRouter();
  const t = useTranslations("MCPServersPage.createInstance");

  const [instanceName, setInstanceName] = useState(getTitle(server));
  const [instanceDescription, setInstanceDescription] = useState(
    server.description
  );
  const [envVars, setEnvVars] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    server.env_schema?.forEach((envVar) => {
      init[envVar.name as string] = (envVar.default as string) || "";
    });
    return init;
  });
  const [isCreating, setIsCreating] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);

  const createInstance = async (skipValidation = false) => {
    if (!instanceName.trim()) return;
    if (!skipValidation && !validationResult?.valid) return;

    setIsCreating(true);
    try {
      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: instanceDescription,
        server_spec_id: server.id,
        json_spec: {
          image: server.docker_image_url,
          port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
          environment: envVars,
        },
      });

      if (instanceResult.error) {
        const errorDetail = instanceResult.error.detail;
        const errorMessage =
          typeof errorDetail === "string"
            ? errorDetail
            : Array.isArray(errorDetail) && errorDetail[0]?.msg
              ? errorDetail[0].msg
              : "Failed to create MCP instance";
        throw new Error(errorMessage);
      }

      const created = instanceResult.data;
      if (!created) {
        throw new Error("Failed to create MCP instance");
      }
      const vStatus = created?.verification?.status;
      if (vStatus === "in_progress" || vStatus === "never_attempted") {
        setVerifyingInstance({ id: created.id, name: instanceName });
      } else {
        router.replace(`/connections/${created.id}`);
      }
    } catch (error) {
      console.error("Instance creation error:", error);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <>
      {verifyingInstance && (
        <VerifyingModal
          instanceId={verifyingInstance.id}
          instanceName={verifyingInstance.name}
          onSuccess={(id) => router.replace(`/connections/${id}`)}
          onDelete={() => router.replace("/connections")}
          onEditRetry={(id) => {
            setVerifyingInstance(null);
            router.replace(`/connections/${id}`);
          }}
        />
      )}
      <div className="mx-auto w-full max-w-[600px] px-2 py-10">
        <SpecHeader server={server} verified={false} />
        <Divider className="my-6" />
        <MCPInstanceConfigForm
          formId="mcp-instance-form"
          className="h-full overflow-auto"
          hideSubmitButton
          hideForceCreateButton
          server={server}
          instanceName={instanceName}
          instanceDescription={instanceDescription}
          envVars={envVars}
          onChangeName={setInstanceName}
          onChangeDescription={setInstanceDescription}
          onChangeEnvVar={(key, value) => {
            setEnvVars((prev) => ({ ...prev, [key]: value }));
            if (validationResult) setValidationResult(null);
          }}
          onValidate={async () => {
            setIsChecking(true);
            try {
              const checkResult = await checkMCPServerInstanceConfiguration({
                json_spec: {
                  image: server.docker_image_url,
                  port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
                  environment: envVars,
                },
              });
              if (!checkResult.error) {
                setValidationResult(
                  checkResult.data as {
                    valid: boolean;
                    errors: string[];
                    warnings: string[];
                  }
                );
              }
            } catch (error) {
              console.error("Validation error:", error);
            } finally {
              setIsChecking(false);
            }
          }}
          validateDisabled={isChecking || !instanceName.trim()}
          validateLoading={isChecking}
          onForceCreate={() => createInstance(true)}
          forceCreateDisabled={isCreating || !instanceName.trim()}
          onSubmit={async (e) => {
            e?.preventDefault();
            if (!validationResult) return;
            await createInstance(false);
          }}
          submitDisabled={
            isCreating ||
            !instanceName.trim() ||
            (validationResult ? !validationResult.valid : false)
          }
          submitLabel={
            isCreating ? t("actions.creating") : t("actions.createInstance")
          }
          showContainerSummary
          containerImage={server.docker_image_url ?? undefined}
          containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
        />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function CreateMCPInstanceClient({
  server,
}: {
  server: MCPServer;
}) {
  const connType = getConnectionType(server);

  if (connType === "url") {
    return <UrlConnectForm server={server} />;
  }

  return <DockerCommandForm server={server} />;
}
