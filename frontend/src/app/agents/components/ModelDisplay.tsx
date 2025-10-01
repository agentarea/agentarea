import { useEffect, useState } from "react";
import { listModelInstances } from "@/lib/api";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { Bot } from "lucide-react";

interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
}

interface ModelDisplayProps {
  modelId: string | null | undefined;
  className?: string;
}

export default function ModelDisplay({ 
  modelId, 
  className = ""
}: ModelDisplayProps) {
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const fetchModelInfo = async () => {
      if (!modelId) return;
      
      try {
        setIsLoading(true);
        
        const { data, error } = await listModelInstances();
        if (error) {
          console.error('Failed to fetch model instances:', error);
          return;
        }
        
        // Find the model in the response
        const modelInstance = data?.find(
          (instance: any) => instance.id === modelId
        );
        
        if (modelInstance) {
          setModelInfo({
            provider_name: modelInstance.provider_name || undefined,
            model_display_name: modelInstance.model_display_name || undefined,
            config_name: modelInstance.config_name || undefined
          });
        } else {
        }
      } catch (err) {
        // Model info fetch failed, continue without it
      } finally {
        setIsLoading(false);
      }
    };

    fetchModelInfo();
  }, [modelId]);

  const renderProviderIcon = () => {
    if (isLoading) {
      return <div className="w-5 h-5 animate-pulse bg-gray-200 rounded" />;
    }

    if (!modelInfo?.provider_name) {
      return <Bot className="w-5 h-5 text-muted-foreground" />;
    }

    const iconUrl = getProviderIconUrl(modelInfo.provider_name);
    
    if (iconUrl) {
      return (
        <img
          src={iconUrl}
          alt={modelInfo.provider_name}
          className="w-5 h-5 rounded dark:invert"
          onError={(e) => {
            e.currentTarget.style.display = 'none';
            e.currentTarget.nextElementSibling?.classList.remove('hidden');
          }}
        />
      );
    }

    return <Bot className="w-5 h-5 text-muted-foreground" />;
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 animate-pulse bg-gray-200 rounded" />
        <span className="text-muted-foreground">Loading...</span>
      </div>
    );
  }

  if (!modelInfo) {
    return (
      <div className="flex items-center gap-2">
        <Bot className="w-5 h-5 text-muted-foreground" />
        <span className="text-muted-foreground">Unknown model</span>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {renderProviderIcon()}
      <div className="flex flex-col">
        <span className="font-medium">
          {modelInfo.model_display_name || modelInfo.config_name || modelInfo.provider_name}
        </span>
        {modelInfo.provider_name && modelInfo.model_display_name && (
          <span className="text-sm text-muted-foreground">
            {modelInfo.provider_name}
          </span>
        )}
      </div>
    </div>
  );
} 