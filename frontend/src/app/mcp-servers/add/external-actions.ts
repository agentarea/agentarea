'use server';

import { redirect } from 'next/navigation';
import { revalidatePath } from 'next/cache';
import { createMCPServerInstance } from '@/lib/api';
import { z } from 'zod';

// Define the schema for validation using Zod
const HeaderSchema = z.object({
  key: z.string().min(1, 'Header key is required'),
  value: z.string().min(1, 'Header value is required')
});

const ExternalMCPServerSchema = z.object({
  name: z.string().min(1, 'Server name is required'),
  description: z.string().min(1, 'Description is required'),
  endpointUrl: z
    .string()
    .min(1, 'Endpoint URL is required')
    .url('Invalid URL format'),
  headers: z.array(HeaderSchema).optional().default([]),
  tags: z.string().optional(),
  isPublic: z.boolean(),
});

export interface AddExternalMCPServerFormState {
  message: string;
  errors?: {
    name?: string[];
    description?: string[];
    endpointUrl?: string[];
    headers?: Array<{
      key?: string[];
      value?: string[];
    }>;
    tags?: string[];
    isPublic?: string[];
    _form?: string[]; // General form errors
  };
  fieldValues?: {
    name: string;
    description: string;
    endpointUrl: string;
    headers: Array<{
      key: string;
      value: string;
    }>;
    tags: string[];
    isPublic: boolean;
  };
}

export async function addExternalMCPServer(
  prevState: AddExternalMCPServerFormState,
  formData: FormData
): Promise<AddExternalMCPServerFormState> {
  // Extract header data from FormData
  const headerKeys: string[] = [];
  const headerValues: string[] = [];

  // Find all header keys and values in formData
  for (const [key, value] of formData.entries()) {
    if (key.startsWith('headers.') && key.endsWith('.key')) {
      headerKeys.push(value as string);
    }
    if (key.startsWith('headers.') && key.endsWith('.value')) {
      headerValues.push(value as string);
    }
  }

  // Create headers array from the extracted data
  const headers = headerKeys.map((key, index) => ({
    key,
    value: headerValues[index] || '',
  }));

  const rawFormData = {
    name: formData.get('name') as string,
    description: formData.get('description') as string,
    endpointUrl: formData.get('endpointUrl') as string,
    headers,
    tags: formData.get('tags') as string,
    isPublic: formData.get('isPublic') === 'true' || formData.get('isPublic') === true,
  };

  const validatedFields = ExternalMCPServerSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
    console.error("Validation Errors:", validatedFields.error.flatten().fieldErrors);
    return {
      message: 'Validation failed. Please check the fields.',
      errors: validatedFields.error.flatten().fieldErrors as any,
      fieldValues: rawFormData,
    };
  }

  // Prepare config object with headers if available
  const config: Record<string, any> = {};
  if (validatedFields.data.headers && validatedFields.data.headers.length > 0) {
    config.headers = validatedFields.data.headers.reduce(
      (acc, header) => ({ ...acc, [header.key]: header.value }),
      {}
    );
  }

  let response;
  try {
    // Create an MCP Server Instance directly
    response = await createMCPServerInstance({
      server_id: "00000000-0000-0000-0000-000000000000", // This will be ignored as the endpoint URL is provided
      name: validatedFields.data.name,
      endpoint_url: validatedFields.data.endpointUrl,
      config: config,
    });

    if (response.data) {
      console.log("External MCP server added successfully:", response.data);
      // Invalidate cache for the list page
      revalidatePath('/mcp-servers');
    } else {
      console.error("Failed to add external MCP server:", response.error || response.response?.statusText);
      return {
        message: `Failed to add server: ${response.error?.message || response.response?.statusText || 'Unknown error'}`,
        errors: { _form: [`API Error: ${response.response?.status}`] },
        fieldValues: validatedFields.data,
      };
    }
  } catch (error) {
    console.error("Error adding external MCP server:", error);
    let errorMessage = 'An unexpected error occurred.';
    if (error instanceof Error) {
      errorMessage = error.message;
    }
    return {
      message: 'An error occurred while adding the external MCP server.',
      errors: { _form: [errorMessage] },
      fieldValues: validatedFields.data,
    };
  }

  // Redirect on successful creation
  if (response.data) {
    redirect('/mcp-servers'); // Redirect to the list page
  } else {
    return {
      message: 'Failed to add server after API call.',
      errors: { _form: ['Post-API call check failed.'] },
      fieldValues: validatedFields.data,
    };
  }
} 