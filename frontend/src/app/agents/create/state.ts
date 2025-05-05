import type { AddAgentFormState } from './actions';
import type { components } from '@/api/schema';

// Match the AgentCreate schema more closely
export const initialState: AddAgentFormState = {
  message: '',
  errors: {},
  fieldValues: {
    name: '',
    description: '',
    instruction: '',
    model_id: '',
    tools_config: { mcp_server_configs: [] }, // Initialize as object with empty array
    events_config: { events: [] }, // Array of event config objects
    planning: false,
  },
}; 