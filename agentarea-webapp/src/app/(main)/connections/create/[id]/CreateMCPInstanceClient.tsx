"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { ExternalLink, Github, Globe, Key } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToolsTable } from "../../components/ToolsTable";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
  validateConnectionAction,
  probeInstanceAuthAction,
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

interface ValidationResult {
  status: string;
  tool_count?: number;
  tools?: Array<{ name: string; description: string }>;
  message?: string;
}

type ProbeState = "idle" | "needs_oauth" | "needs_both";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface McpJsonSpec {
  icons?: Array<{ src: string }>;
  title?: string;
  remotes?: Array<{ headers?: FieldSpec[] }>;
  repository?: { url?: string; source?: string };
  websiteUrl?: string;
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

function SpecHeader({ server }: { server: MCPServer }) {
  const iconSrc = getIcon(server);
  const title = getTitle(server);
  const repoUrl = getRepoUrl(server);
  const websiteUrl = getWebsiteUrl(server);
  const repoSource = getRepoSource(server);

  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <div className="rounded-full bg-muted p-4">
        {iconSrc ? (
          <Image
            src={iconSrc}
            alt={title}
            width={32}
            height={32}
            className="h-8 w-8 rounded"
            unoptimized
          />
        ) : (
          <Globe className="h-8 w-8 text-muted-foreground" />
        )}
      </div>
      <div className="space-y-1">
        <h3 className="text-lg font-semibold">{title}</h3>
        {server.description && (
          <p className="mt-1 text-sm text-muted-foreground max-w-lg">{server.description}</p>
        )}
        {(repoUrl || websiteUrl) && (
          <div className="flex items-center justify-center gap-3 pt-1">
            {repoUrl && (
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {repoSource === "github" ? <Github className="h-3 w-3" /> : <Globe className="h-3 w-3" />}
                {repoSource === "github" ? "GitHub" : "Repository"}
              </a>
            )}
            {websiteUrl && (
              <a
                href={websiteUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <ExternalLink className="h-3 w-3" />
                Website
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tools preview table (same style as detail page)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// URL-type connect form (react-hook-form)
// ---------------------------------------------------------------------------

interface UrlFormValues {
  instanceName: string;
  fields: Record<string, string>;
}

function UrlConnectForm({ server }: { server: MCPServer }) {
  const router = useRouter();
  const remoteHeaders = getRemoteHeaders(server);
  const hasFields = remoteHeaders.length > 0;
  const endpointUrl = server.remote_url || "";

  const defaultFieldValues: Record<string, string> = {};
  for (const h of remoteHeaders) {
    defaultFieldValues[h.name] = h.default || "";
  }

  const {
    register,
    getValues,
  } = useForm<UrlFormValues>({
    defaultValues: {
      instanceName: getTitle(server),
      fields: defaultFieldValues,
    },
  });

  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [probeState, setProbeState] = useState<ProbeState>("idle");
  const [authTab, setAuthTab] = useState<"oauth" | "manual">("manual");
  const [createdInstanceId, setCreatedInstanceId] = useState<string | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{ id: string; name: string } | null>(null);

  // Build headers dict from form field values
  const buildHeaders = (): Record<string, string> => {
    const vals = getValues("fields");
    const headers: Record<string, string> = {};
    for (const [key, val] of Object.entries(vals)) {
      if (val?.trim()) headers[key] = val.trim();
    }
    return headers;
  };

  // Validate connection (fields present)
  const handleValidate = async () => {
    setError(null);
    setValidation(null);
    setIsWorking(true);

    try {
      if (hasFields) {
        const result = await validateConnectionAction(endpointUrl, buildHeaders());

        if (result.error) {
          setError(result.error);
          return;
        }
        if (result.data?.status === "auth_error") {
          setError(result.data.message || "Authentication failed");
          return;
        }
        if (result.data?.status !== "ok") {
          setError(result.data?.message || "Connection failed");
          return;
        }

        setValidation(result.data);
        return;
      }

      // No fields — probe for auth method
      const { instanceName } = getValues();
      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: server.description,
        server_spec_id: server.id,
        json_spec: { type: "url", endpoint_url: endpointUrl },
      });

      if (instanceResult.error) {
        const d = instanceResult.error.detail;
        throw new Error(
          typeof d === "string"
            ? d
            : Array.isArray(d) && d[0]?.msg
              ? d[0].msg
              : "Failed to create instance"
        );
      }

      const created = instanceResult.data;
      setCreatedInstanceId(created.id);

      const probeResult = await probeInstanceAuthAction(created.id);

      if (probeResult.data?.status === "ok") {
        router.push(`/connections/${created.id}`);
        return;
      }
      if (probeResult.data?.status === "auth_required") {
        const methods = probeResult.data.methods || [];
        if (methods.includes("oauth")) {
          setProbeState(methods.includes("credentials") ? "needs_both" : "needs_oauth");
          setAuthTab("oauth");
          return;
        }
      }

      router.push(`/connections/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setIsWorking(false);
    }
  };

  // Create instance after successful validation
  const handleCreate = async () => {
    setIsWorking(true);
    setError(null);
    try {
      const { instanceName } = getValues();
      const headers = buildHeaders();

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
              : "Failed to create instance"
        );
      }

      const created = instanceResult.data;
      const vStatus = created?.verification?.status;
      if (vStatus === "in_progress" || vStatus === "never_attempted") {
        const { instanceName } = getValues();
        setVerifyingInstance({ id: created.id, name: instanceName });
      } else {
        router.push(`/connections/${created.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connection");
    } finally {
      setIsWorking(false);
    }
  };

  // OAuth flow
  const handleOAuth = async () => {
    if (!createdInstanceId) return;
    setIsWorking(true);
    setError(null);
    try {
      const result = await oauthAuthorizeAction(createdInstanceId);
      if (result.error || !result.data?.authorize_url) {
        setError(result.error || "OAuth discovery failed — this server may not support OAuth");
        return;
      }
      window.location.href = result.data.authorize_url;
    } catch {
      setError("Failed to start OAuth flow");
    } finally {
      setIsWorking(false);
    }
  };

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
    <div className="mx-auto w-full max-w-4xl space-y-6 py-8">
      <SpecHeader server={server} />

      {/* Instance name */}
      <div className="space-y-1.5">
        <Label htmlFor="instance-name">Name</Label>
        <Input id="instance-name" {...register("instanceName", { required: true })} />
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Spec fields */}
      {hasFields && probeState === "idle" && (
        <div className="space-y-4">
          {remoteHeaders.map((field) => (
            <div key={field.name} className="space-y-1.5">
              <Label htmlFor={`field-${field.name}`}>
                {field.name}
                {field.isRequired !== false && (
                  <span className="ml-1 text-destructive">*</span>
                )}
              </Label>
              {field.description && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
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

      {/* Validation success — tools table + create button */}
      {validation?.status === "ok" && (
        <div className="space-y-4">
          {validation.tools && validation.tools.length > 0 && (
            <ToolsTable tools={validation.tools} label={`${validation.tools.length} tools found`} />
          )}
          <Button
            className="w-full"
            size="lg"
            onClick={handleCreate}
            isLoading={isWorking}
            disabled={isWorking}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Create Connection
          </Button>
        </div>
      )}

      {/* Connect button — initial state */}
      {!validation && probeState === "idle" && (
        <Button
          className="w-full"
          size="lg"
          onClick={handleValidate}
          isLoading={isWorking}
          disabled={isWorking}
        >
          <ExternalLink className="mr-2 h-4 w-4" />
          {isWorking ? "Connecting..." : "Connect"}
        </Button>
      )}

      {/* OAuth/Manual switcher (probe detected auth) */}
      {(probeState === "needs_oauth" || probeState === "needs_both") && (
        <div className="space-y-4">
          {probeState === "needs_both" && (
            <div className="mx-auto flex w-fit rounded-lg border p-0.5">
              <button
                type="button"
                className={`rounded-md px-4 py-1.5 text-sm transition-colors ${authTab === "oauth" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setAuthTab("oauth")}
              >
                OAuth
              </button>
              <button
                type="button"
                className={`rounded-md px-4 py-1.5 text-sm transition-colors ${authTab === "manual" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setAuthTab("manual")}
              >
                Manual
              </button>
            </div>
          )}

          {(authTab === "oauth" || probeState === "needs_oauth") && (
            <div className="space-y-3">
              <p className="text-center text-sm text-muted-foreground">
                This server supports OAuth authorization.
              </p>
              <Button className="w-full" size="lg" onClick={handleOAuth} isLoading={isWorking}>
                <ExternalLink className="mr-2 h-4 w-4" />
                Authorize with OAuth
              </Button>
              {probeState === "needs_oauth" && (
                <button
                  type="button"
                  className="w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => {
                    setProbeState("needs_both");
                    setAuthTab("manual");
                  }}
                >
                  Have credentials? Enter manually instead
                </button>
              )}
            </div>
          )}

          {authTab === "manual" && probeState === "needs_both" && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="manual-header">Authorization</Label>
                <Input
                  id="manual-header"
                  placeholder="Bearer your-token"
                  {...register("fields.Authorization")}
                />
              </div>
              <Button
                className="w-full"
                size="lg"
                onClick={handleCreate}
                isLoading={isWorking}
                disabled={isWorking}
              >
                <Key className="mr-2 h-4 w-4" />
                Connect
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Retry on error */}
      {error && (
        <Button
          variant="outline"
          className="w-full"
          onClick={() => {
            setError(null);
            setValidation(null);
          }}
        >
          Try Again
        </Button>
      )}
    </div>
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
  const [instanceDescription, setInstanceDescription] = useState(server.description);
  const [envVars, setEnvVars] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    server.env_schema?.forEach((envVar) => {
      init[envVar.name as string] = (envVar.default as string) || "";
    });
    return init;
  });
  const [isCreating, setIsCreating] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{ id: string; name: string } | null>(null);
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
      <div className="mx-auto w-full max-w-xl space-y-6 py-8">
        <SpecHeader server={server} />
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
          submitLabel={isCreating ? t("actions.creating") : t("actions.createInstance")}
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
