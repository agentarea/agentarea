"use client";
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { createMCPServerInstance } from '@/lib/api';
import type { components } from '@/api/schema';

type MCPServer = components["schemas"]["MCPServerResponse"];

const schema = z.object({
  server_id: z.string().uuid(),
  name: z.string().min(1),
  endpoint_url: z.string().url(),
  config: z.string().optional(), // JSON string
});

type FormData = z.infer<typeof schema>;

export default function MCPInstanceForm({ servers }: { servers: MCPServer[] }) {
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });
  const [message, setMessage] = useState<string | null>(null);

  const onSubmit = async (data: FormData) => {
    setMessage(null);
    let configObj = {};
    if (data.config) {
      try {
        configObj = JSON.parse(data.config);
      } catch {
        setMessage('Config must be valid JSON');
        return;
      }
    }
    const res = await createMCPServerInstance({
      server_id: data.server_id,
      name: data.name,
      endpoint_url: data.endpoint_url,
      config: configObj,
    });
    if (res.error) {
      // Try to extract a useful error message
      let errorMsg = 'Failed to create instance';
      if (typeof res.error === 'string') {
        errorMsg = res.error;
      } else if (res.error.detail && Array.isArray(res.error.detail) && res.error.detail[0]?.msg) {
        errorMsg = res.error.detail[0].msg;
      }
      setMessage(errorMsg);
    } else {
      setMessage('Instance created!');
      reset();
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <Label htmlFor="server_id">MCP Server</Label>
        <select id="server_id" {...register('server_id')} className="w-full border rounded p-2">
          <option value="">Select server</option>
          {servers.map((srv) => (
            <option key={srv.id} value={srv.id}>{srv.name}</option>
          ))}
        </select>
        {errors.server_id && <div className="text-red-500 text-xs">{errors.server_id.message}</div>}
      </div>
      <div>
        <Label htmlFor="name">Instance Name</Label>
        <Input id="name" {...register('name')} />
        {errors.name && <div className="text-red-500 text-xs">{errors.name.message}</div>}
      </div>
      <div>
        <Label htmlFor="endpoint_url">Endpoint URL</Label>
        <Input id="endpoint_url" {...register('endpoint_url')} />
        {errors.endpoint_url && <div className="text-red-500 text-xs">{errors.endpoint_url.message}</div>}
      </div>
      <div>
        <Label htmlFor="config">Config (JSON)</Label>
        <Textarea id="config" {...register('config')} placeholder='{"key": "value"}' rows={3} />
        {errors.config && <div className="text-red-500 text-xs">{errors.config.message}</div>}
      </div>
      {message && <div className={message.includes('created') ? 'text-green-600' : 'text-red-600'}>{message}</div>}
      <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Creating...' : 'Create Instance'}</Button>
    </form>
  );
} 