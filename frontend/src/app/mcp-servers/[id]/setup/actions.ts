'use server'

import { z } from 'zod'
import { revalidatePath } from 'next/cache'
import { createMCPServerInstance } from '@/lib/api'
import type { components } from '@/api/schema'

// Define the form state type
export interface CreateMCPInstanceState {
  message?: string
  errors?: {
    [key: string]: string[]
  }
  success?: boolean
  redirect?: string
}

// Create validation schema
const createMCPInstanceSchema = z.object({
  name: z.string().min(1, 'Name is required').max(100, 'Name must be less than 100 characters'),
  description: z.string().optional(),
  server_spec_id: z.string().min(1, 'Server ID is required'),
})

export async function createMCPInstance(
  serverId: string,
  envSchema: { [key: string]: unknown }[],
  prevState: CreateMCPInstanceState,
  formData: FormData
): Promise<CreateMCPInstanceState> {
  try {
    // Extract form data
    const rawFormData = {
      name: formData.get('name'),
      description: formData.get('description'),
      server_spec_id: serverId,
    }

    // Validate basic form fields
    const validatedFields = createMCPInstanceSchema.safeParse(rawFormData)

    if (!validatedFields.success) {
      return {
        errors: validatedFields.error.flatten().fieldErrors,
        message: 'Please fix the validation errors below.',
      }
    }

    // Extract and validate environment variables
    const envVars: Record<string, string> = {}
    const envErrors: Record<string, string[]> = {}

    // Process each environment variable from the schema
    for (const envField of envSchema) {
      if (typeof envField === 'object' && envField !== null && 'name' in envField) {
        const fieldName = envField.name as string
        const isRequired = (envField.required as boolean) || false
        const value = formData.get(`env_${fieldName}`) as string

        if (isRequired && (!value || value.trim() === '')) {
          envErrors[`env_${fieldName}`] = [`${fieldName} is required`]
        } else if (value) {
          envVars[fieldName] = value.trim()
        }
      }
    }

    // Check for environment variable validation errors
    if (Object.keys(envErrors).length > 0) {
      return {
        errors: envErrors,
        message: 'Please fix the environment variable errors below.',
      }
    }

    // Create the instance payload
    const instanceData: components["schemas"]["MCPServerInstanceCreateRequest"] = {
      name: validatedFields.data.name,
      description: validatedFields.data.description || null,
      server_spec_id: validatedFields.data.server_spec_id,
      json_spec: {
        env_vars: envVars
      }
    }

    // Call the API
    const response = await createMCPServerInstance(instanceData)

    if (response.error) {
      console.error('API Error:', response.error)
      return {
        errors: { _form: ['Failed to create MCP instance. Please try again.'] },
        message: 'An error occurred while creating the instance.',
      }
    }

    if (response.data) {
      // Revalidate the cache
      revalidatePath('/mcp-server-instances')
      revalidatePath('/mcp-servers')
      
      // Return success state with redirect information
      return {
        message: 'Instance created successfully! Redirecting...',
        success: true,
        redirect: '/mcp-server-instances'
      }
    }

    return {
      message: 'Instance created successfully!',
      success: true,
    }

  } catch (error) {
    console.error('Unexpected error:', error)
    return {
      errors: { _form: ['An unexpected error occurred. Please try again.'] },
      message: 'Failed to create MCP instance.',
    }
  }
} 