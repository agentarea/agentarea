"use client";

import { useEffect, useState } from "react";
import { listModelInstances } from "@/lib/api";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { Bot } from "lucide-react";
import Image from "next/image";

interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
}

interface ModelBadgeProps {
  modelId: string | null | undefined;
}

export default function ModelBadge({ modelId }: ModelBadgeProps) {
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
          console.log('Model not found:', modelId);
        }
      } catch (err) {
        console.error('Failed to fetch model info:', err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchModelInfo();
  }, [modelId]);

  const getProviderIcon = () => {
    if (isLoading) {
      return "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8Y2lyY2xlIGN4PSI4IiBjeT0iOCIgcj0iMyIgZmlsbD0iIzk5OTk5OSIvPgo8L3N2Zz4K";
    }

    if (!modelInfo?.provider_name) {
      return "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNOCA0QzkuMTA0NTcgNCAxMCA0Ljg5NTQzIDEwIDZDMTAgNy4xMDQ1NyA5LjEwNDU3IDggOCA4QzYuODk1NDMgOCA2IDcuMTA0NTcgNiA2QzYgNC44OTU0MyA2Ljg5NTQzIDQgOCA0WiIgZmlsbD0iIzk5OTk5OSIvPgo8cGF0aCBkPSJNOCA5QzkuMTA0NTcgOSAxMCA5Ljg5NTQzIDEwIDExQzEwIDEyLjEwNDYgOS4xMDQ1NyAxMyA4IDEzQzYuODk1NDMgMTMgNiAxMi4xMDQ2IDYgMTFDNiA5Ljg5NTQzIDYuODk1NDMgOSA4IDlaIiBmaWxsPSIjOTk5OTk5Ii8+Cjwvc3ZnPgo=";
    }

    const iconUrl = getProviderIconUrl(modelInfo.provider_name);
    return iconUrl || "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNOCA0QzkuMTA0NTcgNCAxMCA0Ljg5NTQzIDEwIDZDMTAgNy4xMDQ1NyA5LjEwNDU3IDggOCA4QzYuODk1NDMgOCA2IDcuMTA0NTcgNiA2QzYgNC44OTU0MyA2Ljg5NTQzIDQgOCA0WiIgZmlsbD0iIzk5OTk5OSIvPgo8cGF0aCBkPSJNOCA5QzkuMTA0NTcgOSAxMCA5Ljg5NTQzIDEwIDExQzEwIDEyLjEwNDYgOS4xMDQ1NyAxMyA4IDEzQzYuODk1NDMgMTMgNiAxMi4xMDQ2IDYgMTFDNiA5Ljg5NTQzIDYuODk1NDMgOSA4IDlaIiBmaWxsPSIjOTk5OTk5Ii8+Cjwvc3ZnPgo=";
  };

  const getModelName = () => {
    if (isLoading) return "Loading...";
    if (!modelInfo) return "Unknown model";
    
    return modelInfo.model_display_name || modelInfo.config_name || modelInfo.provider_name || "Unknown model";
  };

  const getProviderName = () => {
    if (!modelInfo?.provider_name) return null;
    return modelInfo.provider_name;
  };

  return (
    <div 
      className="flex items-center gap-1 px-2 py-1 bg-gray-100 rounded-md text-sm"
      title={`Model: ${getModelName()}${getProviderName() ? ` (${getProviderName()})` : ''}`}
    >
      <Image
        src={getProviderIcon()}
        alt={getProviderName() || "Model"}
        width={16}
        height={16}
        className="rounded-sm"
        onError={(e) => {
          // Fallback to default icon if image fails to load
          const target = e.target as HTMLImageElement;
          target.src = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNOCA0QzkuMTA0NTcgNCAxMCA0Ljg5NTQzIDEwIDZDMTAgNy4xMDQ1NyA5LjEwNDU3IDggOCA4QzYuODk1NDMgOCA2IDcuMTA0NTcgNiA2QzYgNC44OTU0MyA2Ljg5NTQzIDQgOCA0WiIgZmlsbD0iIzk5OTk5OSIvPgo8cGF0aCBkPSJNOCA5QzkuMTA0NTcgOSAxMCA5Ljg5NTQzIDEwIDExQzEwIDEyLjEwNDYgOS4xMDQ1NyAxMyA4IDEzQzYuODk1NDMgMTMgNiAxMi4xMDQ2IDYgMTFDNiA5Ljg5NTQzIDYuODk1NDMgOSA4IDlaIiBmaWxsPSIjOTk5OTk5Ii8+Cjwvc3ZnPgo=";
        }}
      />
      <span className="text-xs font-medium text-gray-700">
        {getModelName()}
      </span>
      {getProviderName() && (
        <span className="text-xs text-gray-500">
          ({getProviderName()})
        </span>
      )}
    </div>
  );
}
