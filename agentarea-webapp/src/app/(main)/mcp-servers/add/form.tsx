"use client";

import { useActionState, useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, X } from "lucide-react";
import { useFormStatus } from "react-dom";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
  type: z.enum(["docker", "external"], {
    required_error: "Server type is required",
  }),
  name: z.string().min(1, "Server name is required"),
  description: z.string().min(1, "Description is required"),
  dockerImageUrl: z.string().optional(),
  version: z.string().optional(),
  endpointUrl: z.string().optional(),
  headers: z.array(HeaderSchema),
  tags: z.string().optional(),
  isPublic: z.boolean(),
});

const MCPServerSchema = BaseMCPServerSchema.refine(
  (data) => {
    if (data.type === "docker") {
      return data.dockerImageUrl && data.dockerImageUrl.trim() !== "";
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
    endpointUrl: "",
    headers: [],
    tags: [],
    isPublic: true,
  },
};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" className="w-full" disabled={pending}>
      {pending ? "Adding..." : "Add Server"}
    </Button>
  );
}

export function AddMCPServerForm() {
  const [state, formAction] = useActionState(addMCPServer, initialState);
  const [serverType, setServerType] = useState<"docker" | "external">("docker");

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
    <form action={formAction}>
      <CardContent className="form-content">
        {/* Display general form errors */}
        {state.errors?._form && (
          <div className="form-error">
            {state.errors._form.join(", ")}
          </div>
        )}

        {/* Server Type Selector */}
        <div className="space-y-2">
          <Label htmlFor="type">Server Type</Label>
          <Controller
            control={control}
            name="type"
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={(value) => {
                  field.onChange(value);
                  setServerType(value as "docker" | "external");
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select server type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="docker">Docker-based Server</SelectItem>
                  <SelectItem value="external">External Server</SelectItem>
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

        {/* Common Fields */}
        <div className="space-y-2">
          <Label htmlFor="name">Server Name</Label>
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
          <Label htmlFor="description">Description</Label>
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
              <Label htmlFor="dockerImageUrl">Docker Image URL</Label>
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
              <Label htmlFor="version">Version</Label>
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

        {/* External-specific Fields */}
        {serverType === "external" && (
          <>
            <div className="space-y-2">
              <Label htmlFor="endpointUrl">Endpoint URL</Label>
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
          <p className="text-red-600">{state.message}</p>
        )}
      </CardContent>
      <CardFooter>
        <SubmitButton />
      </CardFooter>
    </form>
  );
}
