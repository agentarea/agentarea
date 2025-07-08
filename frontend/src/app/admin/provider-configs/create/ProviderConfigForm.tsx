'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { createProviderConfig, createModelInstance, updateProviderConfig } from '@/lib/api';
import { components } from '@/api/schema';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Key, Globe, Server, Brain, CheckCircle2, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';

type ProviderSpec = components['schemas']['ProviderSpecResponse'];
type ModelSpec = {
  id: string;
  provider_spec_id: string;
  model_name: string;
  display_name: string;
  description: string;
  context_window: number;
  is_active: boolean;
};

interface ProviderConfigFormProps {
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

  // Handle case where data is not loaded
  if (!providerSpecs || !modelSpecs) {
    return (
      <div className="text-center py-10">
        <p className="text-muted-foreground">Loading provider specifications...</p>
      </div>
    );
  }
  
  const [formData, setFormData] = useState({
    provider_spec_id: preselectedProviderId || initialData?.provider_spec_id || '',
    name: initialData?.name || '',
    api_key: '', // API key is not returned in responses for security
    endpoint_url: initialData?.endpoint_url || '',
    is_public: initialData?.is_public || false,
  });

  const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);

  const selectedProvider = providerSpecs?.find?.(spec => spec.id === formData.provider_spec_id);
  const availableModels = modelSpecs?.filter?.(model => 
    selectedProvider && model.provider_spec_id === selectedProvider.id
  ) || [];

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

  const handleProviderChange = (providerId: string) => {
    setFormData(prev => ({ ...prev, provider_spec_id: providerId }));
    setSelectedModels([]); // Reset selected models when provider changes
  };

  const handleModelToggle = (modelSpec: ModelSpec, checked: boolean) => {
    if (checked) {
      setSelectedModels(prev => [...prev, {
        modelSpecId: modelSpec.id,
        instanceName: `${selectedProvider?.name} ${modelSpec.display_name}`,
        description: modelSpec.description || '',
        isPublic: false
      }]);
    } else {
      setSelectedModels(prev => prev.filter(m => m.modelSpecId !== modelSpec.id));
    }
  };

  const updateSelectedModel = (modelSpecId: string, updates: Partial<SelectedModel>) => {
    setSelectedModels(prev => prev.map(model => 
      model.modelSpecId === modelSpecId ? { ...model, ...updates } : model
    ));
  };

  const toggleModelExpanded = (modelId: string) => {
    setExpandedModels(prev => {
      const newSet = new Set(prev);
      if (newSet.has(modelId)) {
        newSet.delete(modelId);
      } else {
        newSet.add(modelId);
      }
      return newSet;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setSuccess(null);

    try {
      // Step 1: Create or update the provider configuration
      let providerConfig;
      let providerError;

      if (isEdit && initialData) {
        const result = await updateProviderConfig(initialData.id, {
          name: formData.name,
          api_key: formData.api_key,
          endpoint_url: formData.endpoint_url || undefined,
          is_active: formData.is_public, // Note: backend uses is_active, frontend uses is_public
        });
        providerConfig = result.data;
        providerError = result.error;
      } else {
        const result = await createProviderConfig({
          provider_spec_id: formData.provider_spec_id,
          name: formData.name,
          api_key: formData.api_key,
          endpoint_url: formData.endpoint_url || undefined,
          is_public: formData.is_public,
        });
        providerConfig = result.data;
        providerError = result.error;
      }

      if (providerError || !providerConfig) {
        const errorMessage = (providerError as any)?.detail?.[0]?.msg || (providerError as any)?.message || 'Unknown error';
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
            throw new Error(`Failed to create model instance "${model.instanceName}": ${(error as any)?.message || 'Unknown error'}`);
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
        setFormData({
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
    <form onSubmit={handleSubmit} className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {success && (
        <Alert className="border-green-200 bg-green-50">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <AlertDescription className="text-green-800">{success}</AlertDescription>
        </Alert>
      )}

      {/* Step 1: Provider Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Key className="h-5 w-5" />
            {isEdit ? 'Edit Provider Configuration' : 'Provider Configuration'}
          </CardTitle>
          <CardDescription>
            {isEdit ? 'Update your AI provider configuration' : 'Configure API access to an AI provider'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="provider">Provider</Label>
            <select
              id="provider"
              value={formData.provider_spec_id}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full p-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
              required
              disabled={!!preselectedProviderId && !isEdit}
            >
              <option value="">Select a provider</option>
              {providerSpecs.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
            {preselectedProviderId && !isEdit && (
              <p className="text-sm text-muted-foreground">
                Provider is pre-selected for this configuration.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="name">Configuration Name</Label>
            <Input
              id="name"
              type="text"
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              placeholder="e.g., Production OpenAI Config"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="api_key">API Key</Label>
            <Input
              id="api_key"
              type="password"
              value={formData.api_key}
              onChange={(e) => setFormData(prev => ({ ...prev, api_key: e.target.value }))}
              placeholder="Enter your API key"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="endpoint_url">Custom Endpoint URL (Optional)</Label>
            <Input
              id="endpoint_url"
              type="url"
              value={formData.endpoint_url}
              onChange={(e) => setFormData(prev => ({ ...prev, endpoint_url: e.target.value }))}
              placeholder="https://api.example.com/v1"
            />
          </div>

          <div className="flex items-center space-x-2">
            <Switch
              id="is_public"
              checked={formData.is_public}
              onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_public: checked }))}
            />
            <Label htmlFor="is_public" className="flex items-center gap-2">
              {formData.is_public ? <Globe className="h-4 w-4" /> : <Key className="h-4 w-4" />}
              {formData.is_public ? 'Public Configuration' : 'Private Configuration'}
            </Label>
          </div>
        </CardContent>
      </Card>

      {/* Step 2: Model Selection (only for create mode) */}
      {!isEdit && selectedProvider && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5" />
              Model Instances
            </CardTitle>
            <CardDescription>
              Select models to create instances for this provider configuration
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">
                  Available Models for {selectedProvider.name}:
                </div>
                {availableModels.length > 0 && (
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        // Select all models
                        const allModels = availableModels.map(model => ({
                          modelSpecId: model.id,
                          instanceName: `${selectedProvider?.name} ${model.display_name}`,
                          description: model.description || '',
                          isPublic: false
                        }));
                        setSelectedModels(allModels);
                      }}
                      disabled={selectedModels.length === availableModels.length}
                    >
                      Select All
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedModels([])}
                      disabled={selectedModels.length === 0}
                    >
                      Clear All
                    </Button>
                  </div>
                )}
              </div>
              
              {availableModels.length === 0 ? (
                <div className="text-sm text-muted-foreground bg-gray-50 p-4 rounded-lg text-center">
                  No models available for this provider.
                </div>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {availableModels.map((model) => {
                    const isSelected = selectedModels.some(m => m.modelSpecId === model.id);
                    const selectedModel = selectedModels.find(m => m.modelSpecId === model.id);
                    const isExpanded = expandedModels.has(model.id);
                    
                    return (
                      <div key={model.id} className="border rounded-lg p-4 space-y-3 hover:bg-gray-50 transition-colors">
                        <div className="flex items-start space-x-3">
                          <Checkbox
                            id={`model-${model.id}`}
                            checked={isSelected}
                            onCheckedChange={(checked) => handleModelToggle(model, checked as boolean)}
                          />
                          <div className="flex-1 space-y-1">
                            <div className="flex items-center gap-2">
                              <Label htmlFor={`model-${model.id}`} className="font-medium cursor-pointer">
                                {model.display_name}
                              </Label>
                              {model.context_window && (
                                <Badge variant="outline">
                                  {model.context_window.toLocaleString()} tokens
                                </Badge>
                              )}
                            </div>
                            <div className="text-sm text-muted-foreground">
                              {model.description || 'No description available'}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              Model: {model.model_name}
                            </div>
                          </div>
                        </div>
                        
                        {isSelected && selectedModel && (
                          <>
                            <Button 
                              type="button"
                              variant="ghost" 
                              size="sm" 
                              className="ml-6 w-full justify-start"
                              onClick={() => toggleModelExpanded(model.id)}
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4 mr-2" />
                              ) : (
                                <ChevronRight className="h-4 w-4 mr-2" />
                              )}
                              Configure Instance Settings
                            </Button>
                            
                            {isExpanded && (
                              <div className="ml-6 space-y-3 bg-blue-50 p-3 rounded border-l-2 border-blue-200 mt-2">
                                <div className="text-sm font-medium text-blue-900">
                                  Instance Configuration
                                </div>
                                <div className="space-y-2">
                                  <Label htmlFor={`name-${model.id}`}>Instance Name</Label>
                                  <Input
                                    id={`name-${model.id}`}
                                    value={selectedModel.instanceName}
                                    onChange={(e) => updateSelectedModel(model.id, { instanceName: e.target.value })}
                                    placeholder="Model instance name"
                                  />
                                </div>
                                <div className="space-y-2">
                                  <Label htmlFor={`desc-${model.id}`}>Description (Optional)</Label>
                                  <Textarea
                                    id={`desc-${model.id}`}
                                    value={selectedModel.description}
                                    onChange={(e) => updateSelectedModel(model.id, { description: e.target.value })}
                                    placeholder="Describe this model instance..."
                                    rows={2}
                                  />
                                </div>
                                <div className="flex items-center space-x-2">
                                  <Switch
                                    id={`public-${model.id}`}
                                    checked={selectedModel.isPublic}
                                    onCheckedChange={(checked) => updateSelectedModel(model.id, { isPublic: checked })}
                                  />
                                  <Label htmlFor={`public-${model.id}`}>
                                    Make this instance public
                                  </Label>
                                </div>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              
              {selectedModels.length > 0 && (
                <div className="bg-green-50 p-3 rounded-lg border border-green-200">
                  <div className="text-sm font-medium text-green-900">
                    {selectedModels.length} model{selectedModels.length === 1 ? '' : 's'} selected
                  </div>
                  <div className="text-xs text-green-700 mt-1">
                    These model instances will be created along with your provider configuration.
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Submit Button */}
      <div className="flex justify-end space-x-4">
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push('/admin/provider-configs')}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
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