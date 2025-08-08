import { useEffect, useState } from "react";
import { listModelInstances } from "@/lib/api";

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

  if (isLoading) {
    return <span className="text-muted-foreground">Loading...</span>;
  }

  if (!modelInfo) {
    return <span className="text-muted-foreground">Unknown model</span>;
  }

  return (
    <span className={className}>
      <span>{modelInfo.config_name || modelInfo.provider_name}</span>
      {modelInfo.model_display_name && (
        <span className="pl-1 font-semibold">({modelInfo.model_display_name})</span>
      )}
    </span>
  );
} 