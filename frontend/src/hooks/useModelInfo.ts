import { useEffect, useState } from "react";
import { getModelSpec, listModelSpecs } from "@/lib/browser-api";

export interface ModelInfo {
  displayName: string;
  providerName: string;
  providerKey: string;
  isLoading: boolean;
  error: string | null;
}

export const useModelInfo = (modelId: string | null | undefined): ModelInfo => {
  const [modelInfo, setModelInfo] = useState<ModelInfo>({
    displayName: "",
    providerName: "",
    providerKey: "",
    isLoading: false,
    error: null,
  });

  useEffect(() => {
    if (!modelId) {
      setModelInfo({
        displayName: "",
        providerName: "",
        providerKey: "",
        isLoading: false,
        error: null,
      });
      return;
    }

    const fetchModelInfo = async () => {
      setModelInfo((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        // First, try to treat modelId as a UUID (model instance ID)
        const isUUID =
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
            modelId
          );

        if (isUUID) {
          // Try to get model spec by ID
          const { data, error } = await getModelSpec(modelId);

          if (error) {
            // If UUID lookup fails, fall back to string search
            console.warn(
              "Failed to fetch model by UUID, trying string search:",
              error
            );
          } else if (data) {
            setModelInfo({
              displayName: data.display_name,
              providerName: data.provider_name || "",
              providerKey: data.provider_key || "",
              isLoading: false,
              error: null,
            });
            return;
          }
        }

        // If not UUID or UUID lookup failed, search by model name
        const { data: modelSpecs, error } = await listModelSpecs({
          is_active: true,
        });

        if (error) {
          setModelInfo({
            displayName: "",
            providerName: "",
            providerKey: "",
            isLoading: false,
            error: error.detail?.[0]?.msg || "Failed to fetch model info",
          });
          return;
        }

        if (modelSpecs) {
          // Find model spec by model_name or display_name
          const foundModel = modelSpecs.find(
            (spec) =>
              spec.model_name.toLowerCase() === modelId.toLowerCase() ||
              spec.display_name.toLowerCase() === modelId.toLowerCase()
          );

          if (foundModel) {
            setModelInfo({
              displayName: foundModel.display_name,
              providerName: foundModel.provider_name || "",
              providerKey: foundModel.provider_key || "",
              isLoading: false,
              error: null,
            });
          } else {
            // If not found, show the original modelId
            setModelInfo({
              displayName: modelId,
              providerName: "",
              providerKey: "",
              isLoading: false,
              error: null,
            });
          }
        }
      } catch (err) {
        setModelInfo({
          displayName: "",
          providerName: "",
          providerKey: "",
          isLoading: false,
          error: err instanceof Error ? err.message : "Unknown error",
        });
      }
    };

    fetchModelInfo();
  }, [modelId]);

  return modelInfo;
};
