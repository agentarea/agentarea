"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Card } from "@/components/ui/card";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { useTranslations } from "next-intl";
import { 
  Bot, 
  FileText, 
  Server,
  Layers, 
  Link, 
  Key, 
  Maximize2, 
} from "lucide-react";

interface FormData {
  name: string;
  description: string;
  provider: string;
  modelType: string;
  apiKey: string;
  endpointUrl: string;
  contextWindow: string;
  isPublic: boolean;
}

export default function AddLLMModelPage() {
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    provider: "",
    modelType: "",
    apiKey: "",
    endpointUrl: "",
    contextWindow: "8K",
    isPublic: false,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSelectChange = (name: string, value: string) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSwitchChange = (checked: boolean) => {
    setFormData((prev) => ({ ...prev, isPublic: checked }));
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    console.log("Form data submitted:", formData);
    // Here you would send the data to your API
    alert(t('addModelSuccess'));
  };

  const t = useTranslations('LlmBrowsePage.create');
  const providersList = [
    {
      name: "OpenAI",
      value: "openai"
    },
    {
      name: "Anthropic",
      value: "anthropic"
    },
    {
      name: "Meta AI",  
      value: "meta"
    },
    {
      name: "Mistral AI",
      value: "mistral"
    },
    {
      name: "Custom Provider",
      value: "custom"
    }
  ];

  const modelTypesList = [
    {
      name: "Text-only",
      value: "text"
    },
    {
      name: "Multi-modal",
      value: "multimodal"
    },
    {
      name: "Embedding",
      value: "embedding"
    },
    {
      name: "Specialized",
      value: "specialized"
    }
  ];  

  const contextWindowList = [
    {
      name: "4K tokens",
      value: "4K"
    }, {
      name: "8K tokens",
      value: "8K"
    }, {
      name: "16K tokens",
      value: "16K"
    }, {
      name: "32K tokens",
      value: "32K"
    }, {
      name: "100K+ tokens",
      value: "100K"
    }, {
      name: "Custom size",
      value: "custom"
    },
  ];

  return (
    <ContentBlock
      header={{
        title: t('addNewLlm'),
        backLink: {
          label: t('backToLlmModels'),
          href: "/admin/llms"
        }
      }}
    >
    <Card className="max-w-2xl mx-auto">
      
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-1.5">
          <Label htmlFor="name" className="label">
            <Bot className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('modelName')}
          </Label>
          <Input
            id="name"
            name="name"
            placeholder={t('modelNamePlaceholder')}
            value={formData.name}
            onChange={handleChange}
            required
            className="w-full"
          />
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="description" className="label">
            <FileText className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('description')}
          </Label>
          <Textarea
            id="description"
            name="description"
            placeholder={t('descriptionPlaceholder')}
            value={formData.description}
            onChange={handleChange}
            required
            rows={3}
            className="resize-none"
          />
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-1.5">
            <Label htmlFor="provider" className="label">
              <Server className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('provider')}
            </Label>
            <Select 
              value={formData.provider}
              onValueChange={(value) => handleSelectChange("provider", value)}
            >
              <SelectTrigger id="provider" className="w-full">
                <SelectValue placeholder={t('selectProvider')} />
              </SelectTrigger>
              <SelectContent>
                  {
                    providersList.map((provider) => (
                      <SelectItem key={provider.value} value={provider.value}>
                        {provider.name}
                      </SelectItem>
                    ))
                  }
              </SelectContent>
            </Select>
          </div>
          
          <div className="space-y-1.5">
            <Label htmlFor="modelType" className="label">
              <Layers className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('modelType')}
            </Label>
            <Select 
              value={formData.modelType}
              onValueChange={(value) => handleSelectChange("modelType", value)}
            >
              <SelectTrigger id="modelType" className="w-full">
                <SelectValue placeholder={t('selectType')} />
              </SelectTrigger>
              <SelectContent>
                {
                  modelTypesList.map((modelType) => (
                    <SelectItem key={modelType.value} value={modelType.value}>
                      {modelType.name}
                    </SelectItem>
                  ))
                }
              </SelectContent>
            </Select>
          </div>
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="endpointUrl" className="label">
            <Link className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('endpointUrl')}
          </Label>
          <Input
            id="endpointUrl"
            name="endpointUrl"
            placeholder={t('endpointUrlPlaceholder')}
            value={formData.endpointUrl}
            onChange={handleChange}
            required
            className="w-full"
          />
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="apiKey" className="label">
            <Key className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('apiKey')}
          </Label>
          <Input
            id="apiKey"
            name="apiKey"
            type="password"
            placeholder={t('apiKeyPlaceholder')}
            value={formData.apiKey}
            onChange={handleChange}
            required
            className="w-full"
          />
          <p className="note mt-1">
            {t('apiKeyDescription')}
          </p>
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="contextWindow" className="label">
            <Maximize2 className="label-icon" style={{ strokeWidth: 1.5 }} /> {t('contextWindow')}
          </Label>
          <Select 
            value={formData.contextWindow}
            onValueChange={(value) => handleSelectChange("contextWindow", value)}
          >
            <SelectTrigger id="contextWindow" className="w-full">
              <SelectValue placeholder={t('selectContextSize')} />
            </SelectTrigger>
            <SelectContent>
              {contextWindowList.map((contextWindow) => (
                <SelectItem key={contextWindow.value} value={contextWindow.value}>
                  {contextWindow.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        
        <div className="flex items-center space-x-2 pt-2">
          <Switch
            id="public-switch"
            checked={formData.isPublic}
            onCheckedChange={handleSwitchChange}
          />
          <div className="grid gap-1.5 leading-none">
            <Label htmlFor="public-switch" className="cursor-pointer label">
              {t('public')}
            </Label>
            <p className="note">
              {t('publicDescription')}
            </p>
          </div>
        </div>
        
        <div className="flex justify-end pt-4">
          <Button type="submit">{t('addModel')}</Button>
        </div>
      </form>
    </Card>
    </ContentBlock>
  );
} 