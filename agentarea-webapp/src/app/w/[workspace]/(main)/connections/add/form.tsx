"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Braces,
  Code,
  FileText,
  GitBranch,
  Globe,
  KeyRound,
  ListChecks,
  Package,
  Plus,
  Server,
  ShieldCheck,
  Tag,
  Tags,
  Terminal,
} from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { z } from "zod";
import { announceFormSubmitting } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { apiErrorMessage } from "@/lib/api-errors";
import { listMCPAuthConfigsAction as listMCPAuthConfigs, createMCPAuthConfigAction as createMCPAuthConfig } from "@/lib/server-actions";
import { HeaderRows } from "../components/HeaderRows";
import { SecretRows } from "../components/SecretRows";
import {
  addMCPServer,
  type MCPServerFormState,
  type MCPServerFormValues,
} from "./actions";

/** The header's submit button targets the form by this id. */
export const ADD_MCP_SERVER_FORM_ID = "add-mcp-server-form";

// Header rows for external servers; rows left without a name are dropped on
// submit rather than blocking it.
const HeaderSchema = z.object({
  key: z.string(),
  value: z.string(),
});

// Environment variable rows for docker / command servers. The key names a
// variable the server needs; the value is optional (leave it blank to declare a
// field someone fills in later). `secret` routes the value through the secret
// manager instead of storing it in plaintext. New rows default to secret; the
// user explicitly unlocks a value to store it as plain config — we never guess
// from the variable name.
const EnvVarSchema = z.object({
  key: z.string(),
  value: z.string(),
  secret: z.boolean(),
});

// The shape of the form; the messages are attached per locale in the component.
const BaseMCPServerSchema = z.object({
  type: z.enum(["docker", "command", "external"]),
  name: z.string().min(1),
  description: z.string().min(1),
  dockerImageUrl: z.string().optional(),
  version: z.string().optional(),
  command: z.string().optional(),
  args: z.string().optional(),
  endpointUrl: z.string().optional(),
  headers: z.array(HeaderSchema),
  env: z.array(EnvVarSchema),
  tags: z.string().optional(),
});

type FormValues = z.infer<typeof BaseMCPServerSchema>;
type ServerType = FormValues["type"];
type ConfigMode = "form" | "json";

const SERVER_TYPES: ServerType[] = ["docker", "command", "external"];

const REQUIRED_FIELD = {
  docker: "dockerImageUrl",
  command: "command",
  external: "endpointUrl",
} as const satisfies Record<ServerType, keyof FormValues>;

const initialState: MCPServerFormState = {
  message: "",
  errors: {},
  fieldValues: {
    type: "docker",
    name: "",
    description: "",
    dockerImageUrl: "",
    version: "1.0.0",
    command: "",
    args: "",
    endpointUrl: "",
    headers: [],
    tags: [],
  },
};

interface AuthConfig {
  id: string;
  name: string;
  auth_type: string;
}

type AuthType = "api_key" | "bearer" | "oauth2";

const AUTH_TYPES: AuthType[] = ["api_key", "bearer", "oauth2"];

export function AddMCPServerForm() {
  const t = useTranslations("MCPServersPage.newServer");
  const tAuth = useTranslations("MCPServersPage.authConfigs");
  const tCommon = useTranslations("Common");
  const { canAdminister } = useViewerCapabilities();
  const formRef = useRef<HTMLFormElement>(null);
  const [state, setState] = useState<MCPServerFormState>(initialState);
  const [authConfigs, setAuthConfigs] = useState<AuthConfig[]>([]);
  const [authConfigsError, setAuthConfigsError] = useState<string | null>(null);
  const [newAuthError, setNewAuthError] = useState<string | null>(null);
  const [selectedAuthConfigId, setSelectedAuthConfigId] = useState<string>("");
  const [showNewAuthForm, setShowNewAuthForm] = useState(false);
  const [newAuthType, setNewAuthType] = useState<AuthType>("api_key");
  const [newAuthName, setNewAuthName] = useState("");
  const [newAuthSaving, setNewAuthSaving] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonInput, setJsonInput] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const schema = useMemo(
    () =>
      BaseMCPServerSchema.extend({
        name: z.string().min(1, t("nameRequired")),
        description: z.string().min(1, t("descriptionRequired")),
      }).superRefine((data, ctx) => {
        // Each type has one field it can't run without; the error goes on
        // that field so it shows where the user has to type.
        const field = REQUIRED_FIELD[data.type];
        if (!data[field]?.trim()) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: t(`${field}Required`),
            path: [field],
          });
        }
      }),
    [t]
  );

  const fetchAuthConfigs = useCallback(async () => {
    setAuthConfigsError(null);
    try {
      const result = await listMCPAuthConfigs();
      if (result.error || !result.data) {
        console.error("Failed to load MCP auth configs", result.error);
        setAuthConfigsError(apiErrorMessage(result, tAuth("loadFailed")));
        return;
      }
      setAuthConfigs(result.data as AuthConfig[]);
    } catch (e) {
      console.error("Failed to load MCP auth configs", e);
      setAuthConfigsError(tAuth("loadFailed"));
    }
  }, [tAuth]);

  const handleCreateAuthConfig = useCallback(async (formEl: HTMLFormElement) => {
    setNewAuthSaving(true);
    setNewAuthError(null);
    try {
      const fd = new window.FormData(formEl);
      const authType = fd.get("newAuthType") as string;

      let config: Record<string, unknown> = {};
      let credentials: Record<string, unknown> = {};

      if (authType === "api_key") {
        config = { header_name: (fd.get("headerName") as string) || "Authorization" };
        credentials = { header_value: fd.get("headerValue") as string };
      } else if (authType === "bearer") {
        credentials = { token: fd.get("bearerToken") as string };
      } else if (authType === "oauth2") {
        config = {
          client_id: fd.get("clientId") as string,
          token_url: fd.get("tokenUrl") as string,
          authorize_url: (fd.get("authorizeUrl") as string) || undefined,
          scopes: (fd.get("scopes") as string)?.split(/\s+/).filter(Boolean) || [],
        };
        credentials = { client_secret: fd.get("clientSecret") as string };
      }

      const result = await createMCPAuthConfig({
        name: fd.get("newAuthName") as string,
        auth_type: authType,
        config,
        credentials,
      });

      if (result.error || !result.data) {
        console.error("Failed to create MCP auth config", result.error);
        setNewAuthError(apiErrorMessage(result, tAuth("createFailed")));
        return;
      }
      await fetchAuthConfigs();
      setSelectedAuthConfigId((result.data as { id: string }).id);
      setShowNewAuthForm(false);
      setNewAuthName("");
      setNewAuthType("api_key");
    } catch (e) {
      console.error("Failed to create MCP auth config", e);
      setNewAuthError(tAuth("createFailed"));
    } finally {
      setNewAuthSaving(false);
    }
  }, [fetchAuthConfigs, tAuth]);

  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
    setValue,
    getValues,
    watch,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      type: "docker",
      name: "",
      description: "",
      dockerImageUrl: "",
      version: "1.0.0",
      command: "",
      args: "",
      endpointUrl: "",
      headers: [],
      env: [],
      tags: "",
    },
  });

  const watchedType = watch("type");

  // Fetch auth configs when type is external
  useEffect(() => {
    if (watchedType === "external" && canAdminister) {
      fetchAuthConfigs();
    }
  }, [watchedType, canAdminister, fetchAuthConfigs]);

  const onSubmit = async (data: FormValues) => {
    announceFormSubmitting(formRef.current, true);
    setState(initialState);
    let leaving = false;

    try {
      const input: MCPServerFormValues = {
        ...data,
        headers: data.headers
          .filter((header) => header.key.trim())
          .map((header) => ({ ...header, key: header.key.trim() })),
        version: data.version || "1.0.0",
        authConfigId:
          selectedAuthConfigId && selectedAuthConfigId !== "none"
            ? selectedAuthConfigId
            : null,
      };

      const result = await addMCPServer(state, input);

      // addMCPServer calls redirect() on success which throws NEXT_REDIRECT
      // If we get here, it means there was an error
      if (result) {
        setState(result);
      }
    } catch (e: unknown) {
      // Next.js redirect throws — let it propagate, and keep the header
      // button busy until the new connection opens.
      if ((e as { digest?: string } | null)?.digest?.startsWith("NEXT_REDIRECT")) {
        leaving = true;
        throw e;
      }
      setState({
        message: t("unexpectedError"),
        errors: { _form: [e instanceof Error ? e.message : t("unexpectedError")] },
      });
    } finally {
      if (!leaving) announceFormSubmitting(formRef.current, false);
    }
  };

  // Build JSON from current form state (form → JSON)
  const formToJson = useCallback(() => {
    const type = watch("type");
    const name = watch("name");
    const description = watch("description");

    const envObj = (watch("env") || []).reduce<Record<string, string>>(
      (acc, e) => {
        if (e?.key?.trim()) acc[e.key.trim()] = e.value ?? "";
        return acc;
      },
      {}
    );
    const envPart = Object.keys(envObj).length ? { env: envObj } : {};

    if (type === "command") {
      const command = watch("command") || "";
      const argsStr = watch("args") || "";
      const args = argsStr.trim() ? argsStr.trim().split(/\s+/) : [];
      return JSON.stringify({ command, args, ...envPart, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    } else if (type === "external") {
      const endpointUrl = watch("endpointUrl") || "";
      return JSON.stringify({ url: endpointUrl, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    } else {
      const dockerImageUrl = watch("dockerImageUrl") || "";
      const version = watch("version") || "1.0.0";
      return JSON.stringify({ image: dockerImageUrl, version, ...envPart, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    }
  }, [watch]);

  // Parse JSON and apply to form (JSON → form)
  const applyJsonToForm = useCallback((raw: string) => {
    setJsonInput(raw);
    setJsonError(null);
    if (!raw.trim()) return;
    try {
      let parsed = JSON.parse(raw);
      let serverName = "";

      // Support: { "servers": { "name": { "type": "http", "url": "..." } } }
      if (parsed.servers && typeof parsed.servers === "object") {
        const keys = Object.keys(parsed.servers);
        if (keys.length === 1) {
          serverName = keys[0];
          parsed = { ...parsed.servers[serverName], _name: serverName, _inputs: parsed.inputs };
        }
      }
      // Support: { "mcpServers": { "name": { ... } } }
      if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
        const keys = Object.keys(parsed.mcpServers);
        if (keys.length === 1) {
          serverName = keys[0];
          parsed = { _name: serverName, ...parsed.mcpServers[serverName] };
        }
      }

      // Extract name/description
      if (parsed._name || parsed.name) {
        setValue("name", parsed._name || parsed.name);
      }
      if (parsed._description || parsed.description) {
        setValue("description", parsed._description || parsed.description);
      }

      // Detect type and extract fields
      if (parsed.command) {
        setValue("type", "command");
        setValue("command", parsed.command);
        setValue("args", Array.isArray(parsed.args) ? parsed.args.join(" ") : parsed.args || "");
      } else if (parsed.url || parsed.endpoint_url || parsed.type === "http" || parsed.type === "streamable-http") {
        setValue("type", "external");
        setValue("endpointUrl", parsed.url || parsed.endpoint_url || "");
        // Auto-set description for URL types
        if (!watch("description")) {
          setValue("description", `Remote MCP server${serverName ? ` (${serverName})` : ""}`);
        }
        // Extract headers
        if (parsed.headers && typeof parsed.headers === "object") {
          const headerEntries = Object.entries(parsed.headers).map(([key, value]) => ({
            key,
            value: String(value),
          }));
          setValue("headers", headerEntries);
        }
      } else if (parsed.image || parsed.docker_image_url) {
        setValue("type", "docker");
        setValue("dockerImageUrl", parsed.image || parsed.docker_image_url);
        if (parsed.version) setValue("version", parsed.version);
      }
      if (parsed.env && typeof parsed.env === "object") {
        const envEntries = Object.entries(parsed.env).map(([key, value]) => ({
          key,
          value: value == null ? "" : String(value),
          // Default pasted values to secret; the user can unlock plain config.
          secret: true,
        }));
        setValue("env", envEntries);
        const currentDesc = watch("description");
        if (!currentDesc) {
          setValue("description", `Environment: ${Object.keys(parsed.env).join(", ")}`);
        }
      }
      setJsonError(null);
    } catch {
      setJsonError(t("config.invalid"));
    }
  }, [setValue, watch, t]);

  // When switching to JSON mode, populate from current form state
  const toggleJsonMode = useCallback(() => {
    if (!jsonMode) {
      setJsonInput(formToJson());
      setJsonError(null);
    } else {
      // Switching back to form — apply current JSON to form
      if (jsonInput.trim()) {
        applyJsonToForm(jsonInput);
      }
    }
    setJsonMode(!jsonMode);
  }, [jsonMode, formToJson, jsonInput, applyJsonToForm]);

  // Combine react-hook-form errors and server action errors
  const combinedErrors = {
    ...errors,
    ...state.errors,
  };

  const getErrorMessage = (
    error: string | string[] | { message?: string } | undefined
  ) => {
    if (typeof error === "string") return error;
    if (Array.isArray(error)) return error[0];
    return error?.message;
  };

  const fieldError = (field: keyof typeof combinedErrors) => {
    const message = getErrorMessage(
      combinedErrors[field] as string | string[] | { message?: string } | undefined
    );
    return message ? (
      <p role="alert" className="form-error">
        {message}
      </p>
    ) : null;
  };

  const formError =
    state.errors?._form?.join(", ") ||
    (state.message && state.errors ? state.message : null);

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit(onSubmit)}
      id={ADD_MCP_SERVER_FORM_ID}
      className="mx-auto w-full max-w-4xl"
    >
      <div className="form-content">
        {formError && <FormError>{formError}</FormError>}

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            {jsonMode ? (
              <FormLabel htmlFor="mcp-config" icon={Braces} required>
                {t("config.label")}
              </FormLabel>
            ) : (
              <FormLabel htmlFor="type" icon={Server} required>
                <span id="server-type-label">{t("type.label")}</span>
              </FormLabel>
            )}
            <SegmentedControl<ConfigMode>
              value={jsonMode ? "json" : "form"}
              onChange={(mode) => {
                if ((mode === "json") !== jsonMode) toggleJsonMode();
              }}
              layoutId="mcp-config-mode-control"
              items={[
                {
                  value: "form",
                  label: (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <ListChecks aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
                      {t("mode.form")}
                    </span>
                  ),
                },
                {
                  value: "json",
                  label: (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <Braces aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.8} />
                      {t("mode.json")}
                    </span>
                  ),
                },
              ]}
            />
          </div>

          {jsonMode ? (
            <>
              <Textarea
                id="mcp-config"
                value={jsonInput}
                onChange={(e) => applyJsonToForm(e.target.value)}
                placeholder={'{\n  "servers": {\n    "github": {\n      "type": "http",\n      "url": "https://api.githubcopilot.com/mcp/"\n    }\n  }\n}'}
                className="h-[260px] resize-none font-mono text-xs"
                aria-invalid={Boolean(jsonError)}
              />
              {jsonError ? (
                <p role="alert" className="form-error">
                  {jsonError}
                </p>
              ) : (
                <p className="note">{t("config.hint")}</p>
              )}
            </>
          ) : (
            <Controller
              control={control}
              name="type"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger
                    id="type"
                    aria-labelledby="server-type-label"
                    aria-required="true"
                  >
                    <SelectValue placeholder={t("type.placeholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {SERVER_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {t(`type.${type}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          )}
          {fieldError("type")}
          {/* In JSON mode the fields are hidden: say here what the config
              still lacks. */}
          {jsonMode && (
            <>
              {fieldError("name")}
              {fieldError("description")}
              {fieldError(REQUIRED_FIELD[watchedType])}
            </>
          )}
        </div>
      </div>

      {!jsonMode && (
        <>
          <Divider className="my-6" />

          <div className="form-content">
            <div className="space-y-2">
              <FormLabel htmlFor="name" icon={Tag} required>
                {t("name")}
              </FormLabel>
              <Input
                id="name"
                {...register("name")}
                placeholder={t("namePlaceholder")}
                autoComplete="off"
                aria-invalid={!!combinedErrors.name}
              />
              {fieldError("name")}
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="description" icon={FileText} required>
                {t("description")}
              </FormLabel>
              <Textarea
                id="description"
                {...register("description")}
                placeholder={t("descriptionPlaceholder")}
                className="h-[100px] resize-none"
                aria-invalid={!!combinedErrors.description}
              />
              {fieldError("description")}
            </div>

            {watchedType === "docker" && (
              <>
                <div className="space-y-2">
                  <FormLabel htmlFor="dockerImageUrl" icon={Package} required>
                    {t("dockerImageUrl")}
                  </FormLabel>
                  <Input
                    id="dockerImageUrl"
                    {...register("dockerImageUrl")}
                    placeholder="ghcr.io/anthropic/mcp-file-server:latest"
                    aria-invalid={!!combinedErrors.dockerImageUrl}
                  />
                  {fieldError("dockerImageUrl") ?? (
                    <p className="note">{t("dockerImageUrlHint")}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <FormLabel htmlFor="version" icon={GitBranch} optional>
                    {t("version")}
                  </FormLabel>
                  <Input
                    id="version"
                    {...register("version")}
                    placeholder="1.0.0"
                    aria-invalid={!!combinedErrors.version}
                  />
                  {fieldError("version")}
                </div>
              </>
            )}

            {watchedType === "command" && (
              <>
                <div className="space-y-2">
                  <FormLabel htmlFor="command" icon={Terminal} required>
                    {t("command")}
                  </FormLabel>
                  <Input
                    id="command"
                    {...register("command")}
                    placeholder="npx, uvx, node"
                    className="font-mono"
                    aria-invalid={!!combinedErrors.command}
                  />
                  {fieldError("command") ?? (
                    <p className="note">{t("commandHint")}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <FormLabel htmlFor="args" icon={Code} optional>
                    {t("args")}
                  </FormLabel>
                  <Input
                    id="args"
                    {...register("args")}
                    placeholder="-y @modelcontextprotocol/server-filesystem /tmp"
                    className="font-mono"
                  />
                  <p className="note">{t("argsHint")}</p>
                </div>
              </>
            )}

            {watchedType === "external" && (
              <div className="space-y-2">
                <FormLabel htmlFor="endpointUrl" icon={Globe} required>
                  {t("endpointUrl")}
                </FormLabel>
                <Input
                  id="endpointUrl"
                  {...register("endpointUrl")}
                  placeholder="https://api.example.com/mcp"
                  type="url"
                  aria-invalid={!!combinedErrors.endpointUrl}
                />
                {fieldError("endpointUrl") ?? (
                  <p className="note">{t("endpointUrlHint")}</p>
                )}
              </div>
            )}

            <div className="space-y-2">
              <FormLabel htmlFor="tags" icon={Tags} optional>
                {t("tags")}
              </FormLabel>
              <Input
                id="tags"
                {...register("tags")}
                placeholder={t("tagsPlaceholder")}
              />
              <p className="note">{t("tagsHint")}</p>
            </div>
          </div>

          <Divider className="my-6" />

          <div className="form-content">
            {(watchedType === "docker" || watchedType === "command") && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <FormLabel icon={KeyRound} optional>
                    {t("env.label")}
                  </FormLabel>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    onClick={() =>
                      setValue("env", [
                        ...getValues("env"),
                        { key: "", value: "", secret: true },
                      ])
                    }
                  >
                    <Plus />
                    {t("env.add")}
                  </Button>
                </div>
                <Controller
                  control={control}
                  name="env"
                  render={({ field }) => (
                    <SecretRows
                      rows={field.value.map((row) => ({
                        name: row.key,
                        value: row.value,
                        secret: row.secret,
                      }))}
                      onChange={(rows) =>
                        field.onChange(
                          rows.map((row) => ({
                            key: row.name,
                            value: row.value,
                            secret: row.secret,
                          }))
                        )
                      }
                      namePlaceholder={t("env.keyPlaceholder")}
                      valuePlaceholder={t("env.valuePlaceholder")}
                      nameClassName="font-mono"
                    />
                  )}
                />
                <p className="note">{t("env.hint")}</p>
              </div>
            )}

            {watchedType === "external" && (
              <>
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <FormLabel icon={KeyRound} optional>
                      {t("headers.label")}
                    </FormLabel>
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      onClick={() =>
                        setValue("headers", [
                          ...getValues("headers"),
                          { key: "", value: "" },
                        ])
                      }
                    >
                      <Plus />
                      {t("headers.add")}
                    </Button>
                  </div>
                  <Controller
                    control={control}
                    name="headers"
                    render={({ field }) => (
                      <HeaderRows
                        alwaysSecret
                        rows={field.value.map((row) => ({
                          name: row.key,
                          value: row.value,
                        }))}
                        onChange={(rows) =>
                          field.onChange(
                            rows.map((row) => ({ key: row.name, value: row.value }))
                          )
                        }
                      />
                    )}
                  />
                  <p className="note">{t("headers.hint")}</p>
                </div>

                <div className="space-y-2">
                  <FormLabel htmlFor="authConfigId" icon={ShieldCheck} optional>
                    {t("auth.label")}
                  </FormLabel>
                  <Select
                    value={selectedAuthConfigId}
                    disabled={!canAdminister}
                    onValueChange={(value) => {
                      if (value === "__new__") {
                        setShowNewAuthForm(true);
                        setSelectedAuthConfigId("");
                      } else {
                        setSelectedAuthConfigId(value);
                        setShowNewAuthForm(false);
                      }
                    }}
                  >
                    <SelectTrigger id="authConfigId">
                      <SelectValue placeholder={t("auth.none")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("auth.none")}</SelectItem>
                      {authConfigs.map((config) => (
                        <SelectItem key={config.id} value={config.id}>
                          {config.name} ({config.auth_type})
                        </SelectItem>
                      ))}
                      <SelectItem value="__new__">{t("auth.createNew")}</SelectItem>
                    </SelectContent>
                  </Select>
                  {!canAdminister && <AdminOnlyHint action="manageMcpAuth" />}
                  {authConfigsError ? (
                    <p role="alert" className="form-error">
                      {authConfigsError}
                    </p>
                  ) : (
                    <p className="note">{t("auth.hint")}</p>
                  )}

                  {/* Inline auth config creation. Its inputs are collected
                      from this panel on save, not submitted with the form. */}
                  {showNewAuthForm && (
                    <div
                      data-auth-config-panel
                      className="mt-3 space-y-4 rounded-lg border p-4"
                    >
                      <p className="text-sm font-medium">{t("auth.newTitle")}</p>

                      <div className="space-y-2">
                        <FormLabel htmlFor="newAuthName" required>
                          {t("auth.configName")}
                        </FormLabel>
                        <Input
                          id="newAuthName"
                          name="newAuthName"
                          value={newAuthName}
                          onChange={(e) => setNewAuthName(e.target.value)}
                          placeholder={t("auth.configNamePlaceholder")}
                        />
                      </div>

                      <div className="space-y-2">
                        <FormLabel htmlFor="newAuthType">{t("auth.type")}</FormLabel>
                        <Select
                          value={newAuthType}
                          onValueChange={(v) => setNewAuthType(v as AuthType)}
                        >
                          <SelectTrigger id="newAuthType">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {AUTH_TYPES.map((type) => (
                              <SelectItem key={type} value={type}>
                                {t(`auth.types.${type}`)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <input type="hidden" name="newAuthType" value={newAuthType} />
                      </div>

                      {newAuthType === "api_key" && (
                        <>
                          <div className="space-y-2">
                            <FormLabel htmlFor="headerName">{t("auth.headerName")}</FormLabel>
                            <Input id="headerName" name="headerName" defaultValue="Authorization" placeholder="Authorization" />
                          </div>
                          <div className="space-y-2">
                            <FormLabel htmlFor="headerValue">{t("auth.headerValue")}</FormLabel>
                            <Input id="headerValue" name="headerValue" type="password" placeholder={t("auth.headerValuePlaceholder")} />
                          </div>
                        </>
                      )}

                      {newAuthType === "bearer" && (
                        <div className="space-y-2">
                          <FormLabel htmlFor="bearerToken">{t("auth.bearerToken")}</FormLabel>
                          <Input id="bearerToken" name="bearerToken" type="password" placeholder={t("auth.bearerTokenPlaceholder")} />
                        </div>
                      )}

                      {newAuthType === "oauth2" && (
                        <>
                          <div className="space-y-2">
                            <FormLabel htmlFor="clientId">{t("auth.clientId")}</FormLabel>
                            <Input id="clientId" name="clientId" />
                          </div>
                          <div className="space-y-2">
                            <FormLabel htmlFor="clientSecret">{t("auth.clientSecret")}</FormLabel>
                            <Input id="clientSecret" name="clientSecret" type="password" />
                          </div>
                          <div className="space-y-2">
                            <FormLabel htmlFor="tokenUrl">{t("auth.tokenUrl")}</FormLabel>
                            <Input id="tokenUrl" name="tokenUrl" placeholder="https://provider.com/oauth/token" />
                          </div>
                          <div className="space-y-2">
                            <FormLabel htmlFor="authorizeUrl" optional>{t("auth.authorizeUrl")}</FormLabel>
                            <Input id="authorizeUrl" name="authorizeUrl" placeholder="https://provider.com/oauth/authorize" />
                          </div>
                          <div className="space-y-2">
                            <FormLabel htmlFor="scopes" optional>{t("auth.scopes")}</FormLabel>
                            <Input id="scopes" name="scopes" placeholder="read write" />
                          </div>
                        </>
                      )}

                      {newAuthError && (
                        <p role="alert" className="form-error">
                          {newAuthError}
                        </p>
                      )}

                      <div className="flex gap-2">
                        <Button
                          type="button"
                          size="xs"
                          isLoading={newAuthSaving}
                          disabled={newAuthSaving || !newAuthName}
                          onClick={(e) => {
                            const panel = (e.currentTarget as HTMLElement).closest(
                              "[data-auth-config-panel]"
                            );
                            if (panel) {
                              const tempForm = document.createElement("form");
                              panel.querySelectorAll("input, select").forEach((el) => {
                                tempForm.appendChild(el.cloneNode(true));
                              });
                              handleCreateAuthConfig(tempForm);
                            }
                          }}
                        >
                          {t("auth.save")}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="xs"
                          onClick={() => setShowNewAuthForm(false)}
                        >
                          {tCommon("cancel")}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </form>
  );
}
