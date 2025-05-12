'use client';

import { useFormState, useFormStatus } from 'react-dom';
import { useForm, Controller, useFieldArray } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { CardContent, CardFooter } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { PlusCircle, X } from 'lucide-react';
import { addExternalMCPServer, AddExternalMCPServerFormState } from './external-actions';

// Define the schema for client-side validation
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
  isPublic: z.boolean().default(true),
});

type FormData = z.infer<typeof ExternalMCPServerSchema>;

const initialState: AddExternalMCPServerFormState = {
  message: '',
  errors: {},
  fieldValues: {
    name: '',
    description: '',
    endpointUrl: '',
    headers: [],
    tags: [],
    isPublic: true,
  },
};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" className="w-full" disabled={pending}>
      {pending ? 'Adding...' : 'Add External Server'}
    </Button>
  );
}

export function AddExternalMCPServerForm() {
  const [state, formAction] = useFormState(addExternalMCPServer, initialState);

  const {
    register,
    control,
    formState: { errors },
    setValue,
    watch,
  } = useForm<FormData>({
    resolver: zodResolver(ExternalMCPServerSchema),
    defaultValues: {
      ...initialState.fieldValues,
      headers: [],
    },
  });

  const { fields, append, remove } = useFieldArray({
    control,
    name: 'headers',
  });

  // Update form with values returned from server action (e.g., on validation error)
  useEffect(() => {
    if (state.fieldValues) {
      Object.entries(state.fieldValues).forEach(([key, value]) => {
        if (key in ExternalMCPServerSchema.shape) {
          setValue(key as keyof FormData, value as any);
        }
      });
    }
  }, [state, setValue]);

  // Combine react-hook-form errors and server action errors
  const combinedErrors = {
    ...errors,
    ...state.errors,
  };

  const getErrorMessage = (error: string | string[] | { message?: string } | undefined) => {
    if (typeof error === 'string') return error;
    if (Array.isArray(error)) return error[0];
    return error?.message;
  };

  return (
    <form action={formAction}>
      <CardContent className="space-y-4">
        {/* Display general form errors */}
        {state.errors?._form && (
          <div className="text-red-500 text-sm">
            {state.errors._form.join(', ')}
          </div>
        )}
        
        <div className="space-y-2">
          <Label htmlFor="name">Server Name</Label>
          <Input
            id="name"
            {...register('name')}
            placeholder="e.g. My External MCP"
            aria-invalid={!!combinedErrors.name}
          />
          {combinedErrors.name && (
            <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.name)}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            {...register('description')}
            placeholder="Describe what this external MCP server does"
            rows={3}
            aria-invalid={!!combinedErrors.description}
          />
          {combinedErrors.description && (
            <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.description)}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="endpointUrl">Endpoint URL</Label>
          <Input
            id="endpointUrl"
            {...register('endpointUrl')}
            placeholder="e.g. https://my-mcp-server.example.com"
            aria-invalid={!!combinedErrors.endpointUrl}
          />
          {combinedErrors.endpointUrl && (
            <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.endpointUrl)}</p>
          )}
          <p className="text-sm text-muted-foreground">
            Enter the full URL to an external Model Context Protocol server
          </p>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Authentication Headers</Label>
            <Button 
              type="button" 
              variant="outline" 
              size="sm"
              onClick={() => append({ key: '', value: '' })}
              className="h-8"
            >
              <PlusCircle className="mr-2 h-4 w-4" />
              Add Header
            </Button>
          </div>
          {fields.map((field, index) => (
            <div key={field.id} className="flex space-x-2">
              <div className="flex-1">
                <Input
                  {...register(`headers.${index}.key`)}
                  placeholder="Header name"
                  className="mb-1"
                />
                {combinedErrors.headers?.[index]?.key && (
                  <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.headers?.[index]?.key)}</p>
                )}
              </div>
              <div className="flex-1">
                <Input
                  {...register(`headers.${index}.value`)}
                  placeholder="Header value"
                  className="mb-1"
                />
                {combinedErrors.headers?.[index]?.value && (
                  <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.headers?.[index]?.value)}</p>
                )}
              </div>
              <Button 
                type="button" 
                variant="ghost" 
                size="icon" 
                onClick={() => remove(index)}
                className="h-10 w-10 flex-shrink-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <p className="text-sm text-muted-foreground">
            Add authentication headers if required by the external MCP server
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="tags">Tags (comma separated)</Label>
          <Input
            id="tags"
            {...register('tags')}
            placeholder="e.g. files, database, web"
          />
        </div>

        <Controller
          control={control}
          name="isPublic"
          render={({ field }) => (
            <div className="flex items-center justify-between pt-4">
              <div className="space-y-0.5">
                <Label htmlFor="public-switch" className="cursor-pointer">Public Server</Label>
                <p className="text-sm text-muted-foreground">
                  Make this MCP server available to other users
                </p>
              </div>
              <Switch
                id="public-switch"
                checked={field.value}
                onCheckedChange={field.onChange}
                aria-invalid={!!combinedErrors.isPublic}
              />
              <input type="hidden" {...register('isPublic')} value={field.value.toString()} />
            </div>
          )}
        />
        {combinedErrors.isPublic && (
          <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.isPublic)}</p>
        )}

        {/* Display success/failure message */}
        {state.message && !state.errors && <p className="text-green-600">{state.message}</p>}
        {state.message && state.errors && <p className="text-red-600">{state.message}</p>}
      </CardContent>
      <CardFooter>
        <SubmitButton />
      </CardFooter>
    </form>
  );
} 