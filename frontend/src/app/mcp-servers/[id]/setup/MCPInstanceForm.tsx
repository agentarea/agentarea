"use client";

import { useActionState, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { components } from '@/api/schema';
import { createMCPInstance, type CreateMCPInstanceState } from './actions';
import { MCPInstanceConfigForm } from '@/components/MCPInstanceConfigForm';
import { checkMCPServerInstanceConfiguration, createMCPServerInstance } from '@/lib/api';
import { toast } from 'sonner';

type MCPServer = components["schemas"]["MCPServerResponse"];

interface EnvSchemaField {
  name: string;
  description?: string;
  required?: boolean;
  default?: string;
  type?: string;
}

function isEnvSchemaField(obj: unknown): obj is EnvSchemaField {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'name' in obj &&
    typeof (obj as Record<string, unknown>).name === 'string'
  );
}

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
  const createMCPInstanceWithServer = createMCPInstance.bind(null, server.id, server.env_schema);
  const [state, formAction, pending] = useActionState(createMCPInstanceWithServer, initialState);

  useEffect(() => {
    if (state?.success && state?.redirect) {
      const timer = setTimeout(() => {
        router.push(state.redirect!);
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [state?.success, state?.redirect, router]);

  const envSchemaFields = convertToEnvSchemaFields(server.env_schema);

  const [instanceName, setInstanceName] = useState<string>("");
  const [instanceDescription, setInstanceDescription] = useState<string>("");
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [isChecking, setIsChecking] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors: string[]; warnings: string[] } | null>(null);

  useEffect(() => {
    const initial: Record<string, string> = {};
    envSchemaFields.forEach((f) => {
      initial[f.name] = f.default || "";
    });
    setEnvVars(initial);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create {server.name} Instance</CardTitle>
      </CardHeader>
      <CardContent>
        {state?.errors?._form && (
          <Alert variant="destructive">
            <AlertDescription>
              {state.errors._form.join(', ')}
            </AlertDescription>
          </Alert>
        )}

        {state?.message && !state?.errors?._form && (
          <Alert variant={state.success ? "default" : "destructive"}>
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        )}

        <MCPInstanceConfigForm
          formAction={formAction}
          submitLabel={isCreating || pending ? 'Creating Instance...' : 'Create Instance'}
          submitDisabled={isCreating || pending || !instanceName.trim() || (validationResult ? !validationResult.valid : false)}
          server={server}
          instanceName={instanceName}
          instanceDescription={instanceDescription}
          envVars={envVars}
          onChangeName={(v) => { setInstanceName(v); if (validationResult) setValidationResult(null); }}
          onChangeDescription={setInstanceDescription}
          onChangeEnvVar={(key, value) => { setEnvVars((prev) => ({ ...prev, [key]: value })); if (validationResult) setValidationResult(null); }}
          errors={state?.errors as Record<string, string[] | string | undefined>}
          onValidate={async () => {
            setIsChecking(true);
            try {
              const check = await checkMCPServerInstanceConfiguration({
                json_spec: { image: server.docker_image_url, port: 8000, environment: envVars }
              });
              if (check.error) {
                toast.error('Failed to validate configuration');
              } else {
                setValidationResult(check.data);
                if (check.data.valid) toast.success('Configuration is valid!');
                else toast.warning(`Configuration has ${check.data.errors.length} error(s)`);
              }
            } catch (err) {
              console.error(err);
              toast.error('Validation failed');
            } finally {
              setIsChecking(false);
            }
          }}
          validateDisabled={isChecking || !instanceName.trim()}
          onForceCreate={async () => {
            setIsCreating(true);
            try {
              const res = await createMCPServerInstance({
                name: instanceName,
                description: instanceDescription,
                server_spec_id: server.id,
                json_spec: { image: server.docker_image_url, port: 8000, environment: envVars }
              });
              if (res.error) throw new Error(typeof res.error.detail === 'string' ? res.error.detail : 'Failed to create instance');
              toast.success(`Successfully created ${instanceName}`);
              router.refresh();
            } catch (err: any) {
              console.error(err);
              toast.error(err?.message || 'Failed to create instance');
            } finally {
              setIsCreating(false);
            }
          }}
          forceCreateDisabled={isCreating || !instanceName.trim()}
        />
      </CardContent>
    </Card>
  );
} 