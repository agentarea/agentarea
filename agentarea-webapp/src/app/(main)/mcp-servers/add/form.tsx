"use client";

import { useActionState, useCallback, useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Code, Globe, Package, Plus, Server, Tag, Terminal, X } from "lucide-react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { addMCPServer, MCPServerFormState } from "./actions";

// Define the header schema for external servers
const HeaderSchema = z.object({
  key: z.string().min(1, "Header key is required"),
  value: z.string().min(1, "Header value is required"),
});

// Define the unified schema for client-side validation
// Create base schema without refine for shape access
const BaseMCPServerSchema = z.object({
  type: z.enum(["docker", "command", "external"], {
    required_error: "Server type is required",
  }),
  name: z.string().min(1, "Server name is required"),
  description: z.string().min(1, "Description is required"),
  dockerImageUrl: z.string().optional(),
  version: z.string().optional(),
  command: z.string().optional(),
  args: z.string().optional(),
  endpointUrl: z.string().optional(),
  headers: z.array(HeaderSchema),
  tags: z.string().optional(),
  isPublic: z.boolean(),
});

const MCPServerSchema = BaseMCPServerSchema.refine(
  (data) => {
    if (data.type === "docker") {
      return data.dockerImageUrl && data.dockerImageUrl.trim() !== "";
    } else if (data.type === "command") {
      return data.command && data.command.trim() !== "";
    } else if (data.type === "external") {
      return data.endpointUrl && data.endpointUrl.trim() !== "";
    }
    return false;
  },
  {
    message: "Required fields missing for selected server type",
    path: ["type"],
  }
);

type FormData = z.infer<typeof BaseMCPServerSchema>;

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
    isPublic: true,
  },
};

interface AuthConfig {
  id: string;
  name: string;
  auth_type: string;
}

type AuthType = "api_key" | "bearer" | "oauth2";

export function AddMCPServerForm() {
  const [state, formAction] = useActionState(addMCPServer, initialState);
  const [serverType, setServerType] = useState<"docker" | "command" | "external">("docker");
  const [authConfigs, setAuthConfigs] = useState<AuthConfig[]>([]);
  const [selectedAuthConfigId, setSelectedAuthConfigId] = useState<string>("");
  const [showNewAuthForm, setShowNewAuthForm] = useState(false);
  const [newAuthType, setNewAuthType] = useState<AuthType>("api_key");
  const [newAuthName, setNewAuthName] = useState("");
  const [newAuthSaving, setNewAuthSaving] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonInput, setJsonInput] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const fetchAuthConfigs = useCallback(async () => {
    try {
      const { listMCPAuthConfigs } = await import("@/lib/browser-api");
      const { data } = await listMCPAuthConfigs();
      if (data) {
        setAuthConfigs(data as AuthConfig[]);
      }
    } catch {
      // Auth configs may not be available yet
    }
  }, []);

  const handleCreateAuthConfig = useCallback(async (formEl: HTMLFormElement) => {
    setNewAuthSaving(true);
    try {
      const { createMCPAuthConfig } = await import("@/lib/browser-api");
      const fd = new FormData(formEl);
      const authType = fd.get("newAuthType") as string;

      let config: Record<string, any> = {};
      let credentials: Record<string, any> = {};

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

      const { data } = await createMCPAuthConfig({
        name: fd.get("newAuthName") as string,
        auth_type: authType,
        config,
        credentials,
      });

      if (data) {
        await fetchAuthConfigs();
        setSelectedAuthConfigId((data as any).id);
        setShowNewAuthForm(false);
        setNewAuthName("");
        setNewAuthType("api_key");
      }
    } catch {
      // Error creating auth config
    } finally {
      setNewAuthSaving(false);
    }
  }, [fetchAuthConfigs]);

  useEffect(() => {
    if (serverType === "external") {
      fetchAuthConfigs();
    }
  }, [serverType, fetchAuthConfigs]);

  const {
    register,
    control,
    formState: { errors },
    setValue,
    watch,
  } = useForm<FormData>({
    resolver: zodResolver(BaseMCPServerSchema),
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
      tags: "",
      isPublic: true,
    },
  });

  const { fields, append, remove } = useFieldArray({
    control,
    name: "headers",
  });

  const watchedType = watch("type");

  // Build JSON from current form state (form → JSON)
  const formToJson = useCallback(() => {
    const type = watch("type");
    const name = watch("name");
    const description = watch("description");

    if (type === "command") {
      const command = watch("command") || "";
      const argsStr = watch("args") || "";
      const args = argsStr.trim() ? argsStr.trim().split(/\s+/) : [];
      return JSON.stringify({ command, args, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    } else if (type === "external") {
      const endpointUrl = watch("endpointUrl") || "";
      return JSON.stringify({ url: endpointUrl, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    } else {
      const dockerImageUrl = watch("dockerImageUrl") || "";
      const version = watch("version") || "1.0.0";
      return JSON.stringify({ image: dockerImageUrl, version, ...(name ? { _name: name } : {}), ...(description ? { _description: description } : {}) }, null, 2);
    }
  }, [watch]);

  // Parse JSON and apply to form (JSON → form)
  const applyJsonToForm = useCallback((raw: string) => {
    setJsonInput(raw);
    setJsonError(null);
    if (!raw.trim()) return;
    try {
      let parsed = JSON.parse(raw);
      // Support pasting full mcpServers config: { "mcpServers": { "name": { ... } } }
      if (parsed.mcpServers && typeof parsed.mcpServers === "object") {
        const keys = Object.keys(parsed.mcpServers);
        if (keys.length === 1) {
          const serverName = keys[0];
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
        setServerType("command");
        setValue("command", parsed.command);
        setValue("args", Array.isArray(parsed.args) ? parsed.args.join(" ") : parsed.args || "");
      } else if (parsed.url || parsed.endpoint_url) {
        setValue("type", "external");
        setServerType("external");
        setValue("endpointUrl", parsed.url || parsed.endpoint_url);
      } else if (parsed.image || parsed.docker_image_url) {
        setValue("type", "docker");
        setServerType("docker");
        setValue("dockerImageUrl", parsed.image || parsed.docker_image_url);
        if (parsed.version) setValue("version", parsed.version);
      }
      if (parsed.env) {
        const currentDesc = watch("description");
        if (!currentDesc) {
          setValue("description", `Environment: ${Object.keys(parsed.env).join(", ")}`);
        }
      }
      setJsonError(null);
    } catch {
      setJsonError("Invalid JSON");
    }
  }, [setValue, watch]);

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

  // Update server type when form type changes
  useEffect(() => {
    setServerType(watchedType);
  }, [watchedType]);

  // Update form with values returned from server action
  useEffect(() => {
    if (state.fieldValues) {
      Object.entries(state.fieldValues).forEach(([key, value]) => {
        if (BaseMCPServerSchema.shape && key in BaseMCPServerSchema.shape) {
          setValue(key as keyof FormData, value as string | boolean);
        }
      });
    }
  }, [state, setValue]);

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

  return (
    <form action={formAction} id="add-mcp-server-form" className="overflow-auto h-full">
      <div className="form-content lg:max-w-xl lg:mx-auto">
        {/* Display general form errors */}
        {state.errors?._form && (
          <div className="form-error text-sm text-destructive">
            {state.errors._form.join(", ")}
          </div>
        )}

        {/* Server Type Selector */}
        <div className="space-y-2">
          <FormLabel htmlFor="type" icon={Server} required>Server Type</FormLabel>
          <Controller
            control={control}
            name="type"
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={(value) => {
                  field.onChange(value);
                  setServerType(value as "docker" | "command" | "external");
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select server type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="docker">Docker Image</SelectItem>
                  <SelectItem value="command">Command (npx / uvx)</SelectItem>
                  <SelectItem value="external">External URL</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
          <input type="hidden" {...register("type")} />
          {combinedErrors.type && (
            <p className="form-error">
              {getErrorMessage(combinedErrors.type)}
            </p>
          )}
        </div>

        {/* Form / JSON Mode Toggle */}
        <div className="flex items-center gap-1 rounded-md border p-0.5 w-fit">
          <button
            type="button"
            className={`px-3 py-1 text-sm rounded transition-colors ${!jsonMode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => jsonMode && toggleJsonMode()}
          >
            Form
          </button>
          <button
            type="button"
            className={`px-3 py-1 text-sm rounded transition-colors ${jsonMode ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
            onClick={() => !jsonMode && toggleJsonMode()}
          >
            JSON
          </button>
        </div>

        {jsonMode ? (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Edit the config directly or paste from .cursor/mcp.json
            </p>
            <Textarea
              value={jsonInput}
              onChange={(e) => applyJsonToForm(e.target.value)}
              placeholder={'{\n  "mcpServers": {\n    "my-server": {\n      "command": "npx",\n      "args": ["-y", "@some/mcp-server"]\n    }\n  }\n}'}
              rows={14}
              className="font-mono text-sm"
            />
            {jsonError && (
              <p className="text-sm text-red-500">{jsonError}</p>
            )}
          </div>
        ) : (
        <>
        {/* Common Fields */}
        <div className="space-y-2">
          <FormLabel htmlFor="name" icon={Server} required>Server Name</FormLabel>
          <Input
            id="name"
            {...register("name")}
            placeholder="e.g. File System MCP"
            aria-invalid={!!combinedErrors.name}
          />
          {combinedErrors.name && (
            <p className="form-error">
              {getErrorMessage(combinedErrors.name)}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <FormLabel htmlFor="description" required>Description</FormLabel>
          <Textarea
            id="description"
            {...register("description")}
            placeholder="Describe what this MCP server does"
            rows={3}
            aria-invalid={!!combinedErrors.description}
          />
          {combinedErrors.description && (
            <p className="form-error">
              {getErrorMessage(combinedErrors.description)}
            </p>
          )}
        </div>

        {/* Docker-specific Fields */}
        {serverType === "docker" && (
          <>
            <div className="space-y-2">
              <FormLabel htmlFor="dockerImageUrl" icon={Package} required>Docker Image URL</FormLabel>
              <Input
                id="dockerImageUrl"
                {...register("dockerImageUrl")}
                placeholder="e.g. ghcr.io/anthropic/mcp-file-server:latest"
                aria-invalid={!!combinedErrors.dockerImageUrl}
              />
              {combinedErrors.dockerImageUrl && (
                <p className="form-error">
                  {getErrorMessage(combinedErrors.dockerImageUrl)}
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                Enter the full URL to a Docker image that implements the Model
                Context Protocol. The image should expose port 8999.
              </p>
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="version" icon={Tag}>Version</FormLabel>
              <Input
                id="version"
                {...register("version")}
                placeholder="e.g. 1.0.0"
                defaultValue="1.0.0"
                aria-invalid={!!combinedErrors.version}
              />
              {combinedErrors.version && (
                <p className="form-error">
                  {getErrorMessage(combinedErrors.version)}
                </p>
              )}
            </div>
          </>
        )}

        {/* Command-specific Fields */}
        {serverType === "command" && (
          <>
            <div className="space-y-2">
              <FormLabel htmlFor="command" icon={Terminal} required>Command</FormLabel>
              <Input
                id="command"
                {...register("command")}
                placeholder="e.g. npx, uvx, node"
                aria-invalid={!!combinedErrors.command}
              />
              {combinedErrors.command && (
                <p className="form-error">
                  {getErrorMessage(combinedErrors.command)}
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                The command to run. It will be wrapped in a sandbox container
                with supergateway for HTTP transport.
              </p>
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="args" icon={Code} optional>Arguments</FormLabel>
              <Input
                id="args"
                {...register("args")}
                placeholder="e.g. -y @modelcontextprotocol/server-filesystem /tmp"
              />
              <p className="text-sm text-muted-foreground">
                Space-separated arguments passed to the command.
              </p>
            </div>
          </>
        )}

        {/* External-specific Fields */}
        {serverType === "external" && (
          <>
            <div className="space-y-2">
              <FormLabel htmlFor="endpointUrl" icon={Globe} required>Endpoint URL</FormLabel>
              <Input
                id="endpointUrl"
                {...register("endpointUrl")}
                placeholder="e.g. https://api.example.com/mcp"
                aria-invalid={!!combinedErrors.endpointUrl}
              />
              {combinedErrors.endpointUrl && (
                <p className="form-error">
                  {getErrorMessage(combinedErrors.endpointUrl)}
                </p>
              )}
              <p className="text-sm text-muted-foreground">
                Enter the URL where your external MCP server is running.
              </p>
            </div>

            {/* Headers */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Headers (optional)</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => append({ key: "", value: "" })}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Add Header
                </Button>
              </div>

              {fields.map((field, index) => (
                <div key={field.id} className="flex items-center gap-2">
                  <Input
                    {...register(`headers.${index}.key`)}
                    placeholder="Header name"
                    className="flex-1"
                  />
                  <Input
                    {...register(`headers.${index}.value`)}
                    placeholder="Header value"
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => remove(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}

              <p className="text-sm text-muted-foreground">
                Add any custom headers required for authentication or
                configuration.
              </p>
            </div>

            {/* Auth Config Selector */}
            <div className="space-y-2">
              <Label htmlFor="authConfigId">Authentication (optional)</Label>
              <Select
                value={selectedAuthConfigId}
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
                <SelectTrigger>
                  <SelectValue placeholder="No authentication" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No authentication</SelectItem>
                  {authConfigs.map((config) => (
                    <SelectItem key={config.id} value={config.id}>
                      {config.name} ({config.auth_type})
                    </SelectItem>
                  ))}
                  <SelectItem value="__new__">+ Create new auth config</SelectItem>
                </SelectContent>
              </Select>
              <input
                type="hidden"
                name="authConfigId"
                value={selectedAuthConfigId === "none" ? "" : selectedAuthConfigId}
              />

              {/* Inline Auth Config Creation Form */}
              {showNewAuthForm && (
                <div className="mt-3 rounded-md border p-4 space-y-3">
                  <p className="text-sm font-medium">New Authentication Config</p>

                  <div className="space-y-1">
                    <Label htmlFor="newAuthName">Config Name</Label>
                    <Input
                      id="newAuthName"
                      name="newAuthName"
                      value={newAuthName}
                      onChange={(e) => setNewAuthName(e.target.value)}
                      placeholder="e.g. My API Key"
                    />
                  </div>

                  <div className="space-y-1">
                    <Label htmlFor="newAuthType">Auth Type</Label>
                    <Select
                      value={newAuthType}
                      onValueChange={(v) => setNewAuthType(v as AuthType)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="api_key">API Key</SelectItem>
                        <SelectItem value="bearer">Bearer Token</SelectItem>
                        <SelectItem value="oauth2">OAuth2</SelectItem>
                      </SelectContent>
                    </Select>
                    <input type="hidden" name="newAuthType" value={newAuthType} />
                  </div>

                  {newAuthType === "api_key" && (
                    <>
                      <div className="space-y-1">
                        <Label htmlFor="headerName">Header Name</Label>
                        <Input id="headerName" name="headerName" defaultValue="Authorization" placeholder="Authorization" />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="headerValue">Header Value</Label>
                        <Input id="headerValue" name="headerValue" type="password" placeholder="Your API key" />
                      </div>
                    </>
                  )}

                  {newAuthType === "bearer" && (
                    <div className="space-y-1">
                      <Label htmlFor="bearerToken">Bearer Token</Label>
                      <Input id="bearerToken" name="bearerToken" type="password" placeholder="Your bearer token" />
                    </div>
                  )}

                  {newAuthType === "oauth2" && (
                    <>
                      <div className="space-y-1">
                        <Label htmlFor="clientId">Client ID</Label>
                        <Input id="clientId" name="clientId" placeholder="OAuth2 client ID" />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="clientSecret">Client Secret</Label>
                        <Input id="clientSecret" name="clientSecret" type="password" placeholder="OAuth2 client secret" />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="tokenUrl">Token URL</Label>
                        <Input id="tokenUrl" name="tokenUrl" placeholder="https://provider.com/oauth/token" />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="authorizeUrl">Authorize URL (optional)</Label>
                        <Input id="authorizeUrl" name="authorizeUrl" placeholder="https://provider.com/oauth/authorize" />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="scopes">Scopes (optional)</Label>
                        <Input id="scopes" name="scopes" placeholder="read write" />
                      </div>
                    </>
                  )}

                  <div className="flex gap-2 pt-1">
                    <Button
                      type="button"
                      size="sm"
                      disabled={newAuthSaving || !newAuthName}
                      onClick={(e) => {
                        const form = (e.target as HTMLElement).closest(".rounded-md.border") as HTMLElement;
                        if (form) {
                          const tempForm = document.createElement("form");
                          form.querySelectorAll("input, select").forEach((el) => {
                            const clone = el.cloneNode(true) as HTMLInputElement;
                            tempForm.appendChild(clone);
                          });
                          handleCreateAuthConfig(tempForm);
                        }
                      }}
                    >
                      {newAuthSaving ? "Saving..." : "Save Auth Config"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setShowNewAuthForm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              <p className="text-sm text-muted-foreground">
                Select an existing auth configuration or create a new one.
              </p>
            </div>
          </>
        )}
        </>
        )}

        {/* Common Fields - Tags */}
        <div className="space-y-2">
          <Label htmlFor="tags">Tags (comma separated)</Label>
          <Input
            id="tags"
            {...register("tags")}
            placeholder="e.g. files, database, web"
          />
        </div>

        {/* Common Fields - Public Switch */}
        <Controller
          control={control}
          name="isPublic"
          render={({ field }) => (
            <div className="flex items-center justify-between pt-4">
              <div className="space-y-0.5">
                <Label htmlFor="public-switch" className="cursor-pointer">
                  Public Server
                </Label>
                <p className="text-sm text-muted-foreground">
                  Make this MCP server available to other users
                </p>
              </div>
              <Switch
                id="public-switch"
                checked={field.value}
                onCheckedChange={field.onChange}
                aria-invalid={!!combinedErrors.isPublic}
              />
              <input
                type="hidden"
                {...register("isPublic")}
                value={field.value.toString()}
              />
            </div>
          )}
        />
        {combinedErrors.isPublic && (
          <p className="form-error">
            {getErrorMessage(combinedErrors.isPublic)}
          </p>
        )}

        {/* Display success/failure message */}
        {state.message && !state.errors && (
          <p className="text-green-600">{state.message}</p>
        )}
        {state.message && state.errors && (
          <p className="text-sm text-destructive">{state.message}</p>
        )}
      </div>
    </form>
  );
}
