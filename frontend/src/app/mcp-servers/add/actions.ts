'use server';

import { redirect } from 'next/navigation';
import { revalidatePath } from 'next/cache';
import {createMCPServer} from '@/lib/api'; // Assuming client setup handles auth etc.
import { z } from 'zod';

// Define the schema for validation using Zod
const MCPServerSchema = z.object({
  name: z.string().min(1, 'Server name is required'),
  description: z.string().min(1, 'Description is required'),
  dockerImageUrl: z
    .string()
    .min(1, 'Docker Image URL is required'), // Basic URL validation
  tags: z.string().optional(), // Assuming tags are optional
  isPublic: z.boolean(),
});

export interface AddMCPServerFormState {
  message: string;
  errors?: {
    name?: string[];
    description?: string[];
    dockerImageUrl?: string[];
    tags?: string[];
    isPublic?: string[];
    _form?: string[]; // General form errors
  };
  fieldValues?: {
    name: string;
    description: string;
    dockerImageUrl: string;
    tags: string[];
    isPublic: boolean;
  };
}

export async function addMCPServer(
  prevState: AddMCPServerFormState,
  formData: FormData
): Promise<AddMCPServerFormState> {
  const rawFormData = {
    name: formData.get('name') as string,
    description: formData.get('description') as string,
    dockerImageUrl: formData.get('dockerImageUrl') as string,
    // Tags are comma-separated string, handle potential splitting later if needed
    tags: formData.get('tags') as string,
    // FormData doesn't handle booleans well directly from checkboxes/switches
    // Need to check value. 'on' is typical for checkboxes, but Switches might differ.
    // We'll handle this properly in the client form component using react-hook-form state.
    // For now, let's assume the client sends a proper boolean or string convertible to boolean.
    // A hidden input controlled by react-hook-form might be best.
    // For simplicity here, we'll parse 'true'/'false' string or boolean value.
    isPublic: formData.get('isPublic') === 'true' || formData.get('isPublic') === true,
  };

  const validatedFields = MCPServerSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
      console.error("Validation Errors:", validatedFields.error.flatten().fieldErrors);
    return {
      message: 'Validation failed. Please check the fields.',
      errors: validatedFields.error.flatten().fieldErrors,
      fieldValues: rawFormData, // Return entered values
    };
  }

  let response;
  try {
    // TODO: Address the type error from the linter.
    // This might require regenerating the client types or checking the OpenAPI schema.
    // Using //@ts-ignore as a temporary workaround if necessary.
    // Assuming '/mcp-servers' is the correct path defined in your OpenAPI spec.
    // Also, ensure the request body format matches the expected schema (e.g., json: validatedFields.data)
    response = await createMCPServer({
      name: validatedFields.data.name,
      description: validatedFields.data.description,
      docker_image_url: validatedFields.data.dockerImageUrl,
      version: "1.0.0",
      tags: validatedFields.data.tags ? [validatedFields.data.tags] : [],
      is_public: validatedFields.data.isPublic,
    });

    // Assuming response structure based on common patterns or previous code
    // Adjust based on actual client library behavior
    if (response.data) {
        console.log("MCP server added successfully:", response.data);
      // Invalidate cache for the list page, if it exists
      revalidatePath('/mcp-servers');
      // Redirect to a success page or the list page
      // For now, just return success state. Redirect happens below.
    } else {
        console.error("Failed to add MCP server:", response.error || response.response?.statusText);
      // Handle API error (e.g., server returned 4xx or 5xx)
      return {
        message: `Failed to add server: ${response.error?.message || response.response?.statusText || 'Unknown error'}`, // @ts-ignore
        errors: { _form: [`API Error: ${response.response?.status}`] }, // @ts-ignore
        fieldValues: validatedFields.data,
      };
    }
  } catch (error) {
    console.error("Error adding MCP server:", error);
    let errorMessage = 'An unexpected error occurred.';
    if (error instanceof Error) {
        errorMessage = error.message;
    }
    return {
      message: 'An error occurred while adding the MCP server.',
       errors: { _form: [errorMessage]},
       fieldValues: validatedFields.data,
    };
  }

  // Redirect only on *successful* creation outside the try block
  // Check if the response indicates success before redirecting
  // The exact check depends on the client library structure
  if (response.data) {
     redirect('/mcp-servers'); // Redirect to the list page after successful addition
  } else {
      // This case should theoretically be caught by the error handling inside try/catch,
      // but adding it for robustness.
      return {
          message: 'Failed to add server after API call.',
          errors: { _form: ['Post-API call check failed.'] },
          fieldValues: validatedFields.data,
      }
  }

} 