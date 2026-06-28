import type { AgentareaApiApiV1ModelSpecsModelSpecResponse, ModelInstanceResponse, ProviderConfigResponse, ProviderSpecResponse } from "@/api/client/types.gen";

// Re-export types from API schema for convenience
export type ProviderSpec = ProviderSpecResponse;
export type ProviderConfig = ProviderConfigResponse;
export type ModelSpec =
  AgentareaApiApiV1ModelSpecsModelSpecResponse;
export type ModelInstance = ModelInstanceResponse;

// Custom types for the form
export interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

// Form data type
export interface ProviderConfigFormData {
  provider_spec_id: string;
  name: string;
  api_key?: string;
  endpoint_url?: string;
  is_public: boolean;
}

// Props for the universal form component
export interface ProviderConfigFormProps {
  initialData?: ProviderConfig;
  className?: string;
  isEdit?: boolean;
  preselectedProviderId?: string;
  isClear?: boolean;
  onAfterSubmit?: (config: ProviderConfig) => void | Promise<void>;
  onCancel?: () => void;
  submitButtonText?: string;
  cancelButtonText?: string;
  showModelSelection?: boolean;
  autoRedirect?: boolean;
  existingModelInstances?: ModelInstance[];
}
