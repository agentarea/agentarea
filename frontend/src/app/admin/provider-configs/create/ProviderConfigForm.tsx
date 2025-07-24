'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { motion, AnimatePresence } from 'framer-motion';
import { createProviderConfig, createModelInstance, updateProviderConfig } from '@/lib/api';
import { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { SearchableSelect } from '@/components/ui/searchable-select';
import { CheckCircle2, AlertCircle, Bot, Server } from 'lucide-react';
import FormLabel from '@/components/FormLabel/FormLabel';
import BaseInfo from './components/BaseInfo';
import ModelInstances from './components/ModelInstances';
import { getProviderIconUrl } from '@/lib/provider-icons';
import { cn } from '@/lib/utils';


type ProviderSpec = components['schemas']['ProviderSpecResponse'];
export type ModelSpec = {
  id: string;
  provider_spec_id: string;
  model_name: string;
  display_name: string;
  description: string;
  context_window: number;
  is_active: boolean;
};

export interface ProviderConfigFormProps {
  providerSpecs: ProviderSpec[];
  modelSpecs: ModelSpec[];
  initialData?: components['schemas']['ProviderConfigResponse'];
  isEdit?: boolean;
  preselectedProviderId?: string;
}

interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

// Form validation schema
const providerConfigSchema = z.object({
  provider_spec_id: z.string().min(1, 'Provider is required'),
  name: z.string().min(1, 'Name is required').max(255, 'Name must be less than 255 characters'),
  api_key: z.string().min(1, 'API key is required'),
  endpoint_url: z.string().optional(),
  is_public: z.boolean(),
});

type ProviderConfigFormData = z.infer<typeof providerConfigSchema>;

export default function ProviderConfigForm({ 
  providerSpecs, 
  modelSpecs, 
  initialData, 
  isEdit = false,
  preselectedProviderId 
}: ProviderConfigFormProps) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [expandedModels, setExpandedModels] = useState<Set<string>>(new Set());
  const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);

  // Initialize react-hook-form
  const {
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isValid },
    reset
  } = useForm<ProviderConfigFormData>({
    resolver: zodResolver(providerConfigSchema),
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
    if (selectedProvider && availableModels.length > 0 && !isEdit) {
      const allModels = availableModels.map(model => ({
        modelSpecId: model.id,
        instanceName: `${selectedProvider.name} ${model.display_name}`,
        description: model.description || '',
        isPublic: false
      }));
      setSelectedModels(allModels);
    }
  }, [selectedProvider, availableModels, isEdit]);

  // Handle case where data is not loaded
  if (!providerSpecs || !modelSpecs) {
    return (
      <div className="text-center py-10">
        <p className="text-muted-foreground">Loading provider specifications...</p>
      </div>
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
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      // Step 1: Create or update the provider configuration
      let providerConfig;
      let providerError;

      if (isEdit && initialData) {
        const result = await updateProviderConfig(initialData.id, {
          name: data.name,
          api_key: data.api_key,
          endpoint_url: data.endpoint_url || undefined,
          is_active: data.is_public, // Note: backend uses is_active, frontend uses is_public
        });
        providerConfig = result.data;
        providerError = result.error;
      } else {
        const result = await createProviderConfig({
          provider_spec_id: data.provider_spec_id,
          name: data.name,
          api_key: data.api_key,
          endpoint_url: data.endpoint_url || undefined,
          is_public: data.is_public,
        });
        providerConfig = result.data;
        providerError = result.error;
      }

      if (providerError || !providerConfig) {
        const errorMessage = (providerError as { detail?: { msg?: string }[]; message?: string })?.detail?.[0]?.msg || (providerError as { message?: string })?.message || 'Unknown error';
        throw new Error(`Failed to ${isEdit ? 'update' : 'create'} provider configuration: ${errorMessage}`);
      }

      // Step 2: Create model instances if any are selected (only for create mode)
      if (!isEdit && selectedModels.length > 0) {
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
        setSuccess(`Provider configuration ${isEdit ? 'updated' : 'created'} successfully with ${selectedModels.length} model instances!`);
      } else {
        setSuccess(`Provider configuration ${isEdit ? 'updated' : 'created'} successfully!`);
      }

      // Reset form only if creating
      if (!isEdit) {
        reset({
          provider_spec_id: '',
          name: '',
          api_key: '',
          endpoint_url: '',
          is_public: false,
        });
        setSelectedModels([]);
      }

      // Redirect after a short delay
      setTimeout(() => {
        router.push('/admin/provider-configs');
      }, 2000);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
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

        {success && (
          <motion.div
            initial={{ opacity: 0, height: 0, scale: 0.95 }}
            animate={{ opacity: 1, height: "auto", scale: 1 }}
            exit={{ opacity: 0, height: 0, scale: 0.95 }}
            transition={{ duration: 0.3 }}
          >
            <Alert className="border-green-200 bg-green-50">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <AlertDescription className="text-green-800">{success}</AlertDescription>
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
      <Card className="grid grid-cols-1 gap-6">
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
                  disabled={!!preselectedProviderId && !isEdit}
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
            {preselectedProviderId && !isEdit && (
              <p className="note">
                Provider is pre-selected for this configuration.
              </p>
            )}
          </div>

          <BaseInfo control={control} errors={errors} providerSpecId={watchedProviderId} />

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
      </Card>

      {/* Step 2: Model Selection (only for create mode) */}
      <AnimatePresence>
        {!isEdit && selectedProvider && (
          <motion.div
            initial={{ height: 0, opacity: 0,scale: 0.95, overflow: "hidden" }}
            animate={{ height: "auto", opacity: 1,scale: 1, overflow: "visible" }}
            exit={{ height: 0, opacity: 0,scale: 0.95, overflow: "hidden" }}
            transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1], opacity: { duration: 0.4, delay: 0.2 }}}
          >
            <ModelInstances selectedProvider={selectedProvider} availableModels={availableModels} />
          </motion.div>
        )}
      </AnimatePresence>
      </div>

      {/* Submit Button */}
      <div className="flex justify-end space-x-4">
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push('/admin/provider-configs')}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting || !isValid}>
          {isSubmitting 
            ? (isEdit ? 'Updating...' : 'Creating...') 
            : (isEdit 
                ? 'Update Configuration' 
                : `Create Configuration${selectedModels.length > 0 ? ` + ${selectedModels.length} Models` : ''}`
              )
          }
        </Button>
      </div>
    </form>
  );
} 