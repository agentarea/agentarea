"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, Bot, Server } from "lucide-react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import FormLabel from "@/components/FormLabel/FormLabel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  createModelInstanceAction as createModelInstance,
  createProviderConfigAction as createProviderConfig,
  deleteModelInstanceAction as deleteModelInstance,
  discoverModelsPreviewAction as discoverModelsPreview,
  listProviderSpecsAction as listProviderSpecs,
  listProviderSpecsWithModelsAction as listProviderSpecsWithModels,
  updateProviderConfigAction as updateProviderConfig,
} from "@/lib/server-actions";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { cn } from "@/lib/utils";
import {
  ModelSpec,
  ProviderConfigFormProps,
  ProviderSpec,
  SelectedModel,
} from "@/types/provider";
import BaseInfo from "./components/BaseInfo";
import ModelInstances from "./components/ModelInstances";

// Form validation schema
const providerConfigSchema = z.object({
  provider_spec_id: z.string().min(1, "Provider is required"),
  name: z
    .string()
    .min(1, "Name is required")
    .max(255, "Name must be less than 255 characters"),
  api_key: z.string().optional(),
  endpoint_url: z.string().optional(),
  is_public: z.boolean(),
});

type ProviderConfigFormData = z.infer<typeof providerConfigSchema>;

function generateConfigName(providerName: string): string {
  const randomNumber = Math.floor(100000 + Math.random() * 900000);
  return `${providerName} Config - ${randomNumber}`;
}

function modelsToSelection(
  models: ModelSpec[],
  providerName: string
): SelectedModel[] {
  return models.map((model) => ({
    modelSpecId: model.id,
    instanceName: `${providerName} ${model.display_name}`,
    description: model.description || "",
    isPublic: false,
  }));
}

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
  const [createdProviderConfigId, setCreatedProviderConfigId] = useState<
    string | null
  >(null);

  // Discovery state
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoverySuccess, setDiscoverySuccess] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);

  // Initialize react-hook-form (must be before any effects that use setValue)
  const {
    control,
    handleSubmit,
    setValue,
    formState: { errors, isValid },
    reset,
  } = useForm<ProviderConfigFormData>({
    resolver: zodResolver(
      isEdit
        ? providerConfigSchema
        : providerConfigSchema.extend({
            api_key: z.string().min(1, "API key is required"),
          })
    ),
    defaultValues: {
      provider_spec_id:
        preselectedProviderId || initialData?.provider_spec_id || "",
      name: initialData?.name || "",
      api_key: "",
      endpoint_url: initialData?.endpoint_url || "",
      is_public: initialData?.is_public || false,
    },
    mode: "onChange",
  });

  // useWatch instead of watch() — subscribes once, no re-render cascade
  const watchedProviderId = useWatch({ control, name: "provider_spec_id" });
  const apiKeyValue = useWatch({ control, name: "api_key" });
  const endpointUrlValue = useWatch({ control, name: "endpoint_url" });

  const selectedProvider = useMemo(
    () => providerSpecs?.find?.((spec) => spec.id === watchedProviderId),
    [providerSpecs, watchedProviderId]
  );

  const availableModels = useMemo(
    () =>
      modelSpecs?.filter?.(
        (model) =>
          selectedProvider && model.provider_spec_id === selectedProvider.id
      ) || [],
    [modelSpecs, selectedProvider]
  );

  // === SINGLE data-loading effect — handles ALL initialization ===
  useEffect(() => {
    const loadData = async () => {
      try {
        setIsLoading(true);
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

        const specs = (providerSpecsResponse.data || []) as ProviderSpec[];
        const specsWithModels =
          providerSpecsWithModelsResponse.data || [];

        // Spread all fields from API (includes enriched cost/capability data)
        const models: ModelSpec[] = specsWithModels.flatMap((spec: any) =>
          spec.models.map((model: any) => ({
            ...model,
            provider_spec_id: spec.id,
          }))
        );

        setProviderSpecs(specs);
        setModelSpecs(models);

        // --- All initialization that previously lived in separate effects ---

        const targetProviderId =
          preselectedProviderId || initialData?.provider_spec_id;

        if (isEdit && existingModelInstances.length > 0) {
          // Edit mode: init selected models from existing instances
          setSelectedModels(
            existingModelInstances.map((instance) => ({
              modelSpecId: instance.model_spec_id,
              instanceName: instance.name,
              description: instance.description || "",
              isPublic: instance.is_public,
            }))
          );
        } else if (
          !isEdit &&
          showModelSelection &&
          targetProviderId
        ) {
          // Create mode with preselected provider: auto-select all models
          const provider = specs.find(
            (s: ProviderSpec) => s.id === targetProviderId
          );
          const available = models.filter(
            (m) => m.provider_spec_id === targetProviderId
          );
          if (provider && available.length > 0) {
            setSelectedModels(modelsToSelection(available, provider.name));
          }
        }

        // Generate name for preselected provider in create mode
        if (targetProviderId && !isEdit && !initialData) {
          const provider = specs.find(
            (s: ProviderSpec) => s.id === targetProviderId
          );
          if (provider) {
            setValue("name", generateConfigName(provider.name));
          }
        }

        // Set initial values for edit mode
        if (initialData && isEdit) {
          setValue("provider_spec_id", initialData.provider_spec_id);
          setValue("name", initialData.name);
          setValue("endpoint_url", initialData.endpoint_url || "");
        }
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : t("error.failedToLoadData");
        setError(errorMessage);
        toast.error(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Discovery handler (useCallback so BaseInfo gets a stable reference)
  const handleDiscoverModels = useCallback(
    async (apiKey: string, endpointUrl?: string) => {
      if (!selectedProvider) return;
      setIsDiscovering(true);
      setDiscoveryError(null);
      setDiscoverySuccess(false);
      try {
        const { data, error } = await discoverModelsPreview({
          provider_key: (selectedProvider as any).provider_key,
          api_key: apiKey,
          endpoint_url: endpointUrl,
        });
        if (error) {
          setDiscoveryError(
            (error as any)?.detail || "Discovery failed"
          );
          return;
        }
        const result = data as any;
        if (result?.models) {
          const newModels: ModelSpec[] = result.models.map((m: any) => ({
            ...m,
            provider_spec_id: selectedProvider.id,
          }));
          // Merge: replace models for this provider, keep others
          setModelSpecs((prev) => {
            const others = prev.filter(
              (m) => m.provider_spec_id !== selectedProvider.id
            );
            return [...others, ...newModels];
          });
          setDiscoverySuccess(true);
          toast.success(`Discovered ${result.models.length} models`);
        }
      } catch {
        setDiscoveryError("Discovery failed");
      } finally {
        setIsDiscovering(false);
      }
    },
    [selectedProvider]
  );

  // --- All hooks are above. Early returns below. ---

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (error && !providerSpecs.length) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  // Event handler — no effect needed
  const handleProviderChange = (providerId: string | number) => {
    const provider = providerSpecs.find((spec) => spec.id === providerId);
    const providerName = provider?.name || "";

    setValue("provider_spec_id", providerId.toString());
    setValue("name", generateConfigName(providerName));

    // Auto-select all models for this provider (replaces useEffect)
    if (showModelSelection) {
      const available = modelSpecs.filter(
        (m) => m.provider_spec_id === providerId
      );
      setSelectedModels(modelsToSelection(available, providerName));
    } else {
      setSelectedModels([]);
    }

    // Reset discovery state on provider switch
    setDiscoverySuccess(false);
    setDiscoveryError(null);
  };

  const updateSelectedModel = (
    modelSpecId: string,
    updates: Partial<SelectedModel>
  ) => {
    setSelectedModels((prev) =>
      prev.map((model) =>
        model.modelSpecId === modelSpecId ? { ...model, ...updates } : model
      )
    );
  };

  const onSubmit = async (data: ProviderConfigFormData) => {
    console.log("onSubmit", data);
    console.log("endpoint_url value:", data.endpoint_url);
    console.log("endpoint_url type:", typeof data.endpoint_url);
    setIsSubmitting(true);
    setError(null);

    try {
      // Step 1: Create or update the provider configuration
      let providerConfig;
      let providerError;

      if (isEdit && initialData) {
        const updateData: any = {
          name: data.name,
          endpoint_url: data.endpoint_url === "" ? null : data.endpoint_url,
          is_active: data.is_public,
        };

        if (data.api_key && data.api_key.trim() !== "") {
          updateData.api_key = data.api_key;
        }
        console.log("Update data:", updateData);
        const result = await updateProviderConfig(initialData.id, updateData);
        providerConfig = result.data;
        providerError = result.error;
      } else {
        const result = await createProviderConfig({
          provider_spec_id: data.provider_spec_id,
          name: data.name,
          api_key: data.api_key || "",
          endpoint_url: data.endpoint_url === "" ? null : data.endpoint_url,
          is_public: data.is_public,
        });
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

      if (!isEdit) {
        setCreatedProviderConfigId(providerConfig.id);
      }

      // Step 2: Create model instances if any are selected
      if (!isEdit && selectedModels.length > 0 && showModelSelection) {
        const modelCreationPromises = selectedModels.map(async (model) => {
          const { data, error } = await createModelInstance({
            provider_config_id: providerConfig.id,
            model_spec_id: model.modelSpecId,
            name: model.instanceName,
            description: model.description,
            is_public: model.isPublic,
          });

          if (error || !data) {
            throw new Error(
              `Failed to create model instance "${model.instanceName}": ${
                (error as { message?: string })?.message || "Unknown error"
              }`
            );
          }

          return data;
        });

        await Promise.all(modelCreationPromises);
        toast.success(
          t(
            isEdit
              ? "toast.configurationUpdated"
              : "toast.configurationCreated",
            {
              modelCount: selectedModels.length,
            }
          )
        );
      } else if (isEdit && showModelSelection) {
        const existingModelSpecIds = existingModelInstances.map(
          (instance) => instance.model_spec_id
        );
        const selectedModelSpecIds = selectedModels.map(
          (model) => model.modelSpecId
        );

        const modelsToCreate = selectedModels.filter(
          (model) => !existingModelSpecIds.includes(model.modelSpecId)
        );

        const modelsToDelete = existingModelInstances.filter(
          (instance) => !selectedModelSpecIds.includes(instance.model_spec_id)
        );

        if (modelsToCreate.length > 0) {
          const createPromises = modelsToCreate.map(async (model) => {
            const { data, error } = await createModelInstance({
              provider_config_id: providerConfig.id,
              model_spec_id: model.modelSpecId,
              name: model.instanceName,
              description: model.description,
              is_public: model.isPublic,
            });

            if (error || !data) {
              throw new Error(
                `Failed to create model instance "${model.instanceName}": ${
                  (error as { message?: string })?.message || "Unknown error"
                }`
              );
            }

            return data;
          });

          await Promise.all(createPromises);
        }

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
        toast.success(
          isEdit
            ? t("toast.configurationUpdated")
            : t("toast.configurationCreated")
        );
      }

      if (onAfterSubmit) {
        await onAfterSubmit(providerConfig);
      }

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

      if (autoRedirect && !onAfterSubmit) {
        router.push("/admin/provider-configs");
        router.refresh();
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
      <div className={cn("mx-auto", isClear ? "max-w-xl" : "max-w-4xl")}>
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
                    icon: spec.icon_url || getProviderIconUrl(spec.name),
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
              <p className="form-error">
                {errors.provider_spec_id.message}
              </p>
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
            onDiscoverModels={handleDiscoverModels}
            isDiscovering={isDiscovering}
            discoverySuccess={discoverySuccess}
            discoveryError={discoveryError}
            apiKeyValue={apiKeyValue}
            endpointUrlValue={endpointUrlValue}
          />

          {selectedProvider && showModelSelection && (
            <ModelInstances
              selectedProvider={selectedProvider}
              availableModels={availableModels}
              selectedModels={selectedModels}
              setSelectedModels={setSelectedModels}
              isEdit={isEdit}
              providerConfigId={
                createdProviderConfigId ||
                (isEdit && initialData ? initialData.id : undefined)
              }
              canTest={
                !!createdProviderConfigId || (isEdit && !!initialData)
              }
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
