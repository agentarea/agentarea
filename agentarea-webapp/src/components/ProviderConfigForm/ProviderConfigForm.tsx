"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, Bot, Server } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import type {
  ProviderConfigCreate,
  ProviderConfigUpdate,
  ProviderSpecWithModelsResponse,
} from "@/api/client/types.gen";
import {
  zProviderConfigCreate,
  zProviderConfigUpdate,
} from "@/api/client/zod.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  bulkCreateModelInstancesAction as bulkCreateModelInstances,
  createProviderConfigAction as createProviderConfig,
  deleteModelInstanceAction as deleteModelInstance,
  listProviderSpecsAction as listProviderSpecs,
  listProviderSpecsWithModelsAction as listProviderSpecsWithModels,
  updateProviderConfigAction as updateProviderConfig,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import {
  ModelSpec,
  ProviderConfigFormProps,
  ProviderSpec,
  SelectedModel,
} from "@/types/provider";
import BaseInfo from "./components/BaseInfo";
import ModelInstances from "./components/ModelInstances";

const providerConfigCreateFormSchema = zProviderConfigCreate.superRefine(
  (data, ctx) => {
    if (!data.endpoint_url?.trim() && !data.api_key?.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["api_key"],
        message:
          "API key is required (or set a custom endpoint URL for keyless proxies)",
      });
    }
  }
);

type ProviderConfigFormData = z.input<typeof zProviderConfigCreate>;

export default function ProviderConfigForm({
  initialData,
  className,
  isEdit = false,
  preselectedProviderId,
  isClear = false,
  onAfterSubmit,
  onCancel,
  submitButtonText,
  cancelButtonText,
  showModelSelection = true,
  autoRedirect = true,
  existingModelInstances = [],
}: ProviderConfigFormProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const t = useTranslations("ProviderConfigForm");
  const tCommon = useTranslations("Common");
  const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);
  const [providerSpecs, setProviderSpecs] = useState<ProviderSpec[]>([]);
  const [modelSpecs, setModelSpecs] = useState<ModelSpec[]>([]);

  // Load provider specs and model specs.
  // Pass { silent: true } to refresh without unmounting the form (used after
  // Discover Models so the child component keeps its local UI state).
  const loadData = useCallback(async (opts?: { silent?: boolean }) => {
    try {
      if (!opts?.silent) setIsLoading(true);
      const [providerSpecsResponse, providerSpecsWithModelsResponse] =
        await Promise.all([
          listProviderSpecs(),
          listProviderSpecsWithModels(),
        ]);

      if (
        providerSpecsResponse.error ||
        providerSpecsWithModelsResponse.error
      ) {
        throw new Error(
          providerSpecsResponse.error?.detail?.[0]?.msg ||
            providerSpecsWithModelsResponse.error?.detail?.[0]?.msg ||
            "Failed to load provider specifications"
        );
      }

      const specs = providerSpecsResponse.data || [];
      const specsWithModels =
        (providerSpecsWithModelsResponse.data || []) as ProviderSpecWithModelsResponse[];

      // Extract and flatten model specs from the provider specs with models
      const models = specsWithModels.flatMap((spec) =>
          spec.models.map((model) => ({
            id: model.id,
            provider_spec_id: spec.id,
            model_name: model.model_name,
            display_name: model.display_name,
            description: model.description,
            context_window: model.context_window,
            max_output_tokens: model.max_output_tokens ?? null,
            input_cost_per_token: model.input_cost_per_token ?? null,
            output_cost_per_token: model.output_cost_per_token ?? null,
            supports_function_calling: model.supports_function_calling ?? false,
            supports_vision: model.supports_vision ?? false,
            supports_reasoning: model.supports_reasoning ?? false,
            is_active: model.is_active,
            created_at: model.created_at,
            updated_at: model.updated_at,
            default_context_strategy: (model as { default_context_strategy?: string | null }).default_context_strategy ?? null,
          }))
      );

      setProviderSpecs(specs);
      setModelSpecs(models);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : t("error.failedToLoadData");
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Initialize react-hook-form
  const {
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isValid },
    reset,
  } = useForm<ProviderConfigFormData>({
    resolver: zodResolver(
      isEdit ? zProviderConfigCreate : providerConfigCreateFormSchema
    ),
    defaultValues: {
      provider_spec_id:
        preselectedProviderId || initialData?.provider_spec_id || "",
      name: initialData?.name || "",
      api_key: "", // API key is not returned in responses for security
      endpoint_url: initialData?.endpoint_url || "",
      is_public: initialData?.is_public || false,
    },
    mode: "onChange",
  });

  const watchedProviderId = watch("provider_spec_id");
  const watchedName = watch("name");
  const watchedApiKey = watch("api_key");
  const watchedEndpointUrl = watch("endpoint_url");

  const selectedProvider = providerSpecs?.find?.(
    (spec) => spec.id === watchedProviderId
  );

  // Memoize availableModels to prevent infinite re-renders
  const availableModels = useMemo(() => {
    return (
      modelSpecs?.filter?.(
        (model) =>
          selectedProvider && model.provider_spec_id === selectedProvider.id
      ) || []
    );
  }, [modelSpecs, selectedProvider]);

  // Auto-selection of models lives in <ModelInstances> and only fires after
  // the user runs Discover, so the form no longer pre-fills selectedModels
  // from the registry on provider change.

  // Generate name for preselected provider
  useEffect(() => {
    if (
      preselectedProviderId &&
      selectedProvider &&
      !isEdit &&
      !initialData &&
      !watchedName
    ) {
      const providerName = selectedProvider.name || "";
      const randomNumber = Math.floor(100000 + Math.random() * 900000); // 6-digit random number
      setValue("name", `${providerName} Config - ${randomNumber}`);
    }
  }, [
    preselectedProviderId,
    selectedProvider,
    isEdit,
    initialData,
    watchedName,
    setValue,
  ]);

  // Set initial values when initialData is loaded
  useEffect(() => {
    if (initialData && isEdit) {
      setValue("provider_spec_id", initialData.provider_spec_id);
      setValue("name", initialData.name);
      setValue("endpoint_url", initialData.endpoint_url || "");
    }
  }, [initialData, isEdit, setValue]);

  // Initialize selected models from existing model instances when in edit mode
  useEffect(() => {
    if (isEdit && existingModelInstances.length > 0 && modelSpecs.length > 0) {
      const existingModels = existingModelInstances.map((instance) => {
        return {
          modelSpecId: instance.model_spec_id,
          instanceName: instance.name,
          description: instance.description || "",
          isPublic: instance.is_public,
        };
      });

      setSelectedModels(existingModels);
    }
  }, [isEdit, existingModelInstances, modelSpecs]);

  // Handle loading state
  if (isLoading) {
    return <LoadingSpinner />;
  }

  // Handle error state
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  const handleProviderChange = (providerId: string | number) => {
    const selectedProvider = providerSpecs.find(
      (spec) => spec.id === providerId
    );
    const providerName = selectedProvider?.name || "";
    const randomNumber = Math.floor(100000 + Math.random() * 900000); // 6-digit random number

    setValue("provider_spec_id", providerId.toString());
    setValue("name", `${providerName} Config - ${randomNumber}`);

    setSelectedModels([]); // Reset selected models when provider changes
  };

  const onSubmit = async (data: ProviderConfigFormData) => {
    setIsSubmitting(true);
    setError(null);

    try {
      // Step 1: Create or update the provider configuration
      let providerConfig;
      let providerError;

      if (isEdit && initialData) {
        const updateData: ProviderConfigUpdate = {
          name: data.name,
          endpoint_url: data.endpoint_url === "" ? null : data.endpoint_url,
          is_active: data.is_public, // Note: backend uses is_active, frontend uses is_public
        };

        // Only include api_key if it's provided (not empty)
        if (data.api_key && data.api_key.trim() !== "") {
          updateData.api_key = data.api_key;
        }
        const parsedUpdate = zProviderConfigUpdate.safeParse(updateData);
        if (!parsedUpdate.success) {
          throw new Error(parsedUpdate.error.issues[0]?.message || "Invalid provider configuration");
        }
        const result = await updateProviderConfig(initialData.id, parsedUpdate.data);
        providerConfig = result.data;
        providerError = result.error;
      } else {
        const createData: ProviderConfigCreate = {
          provider_spec_id: data.provider_spec_id,
          name: data.name,
          api_key: data.api_key || "", // API key is required for creation, so this should never be undefined
          endpoint_url: data.endpoint_url === "" ? null : data.endpoint_url,
          is_public: data.is_public,
        };
        const parsedCreate = zProviderConfigCreate.safeParse(createData);
        if (!parsedCreate.success) {
          throw new Error(parsedCreate.error.issues[0]?.message || "Invalid provider configuration");
        }
        const result = await createProviderConfig(parsedCreate.data);
        providerConfig = result.data;
        providerError = result.error;
      }

      if (providerError || !providerConfig) {
        const errorMessage =
          (providerError as { detail?: { msg?: string }[]; message?: string })
            ?.detail?.[0]?.msg ||
          (providerError as { message?: string })?.message ||
          t("error.unknownError");
        throw new Error(
          `${t("error.failedTo")} ${
            isEdit ? tCommon("update") : tCommon("create")
          } ${t("providerConfiguration")}: ${errorMessage}`
        );
      }

      // Step 2: Create model instances via the bulk endpoint to avoid N
      // round-trips when the user selects hundreds of models from a discovered
      // catalog. Deletes stay as individual calls (rare, small N).
      const bulkCreate = async (
        rows: { modelSpecId: string; instanceName: string; description: string; isPublic: boolean }[]
      ) => {
        if (rows.length === 0) return { created: 0 };
        const { data, error } = await bulkCreateModelInstances({
          items: rows.map((m) => ({
            provider_config_id: providerConfig.id,
            model_spec_id: m.modelSpecId,
            name: m.instanceName,
            description: m.description,
            is_public: m.isPublic,
          })),
        });
        if (error || !data) {
          const detail =
            (error as { detail?: { msg?: string }[]; message?: string })?.detail?.[0]?.msg ||
            (error as { message?: string })?.message ||
            "Unknown error";
          throw new Error(`Failed to create model instances: ${detail}`);
        }
        const result = data as {
          succeeded_count: number;
          failed_count: number;
          failed: { index: number; model_spec_id: string; error: string }[];
        };
        if (result.failed_count > 0) {
          const sample = result.failed.slice(0, 3).map((f) => f.error).join("; ");
          toast.error(
            `Failed to create ${result.failed_count} of ${rows.length} model instances. ${sample}`
          );
        }
        return { created: result.succeeded_count };
      };

      if (!isEdit && selectedModels.length > 0 && showModelSelection) {
        const { created } = await bulkCreate(selectedModels);
        toast.success(
          t(
            isEdit
              ? "toast.configurationUpdated"
              : "toast.configurationCreated",
            { modelCount: created }
          )
        );
      } else if (isEdit && showModelSelection) {
        // Handle model instances for edit mode
        const existingModelSpecIds = existingModelInstances.map(
          (instance) => instance.model_spec_id
        );
        const selectedModelSpecIds = selectedModels.map(
          (model) => model.modelSpecId
        );

        // Find models to create (new selections)
        const modelsToCreate = selectedModels.filter(
          (model) => !existingModelSpecIds.includes(model.modelSpecId)
        );

        // Find models to delete (removed selections)
        const modelsToDelete = existingModelInstances.filter(
          (instance) => !selectedModelSpecIds.includes(instance.model_spec_id)
        );

        // Create new model instances in one bulk request
        if (modelsToCreate.length > 0) {
          await bulkCreate(modelsToCreate);
        }

        // Delete removed model instances
        if (modelsToDelete.length > 0) {
          const deletePromises = modelsToDelete.map(async (instance) => {
            const { error } = await deleteModelInstance(instance.id);

            if (error) {
              throw new Error(
                `Failed to delete model instance "${instance.name}": ${
                  (error as { message?: string })?.message || "Unknown error"
                }`
              );
            }
          });

          await Promise.all(deletePromises);
        }

        const changes = [];
        if (modelsToCreate.length > 0)
          changes.push(`+${modelsToCreate.length} ${t("toast.added")}`);
        if (modelsToDelete.length > 0)
          changes.push(`-${modelsToDelete.length} ${t("toast.removed")}`);

        if (changes.length > 0) {
          toast.success(
            t("toast.modelInstancesUpdated") + `: ${changes.join(", ")}`
          );
        } else {
          toast.success(t("toast.configurationUpdatedSuccessfully"));
        }
      } else {
        // These messages are ICU plurals on {modelCount}; passing the arg avoids
        // next-intl returning the raw key (e.g. "ProviderConfigForm.toast.…").
        toast.success(
          isEdit
            ? t("toast.configurationUpdated", { modelCount: 0 })
            : t("toast.configurationCreated", { modelCount: 0 })
        );
      }

      // Call custom after submit handler if provided
      if (onAfterSubmit) {
        await onAfterSubmit(providerConfig);
      }

      // Redirect if autoRedirect is enabled and no custom handler
      if (autoRedirect && !onAfterSubmit) {
        router.push("/admin/provider-configs");
        return;
      }

      // Reset form only if creating and staying on the current page.
      if (!isEdit && !onAfterSubmit) {
        reset({
          provider_spec_id: "",
          name: "",
          api_key: "",
          endpoint_url: "",
          is_public: false,
        });
        setSelectedModels([]);
      }
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : t("error.unexpectedError");
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => {
    if (onCancel) {
      onCancel();
    } else if (autoRedirect) {
      router.push("/admin/provider-configs");
    }
  };

  return (
    <form
      id="provider-config-form"
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        handleSubmit(onSubmit)(e);
      }}
      className={cn("form-content", className)}
    >
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className={cn("mx-auto", "max-w-4xl")}>
        <div
          className={cn(
            "grid grid-cols-1 form-content",
            isClear ? "p-0" : "card card-shadow"
          )}
        >
          <div className="space-y-2">
            <FormLabel htmlFor="provider" icon={Server}>
              {t("provider")}
            </FormLabel>
            <Controller
              name="provider_spec_id"
              control={control}
              render={({ field }) => (
                <SearchableSelect
                  options={providerSpecs.map((spec) => ({
                    id: spec.id,
                    label: spec.name,
                    icon: spec.icon_url ?? undefined,
                  }))}
                  value={field.value}
                  onValueChange={handleProviderChange}
                  placeholder={t("selectProvider")}
                  disabled={isEdit || (!!preselectedProviderId && !initialData)}
                  emptyMessage={
                    <div className="flex h-full flex-col items-center justify-center gap-1">
                      <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/20 dark:bg-primary-foreground/20">
                        <Bot className="h-5 w-5 text-primary dark:text-primary-foreground" />
                      </div>
                      <span className="text-muted-foreground">
                        {t("noProvidersFound")}
                      </span>
                    </div>
                  }
                />
              )}
            />
            {errors.provider_spec_id && (
              <p className="form-error">{errors.provider_spec_id.message}</p>
            )}
            {preselectedProviderId && !isEdit && !initialData && (
              <p className="note">{t("providerIsPreSelected")}</p>
            )}
          </div>

          <BaseInfo
            control={control}
            errors={errors}
            providerSpecId={watchedProviderId}
            isEdit={isEdit}
          />

          {selectedProvider && showModelSelection && (
            <ModelInstances
              selectedProvider={selectedProvider}
              availableModels={availableModels}
              selectedModels={selectedModels}
              setSelectedModels={setSelectedModels}
              isEdit={isEdit}
              providerConfigId={isEdit && initialData ? initialData.id : undefined}
              apiKey={watchedApiKey ?? undefined}
              endpointUrl={watchedEndpointUrl ?? undefined}
              onModelsDiscovered={() => loadData({ silent: true })}
            />
          )}
        </div>
      </div>

      {/* Submit Button - only show in sheet (when onCancel is provided) */}
      {onCancel && (
        <div className="flex justify-end space-x-4">
          <Button
            type="button"
            variant="outline"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleCancel();
            }}
          >
            {cancelButtonText || tCommon("cancel")}
          </Button>
          <Button
            type="submit"
            disabled={isSubmitting || !isValid}
            onClick={(e) => {
              e.stopPropagation();
            }}
          >
            {isSubmitting
              ? isEdit
                ? t("loading.updating")
                : t("loading.creating")
              : submitButtonText ||
                (isEdit
                  ? t("updateConfiguration")
                  : t("createConfigurationWithModels", {
                      modelCount: selectedModels.length,
                    }))}
          </Button>
        </div>
      )}
    </form>
  );
}
