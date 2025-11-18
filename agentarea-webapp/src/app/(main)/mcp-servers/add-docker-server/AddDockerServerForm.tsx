"use client";

import { useRef } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Server, Package, Tag } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { useTranslations } from "next-intl";
import { createMCPServer } from "@/lib/browser-api";

type FormData = {
  name: string;
  dockerImageUrl: string;
  version: string;
};

export default function AddDockerServerForm() {
  const t = useTranslations("MCPServersPage.newServer.docker");
  const router = useRouter();
  
  const formRef = useRef<HTMLFormElement>(null);
  const { 
    register, 
    handleSubmit, 
    formState: { errors } 
  } = useForm<FormData>({
    defaultValues: {
      name: "",
      dockerImageUrl: "",
      version: "1.0.0",
    },
  });

  const handleFormSubmit = async (data: FormData) => {
    const form = formRef.current;
    if (!form) return;

    // Set form submitting state
    form.setAttribute("data-submitting", "true");
    form.dispatchEvent(
      new CustomEvent("form-submitting", { detail: { isSubmitting: true } })
    );

    try {
      const response = await createMCPServer({
        name: data.name,
        description: "", // Description is required by API but not in form
        docker_image_url: data.dockerImageUrl,
        version: data.version,
        tags: [],
        is_public: false,
        env_schema: [],
      });

      if (response.error) {
        const errorDetail = response.error.detail;
        const errorMessage =
          typeof errorDetail === "string"
            ? errorDetail
            : Array.isArray(errorDetail) && errorDetail[0]?.msg
              ? errorDetail[0].msg
              : "Failed to create MCP server";
        throw new Error(errorMessage);
      }

      toast.success("MCP server created successfully", {
        description: `Server "${data.name}" has been created.`,
      });

      // On success, redirect to MCP servers page
      router.push("/mcp-servers");
      router.refresh();
    } catch (error) {
      console.error("Error submitting form:", error);
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Failed to create MCP server";
      toast.error("Failed to create MCP server", {
        description: errorMessage,
      });

      // Reset submitting state on error
      if (formRef.current) {
        formRef.current.removeAttribute("data-submitting");
        formRef.current.dispatchEvent(
          new CustomEvent("form-submitting", {
            detail: { isSubmitting: false },
          })
        );
      }
    }
  };

  return (
    <form
      ref={formRef}
      id="mcp-server-form"
      onSubmit={handleSubmit(handleFormSubmit)}
      className="overflow-auto h-full"
    >
      <div className="form-content lg:max-w-xl lg:mx-auto">
        <div className="space-y-2">
          <FormLabel htmlFor="name" icon={Server} required>
            {t("serverName")}
          </FormLabel>
          <Input
            id="name"
            {...register("name", { 
              required: t("serverNameRequired") || "Server name is required" 
            })}
            placeholder={t("serverNamePlaceholder")}
            aria-invalid={!!errors.name}
          />
          {errors.name && (
            <p className="form-error text-sm text-destructive">
              {errors.name.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <FormLabel htmlFor="dockerImageUrl" icon={Package} required>
            {t("dockerImageUrl")}
          </FormLabel>
          <Input
            id="dockerImageUrl"
            {...register("dockerImageUrl", { 
              required: t("dockerImageUrlRequired") || "Docker image URL is required" 
            })}
            placeholder={t("dockerImageUrlPlaceholder")}
            aria-invalid={!!errors.dockerImageUrl}
          />
          {errors.dockerImageUrl && (
            <p className="form-error text-sm text-destructive">
              {errors.dockerImageUrl.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <FormLabel htmlFor="version" icon={Tag} required>
            {t("version")}
          </FormLabel>
          <Input
            id="version"
            {...register("version", { 
              required: t("versionRequired") || "Version is required" 
            })}
            placeholder={t("versionPlaceholder")}
            aria-invalid={!!errors.version}
          />
          {errors.version && (
            <p className="form-error text-sm text-destructive">
              {errors.version.message}
            </p>
          )}
        </div>
      </div>
    </form>
  );
}