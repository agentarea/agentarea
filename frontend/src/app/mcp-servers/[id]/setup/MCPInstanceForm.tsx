"use client";

import { useActionState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Textarea } from '@/components/ui/textarea';
import type { components } from '@/api/schema';
import { createMCPInstance, type CreateMCPInstanceState } from './actions';

type MCPServer = components["schemas"]["MCPServerResponse"];

interface EnvSchemaField {
  name: string;
  description?: string;
  required?: boolean;
  default?: string;
  type?: string;
}

// Type guard to check if an unknown object has the expected env schema field structure
function isEnvSchemaField(obj: unknown): obj is EnvSchemaField {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'name' in obj &&
    typeof (obj as Record<string, unknown>).name === 'string'
  );
}

// Safe conversion function for env schema
function convertToEnvSchemaFields(envSchema: { [key: string]: unknown }[]): EnvSchemaField[] {
  const validFields: EnvSchemaField[] = [];
  
  envSchema.forEach((field) => {
    if (isEnvSchemaField(field)) {
      validFields.push({
        name: field.name,
        description: field.description,
        required: field.required,
        default: field.default,
        type: field.type
      });
    }
  });
  
  return validFields;
}

interface MCPInstanceFormProps {
  server: MCPServer;
}

const initialState: CreateMCPInstanceState = {
  message: undefined,
  errors: {},
}

export default function MCPInstanceForm({ server }: MCPInstanceFormProps) {
  const router = useRouter();
  
  // Bind the server action with the server ID and env schema
  const createMCPInstanceWithServer = createMCPInstance.bind(null, server.id, server.env_schema);
  
  // Use the useActionState hook for form handling
  const [state, formAction, pending] = useActionState(createMCPInstanceWithServer, initialState);
  
  // Handle redirect when success with redirect URL
  useEffect(() => {
    if (state?.success && state?.redirect) {
      const timer = setTimeout(() => {
        router.push(state.redirect!);
      }, 1500); // Give user time to see the success message
      
      return () => clearTimeout(timer);
    }
  }, [state?.success, state?.redirect, router]);
  
  // Convert environment schema to typed fields
  const envSchemaFields = convertToEnvSchemaFields(server.env_schema);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create {server.name} Instance</CardTitle>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-6">
          {/* Show general form errors */}
          {state?.errors?._form && (
            <Alert variant="destructive">
              <AlertDescription>
                {state.errors._form.join(', ')}
              </AlertDescription>
            </Alert>
          )}

          {/* Show general message */}
          {state?.message && !state?.errors?._form && (
            <Alert variant={state.success ? "default" : "destructive"}>
              <AlertDescription>{state.message}</AlertDescription>
            </Alert>
          )}

          {/* Basic Information */}
          <div className="space-y-4">
            <div>
              <Label htmlFor="name">Instance Name *</Label>
              <Input
                id="name"
                name="name"
                placeholder="Enter instance name"
                required
                className={state?.errors?.name ? 'border-red-500' : ''}
              />
              {state?.errors?.name && (
                <Alert variant="destructive" className="mt-2">
                  <AlertDescription>{state.errors.name.join(', ')}</AlertDescription>
                </Alert>
              )}
            </div>

            <div>
              <Label htmlFor="description">Description (Optional)</Label>
              <Textarea
                id="description"
                name="description"
                placeholder="Enter instance description"
                rows={3}
              />
            </div>
          </div>

          {/* Server Information */}
          <div className="space-y-2 p-4 bg-gray-50 rounded-lg">
            <h3 className="font-medium text-gray-900">Server: {server.name}</h3>
            <p className="text-sm text-gray-600">{server.description}</p>
          </div>

          {/* Environment Variables */}
          {envSchemaFields.length > 0 && (
            <div className="space-y-4 border rounded-lg p-4 bg-gray-50">
              <h3 className="font-medium text-gray-900">Server Configuration</h3>
              
              <div>
                <Label>Environment Variables</Label>
                <div className="space-y-3 mt-2">
                  {envSchemaFields.map((field, index) => {
                    const fieldName = field.name;
                    const fieldDescription = field.description || '';
                    const isRequired = field.required || false;
                    const isPasswordField = fieldName.toLowerCase().includes('password') || 
                                          fieldName.toLowerCase().includes('secret') || 
                                          fieldName.toLowerCase().includes('key') ||
                                          fieldName.toLowerCase().includes('token');
                    
                    return (
                      <div key={`${fieldName}_${index}`}>
                        <Label htmlFor={`env_${fieldName}`}>
                          {fieldName}
                          {isRequired && <span className="text-red-500 ml-1">*</span>}
                        </Label>
                        <Input
                          id={`env_${fieldName}`}
                          name={`env_${fieldName}`}
                          type={isPasswordField ? 'password' : 'text'}
                          defaultValue={field.default || ''}
                          placeholder={fieldDescription || `Enter ${fieldName}`}
                          required={isRequired}
                          className={state?.errors?.[`env_${fieldName}`] ? 'border-red-500' : ''}
                        />
                        {fieldDescription && (
                          <p className="text-sm text-gray-500 mt-1">{fieldDescription}</p>
                        )}
                        {state?.errors?.[`env_${fieldName}`] && (
                          <Alert variant="destructive" className="mt-2">
                            <AlertDescription>
                              {state.errors[`env_${fieldName}`].join(', ')}
                            </AlertDescription>
                          </Alert>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Submit Button */}
          <Button type="submit" disabled={pending} className="w-full">
            {pending ? 'Creating Instance...' : 'Create Instance'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
} 