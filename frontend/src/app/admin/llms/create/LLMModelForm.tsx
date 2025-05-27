"use client";
import { useFormState, useFormStatus } from 'react-dom';
import { useForm, SubmitHandler } from 'react-hook-form';
import { useEffect, useMemo } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { LLMModel } from "@/lib/api";
import { addLLMModelInstance } from './actions';
import { initialState } from './state';

interface LLMProvider {
  id: string;
  name: string;
}

interface FormData {
  providerId: string;
  modelId: string;
  name: string;
  description: string;
  apiKey: string;
  isDefault: boolean;
  isPublic: boolean;
}

interface LLMModelFormProps {
  llms: LLMModel[];
}

function SubmitButton() {
  const { pending } = useFormStatus();
  
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "Adding..." : "Add Model"}
    </Button>
  );
}

export default function LLMModelForm({ llms }: LLMModelFormProps) {
  const [state, formAction] = useFormState(addLLMModelInstance, initialState);

  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
    reset,
  } = useForm<FormData>({
    defaultValues: {
      providerId: '',
      modelId: '',
      name: '',
      description: '',
      apiKey: '',
      isDefault: false,
      isPublic: true,
    },
  });

  // Watch form values for dependent logic
  const watchedProviderId = watch('providerId');
  const watchedModelId = watch('modelId');

  // Extract unique providers from models
  const providers = useMemo(() => {
    const uniqueProviders = new Map<string, LLMProvider>();
    
    llms.forEach((model) => {
      const providerId = 'provider_id' in model ? (model as LLMModel & { provider_id: string }).provider_id : model.provider;
      const providerName = model.provider;
      
      if (!uniqueProviders.has(providerId)) {
        uniqueProviders.set(providerId, {
          id: providerId,
          name: providerName,
        });
      }
    });
    
    return Array.from(uniqueProviders.values());
  }, [llms]);

  // Filter models by selected provider
  const filteredModels = useMemo(() => {
    if (!watchedProviderId) return [];
    
    return llms.filter((model) => {
      const modelProviderId = 'provider_id' in model ? (model as LLMModel & { provider_id: string }).provider_id : model.provider;
      return modelProviderId === watchedProviderId;
    });
  }, [llms, watchedProviderId]);

  // Update form with values returned from server action (e.g., on validation error)
  useEffect(() => {
    if (state.fieldValues) {
      Object.entries(state.fieldValues).forEach(([key, value]) => {
        setValue(key as keyof FormData, value as string | boolean);
      });
    }
  }, [state, setValue]);

  // Reset form on successful submission
  useEffect(() => {
    if (state.message && state.message.includes('successfully') && !state.errors) {
      reset();
    }
  }, [state.message, state.errors, reset]);

  // Combine react-hook-form errors and server action errors
  const combinedErrors = {
    ...errors,
    ...state.errors,
  };

  const getErrorMessage = (error: string | string[] | { message?: string } | undefined) => {
    if (typeof error === 'string') return error;
    if (Array.isArray(error)) return error[0];
    return error?.message;
  };

  const handleProviderChange = (value: string) => {
    setValue('providerId', value);
    setValue('modelId', ''); // Reset model when provider changes
    setValue('name', '');
    setValue('description', '');
  };

  const handleModelChange = (value: string) => {
    const model = llms.find((m) => m.id === value);
    setValue('modelId', value);
    setValue('name', model?.name || '');
    setValue('description', model?.description || '');
  };

  // Handle form submission with react-hook-form validation
  const onSubmit: SubmitHandler<FormData> = async (data) => {
    // Create FormData for server action
    const formData = new FormData();
    Object.entries(data).forEach(([key, value]) => {
      formData.append(key, value.toString());
    });
    
    // Call server action
    formAction(formData);
  };

  return (
    <div>
      {/* Display general form errors */}
      {state.errors?._form && (
        <div className="text-red-500 text-sm mb-4" role="alert">
          {state.errors._form.join(', ')}
        </div>
      )}

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div className="space-y-1.5">
          <Label htmlFor="provider">Provider</Label>
          <Select 
            value={watchedProviderId} 
            onValueChange={handleProviderChange}
          >
            <SelectTrigger id="provider" className="w-full">
              <SelectValue placeholder="Select provider" />
            </SelectTrigger>
            <SelectContent>
              {providers.map((provider) => (
                <SelectItem key={provider.id} value={provider.id}>
                  <span className="flex items-center gap-2">
                    <Avatar className="h-5 w-5">
                      <AvatarFallback>{provider.name[0]?.toUpperCase()}</AvatarFallback>
                    </Avatar>
                    {provider.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <input 
            type="hidden" 
            {...register('providerId', { required: 'Provider is required' })} 
          />
          {combinedErrors.providerId && (
            <span className="text-sm text-red-500" role="alert">
              {getErrorMessage(combinedErrors.providerId)}
            </span>
          )}
        </div>

        {watchedProviderId && (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="model">Model</Label>
              <Select 
                value={watchedModelId} 
                onValueChange={handleModelChange}
              >
                <SelectTrigger id="model" className="w-full">
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {filteredModels.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <input 
                type="hidden" 
                {...register('modelId', { required: 'Model is required' })} 
              />
              {combinedErrors.modelId && (
                <span className="text-sm text-red-500" role="alert">
                  {getErrorMessage(combinedErrors.modelId)}
                </span>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="name">Model Name</Label>
              <Input
                id="name"
                {...register('name', { required: 'Model name is required' })}
                placeholder="e.g. Claude 3.5 Sonnet"
                className="w-full"
                aria-invalid={!!combinedErrors.name}
              />
              {combinedErrors.name && (
                <span className="text-sm text-red-500" role="alert">
                  {getErrorMessage(combinedErrors.name)}
                </span>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                {...register('description')}
                placeholder="Model description"
                className="w-full"
                aria-invalid={!!combinedErrors.description}
              />
              {combinedErrors.description && (
                <span className="text-sm text-red-500" role="alert">
                  {getErrorMessage(combinedErrors.description)}
                </span>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="apiKey">API Key</Label>
              <Input
                id="apiKey"
                {...register('apiKey', { required: 'API key is required' })}
                type="password"
                placeholder="Enter your API key"
                className="w-full"
                aria-invalid={!!combinedErrors.apiKey}
              />
              {combinedErrors.apiKey && (
                <span className="text-sm text-red-500" role="alert">
                  {getErrorMessage(combinedErrors.apiKey)}
                </span>
              )}
            </div>

            <div className="flex items-center space-x-2 pt-2">
              <Switch
                id="default-switch"
                checked={watch('isDefault')}
                onCheckedChange={(checked) => setValue('isDefault', checked)}
              />
              <input 
                type="hidden" 
                {...register('isDefault')} 
              />
              <div className="grid gap-1.5 leading-none">
                <Label htmlFor="default-switch" className="cursor-pointer">
                  Set as default LLM
                </Label>
                <p className="text-sm text-muted-foreground">
                  This model will be used as the default for new agents and workflows.
                </p>
              </div>
            </div>

            <div className="flex items-center space-x-2 pt-2">
              <Switch
                id="public-switch"
                checked={watch('isPublic')}
                onCheckedChange={(checked) => setValue('isPublic', checked)}
              />
              <input 
                type="hidden" 
                {...register('isPublic')} 
              />
              <div className="grid gap-1.5 leading-none">
                <Label htmlFor="public-switch" className="cursor-pointer">
                  Public
                </Label>
                <p className="text-sm text-muted-foreground">
                  Make this model instance available to all users.
                </p>
              </div>
            </div>

            <div className="flex justify-end pt-4 border-t">
              <SubmitButton />
            </div>

            {/* Display success/failure message */}
            {state.message && !state.errors && (
              <p className="text-green-600 pt-2" role="alert">{state.message}</p>
            )}
            {state.message && state.errors && (
              <p className="text-red-600 pt-2" role="alert">{state.message}</p>
            )}
          </>
        )}
      </form>
    </div>
  );
} 