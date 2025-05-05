'use client';

import { useFormState, useFormStatus } from 'react-dom';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { CardContent, CardFooter } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { addMCPServer, AddMCPServerFormState } from './actions';

// Define the schema for client-side validation (can be the same as server-side)
const MCPServerSchema = z.object({
  name: z.string().min(1, 'Server name is required'),
  description: z.string().min(1, 'Description is required'),
  dockerImageUrl: z
    .string()
    .min(1, 'Docker Image URL is required')
    .url('Invalid URL format'),
  tags: z.string().optional(),
  isPublic: z.boolean().default(true),
});

type FormData = z.infer<typeof MCPServerSchema>;

const initialState: AddMCPServerFormState = {
  message: '',
  errors: {},
  fieldValues: {
    name: '',
    description: '',
    dockerImageUrl: '',
    tags: [],
    isPublic: true,
  },
};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" className="w-full" disabled={pending}>
      {pending ? 'Adding...' : 'Add Server'}
    </Button>
  );
}

export function AddMCPServerForm() {
  const [state, formAction] = useFormState(addMCPServer, initialState);

  const {
    register,
    control,
    formState: { errors },
    setValue,
  } = useForm<FormData>({
    resolver: zodResolver(MCPServerSchema),
    defaultValues: initialState.fieldValues,
  });

  // Update form with values returned from server action (e.g., on validation error)
  useEffect(() => {
    if (state.fieldValues) {
      Object.entries(state.fieldValues).forEach(([key, value]) => {
        if (key in MCPServerSchema.shape) {
          setValue(key as keyof FormData, value as string | boolean);
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
            placeholder="e.g. File System MCP"
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
            placeholder="Describe what this MCP server does"
            rows={3}
            aria-invalid={!!combinedErrors.description}
          />
          {combinedErrors.description && (
            <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.description)}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="dockerImageUrl">Docker Image URL</Label>
          <Input
            id="dockerImageUrl"
            {...register('dockerImageUrl')}
            placeholder="e.g. ghcr.io/anthropic/mcp-file-server:latest"
            aria-invalid={!!combinedErrors.dockerImageUrl}
          />
          {combinedErrors.dockerImageUrl && (
            <p className="text-sm text-red-500">{getErrorMessage(combinedErrors.dockerImageUrl)}</p>
          )}
          <p className="text-sm text-muted-foreground">
            Enter the full URL to a Docker image that implements the Model
            Context Protocol. The image should expose port 8999.
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