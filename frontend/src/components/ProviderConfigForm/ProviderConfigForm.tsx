"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { motion, AnimatePresence } from "framer-motion";
import {
  createProviderConfig,
  createModelInstance,
  updateProviderConfig,
  listProviderSpecs,
  listProviderSpecsWithModels,
  deleteModelInstance,
} from "@/lib/browser-api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { AlertCircle, Bot, Server } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import BaseInfo from "./components/BaseInfo";
import ModelInstances from "./components/ModelInstances";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import {
  ProviderSpec,
  ModelSpec,
  SelectedModel,
  ProviderConfigFormProps,
} from "@/types/provider";

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

  // Load provider specs and model specs on component mount
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

        const specs = providerSpecsResponse.data || [];
        const specsWithModels = providerSpecsWithModelsResponse.data || [];

        // Extract and flatten model specs from the provider specs with models
        const models = specsWithModels.flatMap((spec) =>
          spec.models.map((model) => ({
            id: model.id,
            provider_spec_id: spec.id,
            model_name: model.model_name,
            display_name: model.display_name,
            description: model.description,
            context_window: model.context_window,
            is_active: model.is_active,
            created_at: model.created_at,
            updated_at: model.updated_at,
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
    };

    loadData();
  }, []);

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
      api_key: "", // API key is not returned in responses for security
      endpoint_url: initialData?.endpoint_url || "",
      is_public: initialData?.is_public || false,
    },
    mode: "onChange",
  });

  const watchedProviderId = watch("provider_spec_id");
  const watchedName = watch("name");

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

  // Auto-select all models when provider changes
  useEffect(() => {
    if (
      selectedProvider &&
      availableModels.length > 0 &&
      !isEdit &&
      showModelSelection
    ) {
      const allModels = availableModels.map((model) => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider.name} ${model.display_name}`,
        description: model.description || "",
        isPublic: false,
      }));
      setSelectedModels(allModels);
    }
  }, [selectedProvider, availableModels, isEdit, showModelSelection]);

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
        // Find the corresponding model spec
        const modelSpec = modelSpecs.find(
          (spec) => spec.id === instance.model_spec_id
        );

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
          is_active: data.is_public, // Note: backend uses is_active, frontend uses is_public
        };

        // Only include api_key if it's provided (not empty)
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
          api_key: data.api_key || "", // API key is required for creation, so this should never be undefined
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

      // Set the created provider config ID for testing
      if (!isEdit) {
        setCreatedProviderConfigId(providerConfig.id);
      }

      // Step 2: Create model instances if any are selected (only for create mode and if model selection is enabled)
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

        // Create new model instances
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
        toast.success(
          isEdit
            ? t("toast.configurationUpdated")
            : t("toast.configurationCreated")
        );
      }

      // Call custom after submit handler if provided
      if (onAfterSubmit) {
        await onAfterSubmit(providerConfig);
      }

      // Reset form only if creating and no custom handler
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

      // Redirect if autoRedirect is enabled and no custom handler
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
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        handleSubmit(onSubmit)(e);
      }}
      className={cn("space-y-6", className)}
    >
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0, scale: 0.95 }}
            animate={{ opacity: 1, height: "auto", scale: 1 }}
            exit={{ opacity: 0, height: 0, scale: 0.95 }}
            transition={{ duration: 0.3 }}
          >
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="mx-auto max-w-4xl">
        <div
          className={cn(
            "grid grid-cols-1 gap-6",
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
                  disabled={!!preselectedProviderId && !isEdit && !initialData}
                  emptyMessage={
                    <div className="flex flex-col items-center justify-center h-full gap-1">
                      <div className="flex items-center justify-center w-7 h-7 bg-primary/20 rounded-md dark:bg-primary-foreground/20">
                        <Bot className="w-5 h-5 text-primary dark:text-primary-foreground" />
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
              <p className="text-sm text-red-600">
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
          />

          {selectedProvider && showModelSelection && (
            <AnimatePresence>
              <motion.div
                key="model-instances"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{
                  height: { duration: 0.3, ease: "easeOut" },
                  opacity: { duration: 0.2, ease: "easeOut" },
                }}
                style={{ overflow: "hidden" }}
              >
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
              </motion.div>
            </AnimatePresence>
          )}
        </div>
      </div>

      {/* Submit Button */}
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
    </form>
  );
}
