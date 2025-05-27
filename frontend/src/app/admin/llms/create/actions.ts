'use server';

import { redirect } from 'next/navigation';
import { revalidatePath } from 'next/cache';
import { createLLMModelInstance } from '@/lib/api';
import { z } from 'zod';

// Define the schema for validation using Zod
const LLMModelInstanceSchema = z.object({
  providerId: z.string().min(1, 'Provider is required'),
  modelId: z.string().min(1, 'Model is required'),
  name: z.string().min(1, 'Model name is required'),
  description: z.string().optional(),
  apiKey: z.string().min(1, 'API key is required'),
  isDefault: z.boolean().optional().default(false),
  isPublic: z.boolean().optional().default(true),
});

export interface AddLLMModelInstanceFormState {
  message: string;
  errors?: {
    providerId?: string[];
    modelId?: string[];
    name?: string[];
    description?: string[];
    apiKey?: string[];
    isDefault?: string[];
    isPublic?: string[];
    _form?: string[]; // General form errors
  };
  fieldValues?: {
    providerId: string;
    modelId: string;
    name: string;
    description: string;
    apiKey: string;
    isDefault: boolean;
    isPublic: boolean;
  };
}

export async function addLLMModelInstance(
  prevState: AddLLMModelInstanceFormState,
  formData: FormData
): Promise<AddLLMModelInstanceFormState> {
  const rawFormData = {
    providerId: formData.get('providerId') as string,
    modelId: formData.get('modelId') as string,
    name: formData.get('name') as string,
    description: formData.get('description') as string,
    apiKey: formData.get('apiKey') as string,
    isDefault: formData.get('isDefault') === 'true',
    isPublic: formData.get('isPublic') === 'true',
  };

  const validatedFields = LLMModelInstanceSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
    console.error("Validation Errors:", validatedFields.error.flatten().fieldErrors);
    return {
      message: 'Validation failed. Please check the fields.',
      errors: validatedFields.error.flatten().fieldErrors,
      fieldValues: rawFormData,
    };
  }

  try {
    const payload = {
      model_id: validatedFields.data.modelId,
      api_key: validatedFields.data.apiKey,
      name: validatedFields.data.name,
      description: validatedFields.data.description || '',
      is_public: validatedFields.data.isPublic,
    };

    const { data, error } = await createLLMModelInstance(payload);

    if (error) {
      console.error("API error:", error);
      const errorMessage = typeof error === "string" ? error : "Failed to add model instance.";
      return {
        message: 'Failed to add LLM model instance',
        errors: { _form: [errorMessage] },
        fieldValues: validatedFields.data,
      };
    }

    if (data) {
      // Revalidate the page to show updated data
      revalidatePath('/admin/llms');
      
      return {
        message: 'LLM model instance added successfully!',
        fieldValues: {
          providerId: "",
          modelId: "",
          name: "",
          description: "",
          apiKey: "",
          isDefault: false,
          isPublic: true,
        },
      };
    }
  } catch (error) {
    console.error("Error adding LLM model instance:", error);
    let errorMessage = 'An unexpected error occurred.';
    if (error instanceof Error) {
      errorMessage = error.message;
    }
    return {
      message: 'An error occurred while adding the LLM model instance.',
      errors: { _form: [errorMessage] },
      fieldValues: validatedFields.data,
    };
  }

  return {
    message: 'Unknown error occurred',
    errors: { _form: ['Unknown error occurred'] },
    fieldValues: validatedFields.data,
  };
} 