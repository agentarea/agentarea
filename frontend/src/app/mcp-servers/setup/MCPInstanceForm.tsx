"use client";
import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Textarea } from '@/components/ui/textarea';

interface MCPServer {
  id: string;
  name: string;
  description: string;
  env_schema?: Array<{
    name: string;
    type: string;
    required: boolean;
    description?: string;
    default?: string;
  }>;
}

interface MCPInstanceFormProps {
  onSubmit: (data: {
    name: string;
    description?: string;
    server_spec_id?: string;
    json_spec: Record<string, any>;
  }) => void;
  loading?: boolean;
}

export default function MCPInstanceForm({ onSubmit, loading }: MCPInstanceFormProps) {
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    server_spec_id: '',
    json_spec: {} as Record<string, any>
  });
  
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadingServers, setLoadingServers] = useState(false);
  const [isExternalMode, setIsExternalMode] = useState(false);

  useEffect(() => {
    loadServers();
  }, []);

  useEffect(() => {
    if (formData.server_spec_id && servers.length > 0) {
      const server = servers.find(s => s.id === formData.server_spec_id);
      setSelectedServer(server || null);
      setIsExternalMode(false);
      
      // Initialize env_vars in json_spec for managed providers
      if (server) {
        const envVars: Record<string, string> = {};
        server.env_schema?.forEach(field => {
          if (field.default) {
            envVars[field.name] = field.default;
          }
        });
        
        setFormData(prev => ({
          ...prev,
          json_spec: { env_vars: envVars }
        }));
      }
    } else if (formData.server_spec_id === 'external') {
      setSelectedServer(null);
      setIsExternalMode(true);
      setFormData(prev => ({
        ...prev,
        server_spec_id: '',
        json_spec: { endpoint_url: '', headers: {} }
      }));
    } else {
      setSelectedServer(null);
      setIsExternalMode(false);
    }
  }, [formData.server_spec_id, servers]);

  const loadServers = async () => {
    setLoadingServers(true);
    try {
      const response = await fetch('/api/v1/mcp-servers');
      if (response.ok) {
        const data = await response.json();
        setServers(data);
      }
    } catch (error) {
      console.error('Error loading servers:', error);
    } finally {
      setLoadingServers(false);
    }
  };

  const handleEnvVarChange = (name: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      json_spec: {
        ...prev.json_spec,
        env_vars: {
          ...prev.json_spec.env_vars,
          [name]: value
        }
      }
    }));
  };

  const handleExternalConfigChange = (field: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      json_spec: {
        ...prev.json_spec,
        [field]: value
      }
    }));
  };

  const handleHeaderChange = (key: string, value: string) => {
    setFormData(prev => ({
      ...prev,
      json_spec: {
        ...prev.json_spec,
        headers: {
          ...prev.json_spec.headers,
          [key]: value
        }
      }
    }));
  };

  const addHeader = () => {
    const newKey = `header_${Object.keys(formData.json_spec.headers || {}).length + 1}`;
    handleHeaderChange(newKey, '');
  };

  const removeHeader = (key: string) => {
    setFormData(prev => {
      const newHeaders = { ...prev.json_spec.headers };
      delete newHeaders[key];
      return {
        ...prev,
        json_spec: {
          ...prev.json_spec,
          headers: newHeaders
        }
      };
    });
  };

  const validateForm = () => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required';
    }

    if (isExternalMode) {
      if (!formData.json_spec.endpoint_url?.trim()) {
        newErrors.endpoint_url = 'Endpoint URL is required for external providers';
      } else {
        try {
          new URL(formData.json_spec.endpoint_url);
        } catch {
          newErrors.endpoint_url = 'Please enter a valid URL';
        }
      }
    } else if (selectedServer) {
      // Validate required env vars for managed servers
      selectedServer.env_schema?.forEach(field => {
        if (field.required && !formData.json_spec.env_vars?.[field.name]?.trim()) {
          newErrors[`env_${field.name}`] = `${field.name} is required`;
        }
      });
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (validateForm()) {
      onSubmit({
        ...formData,
        server_spec_id: isExternalMode ? undefined : formData.server_spec_id
      });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create MCP Instance</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Basic Information */}
          <div className="space-y-4">
            <div>
              <Label htmlFor="name">Instance Name</Label>
              <Input
                id="name"
                value={formData.name}
                onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                placeholder="Enter instance name"
                className={errors.name ? 'border-red-500' : ''}
              />
              {errors.name && (
                <Alert variant="destructive" className="mt-2">
                  <AlertDescription>{errors.name}</AlertDescription>
                </Alert>
              )}
            </div>

            <div>
              <Label htmlFor="description">Description (Optional)</Label>
              <Textarea
                id="description"
                value={formData.description}
                onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                placeholder="Enter instance description"
                rows={3}
              />
            </div>
          </div>

          {/* Server/Provider Selection */}
          <div>
            <Label htmlFor="server_spec_id">MCP Configuration</Label>
            <Select
              value={isExternalMode ? 'external' : formData.server_spec_id}
              onValueChange={(value) => setFormData(prev => ({ ...prev, server_spec_id: value }))}
              disabled={loadingServers}
            >
              <SelectTrigger>
                <SelectValue placeholder={loadingServers ? "Loading..." : "Select MCP configuration"} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="external">
                  <div>
                    <div className="font-medium">External MCP Server</div>
                    <div className="text-sm text-gray-500">Connect to existing URL</div>
                  </div>
                </SelectItem>
                {servers.map((server) => (
                  <SelectItem key={server.id} value={server.id}>
                    <div>
                      <div className="font-medium">{server.name}</div>
                      <div className="text-sm text-gray-500">{server.description}</div>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Managed Server Configuration */}
          {selectedServer && !isExternalMode && (
            <div className="space-y-4 border rounded-lg p-4 bg-gray-50">
              <h3 className="font-medium text-gray-900">Server Configuration</h3>
              
              {/* Environment Variables */}
              {selectedServer.env_schema && selectedServer.env_schema.length > 0 && (
                <div>
                  <Label>Environment Variables</Label>
                  <div className="space-y-3 mt-2">
                    {selectedServer.env_schema.map((field) => (
                      <div key={field.name}>
                        <Label htmlFor={`env_${field.name}`}>
                          {field.name}
                          {field.required && <span className="text-red-500 ml-1">*</span>}
                        </Label>
                        <Input
                          id={`env_${field.name}`}
                          type={field.name.toLowerCase().includes('password') || field.name.toLowerCase().includes('secret') || field.name.toLowerCase().includes('key') ? 'password' : 'text'}
                          value={formData.json_spec.env_vars?.[field.name] || ''}
                          onChange={(e) => handleEnvVarChange(field.name, e.target.value)}
                          placeholder={field.description || `Enter ${field.name}`}
                          className={errors[`env_${field.name}`] ? 'border-red-500' : ''}
                        />
                        {field.description && (
                          <p className="text-sm text-gray-500 mt-1">{field.description}</p>
                        )}
                        {errors[`env_${field.name}`] && (
                          <Alert variant="destructive" className="mt-2">
                            <AlertDescription>{errors[`env_${field.name}`]}</AlertDescription>
                          </Alert>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* External Configuration */}
          {isExternalMode && (
            <div className="space-y-4 border rounded-lg p-4 bg-blue-50">
              <h3 className="font-medium text-gray-900">External Configuration</h3>
              
              <div>
                <Label htmlFor="endpoint_url">Endpoint URL</Label>
                <Input
                  id="endpoint_url"
                  value={formData.json_spec.endpoint_url || ''}
                  onChange={(e) => handleExternalConfigChange('endpoint_url', e.target.value)}
                  placeholder="https://your-mcp-server.com"
                  className={errors.endpoint_url ? 'border-red-500' : ''}
                />
                {errors.endpoint_url && (
                  <Alert variant="destructive" className="mt-2">
                    <AlertDescription>{errors.endpoint_url}</AlertDescription>
                  </Alert>
                )}
              </div>

              {/* Headers */}
              <div>
                <Label>Headers (Optional)</Label>
                <div className="space-y-2 mt-2">
                  {Object.entries(formData.json_spec.headers || {}).map(([key, value]) => (
                    <div key={key} className="flex gap-2">
                      <Input
                        placeholder="Header name"
                        value={key}
                        onChange={(e) => {
                          const newKey = e.target.value;
                          const oldHeaders = { ...formData.json_spec.headers };
                          delete oldHeaders[key];
                          setFormData(prev => ({
                            ...prev,
                            json_spec: {
                              ...prev.json_spec,
                              headers: { ...oldHeaders, [newKey]: value }
                            }
                          }));
                        }}
                      />
                      <Input
                        placeholder="Header value"
                        value={value as string}
                        onChange={(e) => handleHeaderChange(key, e.target.value)}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => removeHeader(key)}
                      >
                        Remove
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addHeader}
                  >
                    Add Header
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Submit Button */}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? 'Creating...' : 'Create Instance'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
} 