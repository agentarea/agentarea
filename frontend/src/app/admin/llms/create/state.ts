import type { AddLLMModelInstanceFormState } from './actions';

export const initialState: AddLLMModelInstanceFormState = {
  message: '',
  fieldValues: {
    providerId: '',
    modelId: '',
    name: '',
    description: '',
    apiKey: '',
    isDefault: false,
    isPublic: true,
  },
}; 