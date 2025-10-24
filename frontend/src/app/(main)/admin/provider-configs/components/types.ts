export interface ProviderSpec {
  id: string;
  provider_key: string;
  name: string;
  description: string | null;
  provider_type: string;
  icon_url: string | null;
  is_builtin: boolean;
  models: any[];
}

export interface ModelInstance {
  id: string;
  provider_config_id: string;
  model_spec_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  is_public: boolean;
  created_at: string;
  updated_at: string;
  provider_name: string | null;
  provider_key: string | null;
  model_name: string | null;
  model_display_name: string | null;
  config_name: string | null;
}

export interface ProviderConfig {
  id: string;
  provider_spec_id: string;
  name: string;
  endpoint_url: string | null;
  is_active: boolean;
  is_public: boolean;
  created_at: string;
  provider_spec_name: string | null;
  provider_spec_key: string | null;
  spec?: ProviderSpec;
  model_instances?: ModelInstance[];
}
