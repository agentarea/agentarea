"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { listLLMModels, createLLMModelInstance, LLMModel } from "@/lib/api";

interface LLMProvider {
  id: string;
  name: string;
  description?: string;
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

export default function LLMModelForm() {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [models, setModels] = useState<LLMModel[]>([]);
  const [filteredModels, setFilteredModels] = useState<LLMModel[]>([]);
  const [formData, setFormData] = useState<FormData>({
    providerId: "",
    modelId: "",
    name: "",
    description: "",
    apiKey: "",
    isDefault: false,
    isPublic: true,
  });
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  // Fetch providers and models from backend
  useEffect(() => {
    async function fetchProvidersAndModels() {
      // Fetch providers from backend
      const providersRes = await fetch("/api/llm-providers");
      const providersData = await providersRes.json();
      setProviders(providersData);
      // Fetch all models from backend
      const { data } = await listLLMModels();
      if (data) {
        setModels(data);
      }
    }
    fetchProvidersAndModels();
  }, []);

  // Filter models by providerId
  useEffect(() => {
    if (formData.providerId) {
      setFilteredModels(models.filter((m) => {
        return ('provider_id' in m ? (m as { provider_id: string }).provider_id : (m as { provider: string }).provider) === formData.providerId;
      }));
    } else {
      setFilteredModels([]);
    }
    // Reset model selection if provider changes
    setFormData((prev) => ({ ...prev, modelId: "", name: "", description: "" }));
  }, [formData.providerId, models]);

  // When model changes, prefill name/description
  useEffect(() => {
    if (formData.modelId) {
      const model = models.find((m) => m.id === formData.modelId);
      if (model) {
        setFormData((prev) => ({
          ...prev,
          name: model.name,
          description: model.description,
        }));
      }
    }
  }, [formData.modelId, models]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleProviderChange = (value: string) => {
    setFormData((prev) => ({ ...prev, providerId: value }));
    setErrors({});
  };

  const handleModelChange = (value: string) => {
    setFormData((prev) => ({ ...prev, modelId: value }));
    setErrors({});
  };

  const handleSwitchChange = (checked: boolean) => {
    setFormData((prev) => ({ ...prev, isDefault: checked }));
  };

  const handlePublicSwitchChange = (checked: boolean) => {
    setFormData((prev) => ({ ...prev, isPublic: checked }));
  };

  const validate = () => {
    const newErrors: { [key: string]: string } = {};
    if (!formData.providerId) newErrors.providerId = "Provider is required.";
    if (!formData.modelId) newErrors.modelId = "Model is required.";
    if (!formData.name) newErrors.name = "Model name is required.";
    if (!formData.apiKey) newErrors.apiKey = "API key is required.";
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!validate()) return;
    setLoading(true);
    setSuccess(false);
    // Find selected model for model_id and description
    const model = models.find((m) => m.id === formData.modelId);
    if (!model) {
      setErrors({ modelId: "Selected model not found." });
      setLoading(false);
      return;
    }
    const payload = {
      model_id: model.id,
      api_key: formData.apiKey,
      name: formData.name,
      description: formData.description,
      is_public: formData.isPublic,
    };
    const { error } = await createLLMModelInstance(payload);
    setLoading(false);
    if (!error) {
      setSuccess(true);
      setFormData({
        providerId: "",
        modelId: "",
        name: "",
        description: "",
        apiKey: "",
        isDefault: false,
        isPublic: true,
      });
    } else {
      setErrors({ apiKey: typeof error === "string" ? error : "Failed to add model instance." });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-1.5">
        <Label htmlFor="provider">Provider</Label>
        <Select value={formData.providerId} onValueChange={handleProviderChange}>
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
        {errors.providerId && <p className="text-sm text-red-500 mt-1">{errors.providerId}</p>}
      </div>

      {formData.providerId && (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="model">Model</Label>
            <Select value={formData.modelId} onValueChange={handleModelChange}>
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
            {errors.modelId && <p className="text-sm text-red-500 mt-1">{errors.modelId}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="name">Model Name</Label>
            <Input
              id="name"
              name="name"
              placeholder="e.g. Claude 3.5 Sonnet"
              value={formData.name}
              onChange={handleChange}
              required
              className="w-full"
            />
            {errors.name && <p className="text-sm text-red-500 mt-1">{errors.name}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="description">Description</Label>
            <Input
              id="description"
              name="description"
              placeholder="Model description"
              value={formData.description}
              onChange={handleChange}
              className="w-full"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="apiKey">API Key</Label>
            <Input
              id="apiKey"
              name="apiKey"
              type="password"
              placeholder="Enter your API key"
              value={formData.apiKey}
              onChange={handleChange}
              required
              className="w-full"
            />
            {errors.apiKey && <p className="text-sm text-red-500 mt-1">{errors.apiKey}</p>}
          </div>

          <div className="flex items-center space-x-2 pt-2">
            <Switch
              id="default-switch"
              checked={formData.isDefault}
              onCheckedChange={handleSwitchChange}
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
              checked={formData.isPublic}
              onCheckedChange={handlePublicSwitchChange}
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
            <Button type="submit" disabled={loading}>{loading ? "Adding..." : "Add Model"}</Button>
          </div>
          {success && <p className="text-green-600 pt-2">LLM model instance added successfully!</p>}
        </>
      )}
    </form>
  );
} 