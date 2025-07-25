'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { motion, AnimatePresence } from 'framer-motion';
import { createProviderConfig, createModelInstance, updateProviderConfig, listProviderSpecs, listProviderSpecsWithModels } from '@/lib/api';
import { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { AlertCircle, Bot, Server, Loader2 } from 'lucide-react';
import FormLabel from '@/components/FormLabel/FormLabel';
import BaseInfo from './components/BaseInfo';
import ModelInstances from './components/ModelInstances';
import { getProviderIconUrl } from '@/lib/provider-icons';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { ProviderSpec, ModelSpec, SelectedModel, ProviderConfigFormProps } from '@/types/provider';

// Form validation schema
const providerConfigSchema = z.object({
  provider_spec_id: z.string().min(1, 'Provider is required'),
  name: z.string().min(1, 'Name is required').max(255, 'Name must be less than 255 characters'),
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
}: ProviderConfigFormProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedModels, setExpandedModels] = useState<Set<string>>(new Set());
  const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);
  const [providerSpecs, setProviderSpecs] = useState<ProviderSpec[]>([]);
  const [modelSpecs, setModelSpecs] = useState<ModelSpec[]>([]);

  // Load provider specs and model specs on component mount
  useEffect(() => {
    const loadData = async () => {
      try {
        setIsLoading(true);
        const [providerSpecsResponse, providerSpecsWithModelsResponse] = await Promise.all([
          listProviderSpecs(),
          listProviderSpecsWithModels()
        ]);

        if (providerSpecsResponse.error || providerSpecsWithModelsResponse.error) {
          throw new Error(
            providerSpecsResponse.error?.detail?.[0]?.msg || 
            providerSpecsWithModelsResponse.error?.detail?.[0]?.msg ||
            'Failed to load provider specifications'
          );
        }

        const specs = providerSpecsResponse.data || [];
        const specsWithModels = providerSpecsWithModelsResponse.data || [];
        
        // Extract and flatten model specs from the provider specs with models
        const models = specsWithModels.flatMap(spec => 
          spec.models.map(model => ({
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
        const errorMessage = err instanceof Error ? err.message : 'Failed to load data';
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
    reset
  } = useForm<ProviderConfigFormData>({
    resolver: zodResolver(
      isEdit 
        ? providerConfigSchema 
        : providerConfigSchema.extend({
            api_key: z.string().min(1, 'API key is required')
          })
    ),
    defaultValues: {
      provider_spec_id: preselectedProviderId || initialData?.provider_spec_id || '',
      name: initialData?.name || '',
      api_key: '', // API key is not returned in responses for security
      endpoint_url: initialData?.endpoint_url || '',
      is_public: initialData?.is_public || false,
    },
    mode: 'onChange',
  });

  const watchedProviderId = watch('provider_spec_id');
  const watchedName = watch('name');

  const selectedProvider = providerSpecs?.find?.(spec => spec.id === watchedProviderId);
  
  // Memoize availableModels to prevent infinite re-renders
  const availableModels = useMemo(() => {
    return modelSpecs?.filter?.(model => 
      selectedProvider && model.provider_spec_id === selectedProvider.id
    ) || [];
  }, [modelSpecs, selectedProvider]);

  // Auto-select all models when provider changes
  useEffect(() => {
    if (selectedProvider && availableModels.length > 0 && !isEdit && showModelSelection) {
      const allModels = availableModels.map(model => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider.name} ${model.display_name}`,
        description: model.description || '',
        isPublic: false
      }));
      setSelectedModels(allModels);
    }
  }, [selectedProvider, availableModels, isEdit, showModelSelection]);

  // Generate name for preselected provider
  useEffect(() => {
    if (preselectedProviderId && selectedProvider && !isEdit && !initialData && !watchedName) {
      const providerName = selectedProvider.name || '';
      const randomNumber = Math.floor(100000 + Math.random() * 900000); // 6-digit random number
      setValue('name', `${providerName} Config - ${randomNumber}`);
    }
  }, [preselectedProviderId, selectedProvider, isEdit, initialData, watchedName, setValue]);

  // Set initial values when initialData is loaded
  useEffect(() => {
    if (initialData && isEdit) {
      setValue('provider_spec_id', initialData.provider_spec_id);
      setValue('name', initialData.name);
      setValue('endpoint_url', initialData.endpoint_url || '');
    }
  }, [initialData, isEdit, setValue]);

  // Handle loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <div className="flex items-center gap-2">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-muted-foreground">Loading provider specifications...</span>
        </div>
      </div>
    );
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
    const selectedProvider = providerSpecs.find(spec => spec.id === providerId);
    const providerName = selectedProvider?.name || '';
    const randomNumber = Math.floor(100000 + Math.random() * 900000); // 6-digit random number
    
    setValue('provider_spec_id', providerId.toString());
    setValue('name', `${providerName} Config - ${randomNumber}`);

    setSelectedModels([]); // Reset selected models when provider changes
  };

  const updateSelectedModel = (modelSpecId: string, updates: Partial<SelectedModel>) => {
    setSelectedModels(prev => prev.map(model => 
      model.modelSpecId === modelSpecId ? { ...model, ...updates } : model
    ));
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
          endpoint_url: data.endpoint_url === '' ? null : data.endpoint_url,
          is_active: data.is_public, // Note: backend uses is_active, frontend uses is_public
        };
        
        // Only include api_key if it's provided (not empty)
        if (data.api_key && data.api_key.trim() !== '') {
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
          api_key: data.api_key || '', // API key is required for creation, so this should never be undefined
          endpoint_url: data.endpoint_url === '' ? null : data.endpoint_url,
          is_public: data.is_public,
        });
        providerConfig = result.data;
        providerError = result.error;
      }

      if (providerError || !providerConfig) {
        const errorMessage = (providerError as { detail?: { msg?: string }[]; message?: string })?.detail?.[0]?.msg || (providerError as { message?: string })?.message || 'Unknown error';
        throw new Error(`Failed to ${isEdit ? 'update' : 'create'} provider configuration: ${errorMessage}`);
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
            throw new Error(`Failed to create model instance "${model.instanceName}": ${(error as { message?: string })?.message || 'Unknown error'}`);
          }
          
          return data;
        });

        await Promise.all(modelCreationPromises);
        toast.success(`Provider configuration ${isEdit ? 'updated' : 'created'} successfully with ${selectedModels.length} model instances!`);
      } else {
        toast.success(`Provider configuration ${isEdit ? 'updated' : 'created'} successfully!`);
      }

      // Call custom after submit handler if provided
      if (onAfterSubmit) {
        await onAfterSubmit(providerConfig);
      }

      // Reset form only if creating and no custom handler
      if (!isEdit && !onAfterSubmit) {
        reset({
          provider_spec_id: '',
          name: '',
          api_key: '',
          endpoint_url: '',
          is_public: false,
        });
        setSelectedModels([]);
      }

      // Redirect if autoRedirect is enabled and no custom handler
      if (autoRedirect && !onAfterSubmit) {
        router.push('/admin/provider-configs');
        router.refresh();
      }

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
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
      router.push('/admin/provider-configs');
    }
  };

  return (
    <form onSubmit={(e) => {
      e.preventDefault();
      e.stopPropagation();
      handleSubmit(onSubmit)(e);
    }} className={cn("space-y-6", className)}>
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
      <div className={cn(
        "mx-auto grid lg:gap-x-[12px] gap-[12px] items-start transition-all duration-300 ",
        // "max-w-6xl grid-cols-1 lg:grid-cols-2"
        // watchedProviderId ? "max-w-6xl grid-cols-1 lg:grid-cols-2" : "grid-cols-1 max-w-4xl"
      )}>
      {/* Step 1: Provider Configuration */}
      <div className={cn(
        "grid grid-cols-1 gap-6",
        isClear ? "p-0" : "card card-shadow"
      )}>
          <div className="space-y-2">
            <FormLabel htmlFor="provider" icon={Server}>Provider</FormLabel>
            <Controller
              name="provider_spec_id"
              control={control}
              render={({ field }) => (
                <SearchableSelect
                  options={providerSpecs.map(spec => ({
                    id: spec.id,
                    label: spec.name,
                    icon: spec.icon_url || getProviderIconUrl(spec.name)
                  }))}
                  value={field.value}
                  onValueChange={handleProviderChange}
                  placeholder="Select provider"
                  disabled={!!preselectedProviderId && !isEdit && !initialData}
                  emptyMessage={
                    <div className="flex flex-col items-center justify-center h-full gap-1">
                      <div className="flex items-center justify-center w-7 h-7 bg-primary/20 rounded-md dark:bg-primary-foreground/20">
                          <Bot className="w-5 h-5 text-primary dark:text-primary-foreground" />
                      </div>
                      <span className="text-muted-foreground">No providers found</span>
                    </div>
                  }
                />
              )}
            />
            {errors.provider_spec_id && (
              <p className="text-sm text-red-600">{errors.provider_spec_id.message}</p>
            )}
            {preselectedProviderId && !isEdit && !initialData && (
              <p className="note">
                Provider is pre-selected for this configuration.
              </p>
            )}
          </div>

          <BaseInfo control={control} errors={errors} providerSpecId={watchedProviderId} isEdit={isEdit} />
          
          <AnimatePresence>
          {
            selectedProvider && showModelSelection && (
              <motion.div
                initial={{ height: 0, opacity: 0, overflow: "hidden"}}
                animate={{ height: "auto", opacity: 1, overflow: "visible"}}
                exit={{ height: 0, opacity: 0, overflow: "hidden"}}
                transition={{ duration: 0.4, ease: "easeOut"}}
              >
                <ModelInstances selectedProvider={selectedProvider} availableModels={availableModels} selectedModels={selectedModels} setSelectedModels={setSelectedModels} />
              </motion.div>
            )
          }
          </AnimatePresence>

          {/* <div className="flex items-center space-x-2">
            <Controller

              name="is_public"
              control={control}
              render={({ field }) => (
                <Switch
                  id="is_public"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
            <FormLabel htmlFor="is_public" className="flex items-center gap-2" icon={watch('is_public') ? Users : Lock}>
              {watch('is_public') ? 'Public Configuration' : 'Private Configuration'}
            </FormLabel>
          </div> */}
      </div>

      {/* Step 2: Model Selection (only for create mode) */}

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
          {cancelButtonText || 'Cancel'}
        </Button>
        <Button 
          type="submit" 
          disabled={isSubmitting || !isValid}
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          {isSubmitting 
            ? (isEdit ? 'Updating...' : 'Creating...') 
            : (submitButtonText || (isEdit 
                ? 'Update Configuration' 
                : `Create Configuration${selectedModels.length > 0 && showModelSelection ? ` + ${selectedModels.length} Models` : ''}`
              ))
          }
        </Button>
      </div>
    </form>
  );
} 