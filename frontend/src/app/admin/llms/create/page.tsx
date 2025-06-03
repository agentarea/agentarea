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
    alert("LLM model added successfully! (Demo only)");
  };

  return (
    <ContentBlock
      header={{
        title: "Add LLM Model",
        backLink: {
          label: "Back to LLM Models",
          href: "/admin/llms"
        }
      }}
    >
    <Card className="max-w-2xl mx-auto">
      
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-1.5">
          <Label htmlFor="name" className="label">
            <Bot className="label-icon" style={{ strokeWidth: 1.5 }} /> Model Name
          </Label>
          <Input
            id="name"
            name="name"
            placeholder="e.g. Claude 3.5 Sonnet"
            value={formData.name}
            onChange={handleChange}
            required
            className="w-full"
          />
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="description" className="label">
            <FileText className="label-icon" style={{ strokeWidth: 1.5 }} /> Description
          </Label>
          <Textarea
            id="description"
            name="description"
            placeholder="Describe this model's capabilities and use cases"
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
              <Server className="label-icon" style={{ strokeWidth: 1.5 }} /> Provider
            </Label>
            <Select 
              value={formData.provider}
              onValueChange={(value) => handleSelectChange("provider", value)}
            >
              <SelectTrigger id="provider" className="w-full">
                <SelectValue placeholder="Select provider" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="openai">OpenAI</SelectItem>
                <SelectItem value="anthropic">Anthropic</SelectItem>
                <SelectItem value="meta">Meta AI</SelectItem>
                <SelectItem value="mistral">Mistral AI</SelectItem>
                <SelectItem value="custom">Custom Provider</SelectItem>
              </SelectContent>
            </Select>
          </div>
          
          <div className="space-y-1.5">
            <Label htmlFor="modelType" className="label">
              <Layers className="label-icon" style={{ strokeWidth: 1.5 }} /> Model Type
            </Label>
            <Select 
              value={formData.modelType}
              onValueChange={(value) => handleSelectChange("modelType", value)}
            >
              <SelectTrigger id="modelType" className="w-full">
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text">Text-only</SelectItem>
                <SelectItem value="multimodal">Multi-modal</SelectItem>
                <SelectItem value="embedding">Embedding</SelectItem>
                <SelectItem value="specialized">Specialized</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="endpointUrl" className="label">
            <Link className="label-icon" style={{ strokeWidth: 1.5 }} /> Endpoint URL
          </Label>
          <Input
            id="endpointUrl"
            name="endpointUrl"
            placeholder="e.g. https://api.anthropic.com/v1/messages"
            value={formData.endpointUrl}
            onChange={handleChange}
            required
            className="w-full"
          />
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="apiKey" className="label">
            <Key className="label-icon" style={{ strokeWidth: 1.5 }} /> API Key
          </Label>
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
          <p className="note mt-1">
            Your API key is stored securely and used only for connecting to the model.
          </p>
        </div>
        
        <div className="space-y-1.5">
          <Label htmlFor="contextWindow" className="label">
            <Maximize2 className="label-icon" style={{ strokeWidth: 1.5 }} /> Context Window
          </Label>
          <Select 
            value={formData.contextWindow}
            onValueChange={(value) => handleSelectChange("contextWindow", value)}
          >
            <SelectTrigger id="contextWindow" className="w-full">
              <SelectValue placeholder="Select context size" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="4K">4K tokens</SelectItem>
              <SelectItem value="8K">8K tokens</SelectItem>
              <SelectItem value="16K">16K tokens</SelectItem>
              <SelectItem value="32K">32K tokens</SelectItem>
              <SelectItem value="100K">100K+ tokens</SelectItem>
              <SelectItem value="custom">Custom size</SelectItem>
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
              Share with Organization
            </Label>
            <p className="note">
              Make this model available to other members
            </p>
          </div>
        </div>
        
        <div className="flex justify-end pt-4">
          <Button type="submit">Add Model</Button>
        </div>
      </form>
    </Card>
    </ContentBlock>
  );
} 