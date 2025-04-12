"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Wrench,
  Plus,
  Trash2,
  Info,
  Save,
  Code,
  FileJson,
  Upload
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface ToolParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

export default function CreateToolSpecPage() {
  const [toolName, setToolName] = useState("");
  const [toolDescription, setToolDescription] = useState("");
  const [parameters, setParameters] = useState<ToolParameter[]>([
    { name: "", type: "string", description: "", required: true }
  ]);
  const [mcpCompatible, setMcpCompatible] = useState(true);
  const [jsonSchema, setJsonSchema] = useState("");
  const [activeTab, setActiveTab] = useState("form");

  const addParameter = () => {
    setParameters([...parameters, { name: "", type: "string", description: "", required: false }]);
  };

  const removeParameter = (index: number) => {
    const newParameters = [...parameters];
    newParameters.splice(index, 1);
    setParameters(newParameters);
  };

  const updateParameter = (index: number, field: keyof ToolParameter, value: string | boolean) => {
    const newParameters = [...parameters];
    newParameters[index] = { ...newParameters[index], [field]: value };
    setParameters(newParameters);
  };

  const generateJsonSchema = () => {
    const schema = {
      name: toolName,
      description: toolDescription,
      parameters: {
        type: "object",
        properties: parameters.reduce((acc, param) => {
          acc[param.name] = {
            type: param.type,
            description: param.description
          };
          return acc;
        }, {} as Record<string, any>),
        required: parameters.filter(p => p.required).map(p => p.name)
      },
      mcpCompatible
    };
    
    setJsonSchema(JSON.stringify(schema, null, 2));
    setActiveTab("json");
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-4xl font-bold">Create Tool Specification</h1>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-5 w-5 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-md">
                  <p>Tool specifications define the interface for tools that can be used by agents. They include parameters, descriptions, and other metadata.</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <p className="text-lg text-muted-foreground mt-2">
            Define a new tool that can be used by agents in your system
          </p>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="form" className="flex items-center gap-2">
            <Wrench className="h-4 w-4" />
            Form Editor
          </TabsTrigger>
          <TabsTrigger value="json" className="flex items-center gap-2">
            <FileJson className="h-4 w-4" />
            JSON Schema
          </TabsTrigger>
          <TabsTrigger value="code" className="flex items-center gap-2">
            <Code className="h-4 w-4" />
            Code Implementation
          </TabsTrigger>
        </TabsList>
        
        <TabsContent value="form">
          <Card className="p-6">
            <div className="space-y-6">
              <div>
                <Label htmlFor="tool-name">Tool Name</Label>
                <Input 
                  id="tool-name"
                  placeholder="e.g., web_search" 
                  value={toolName}
                  onChange={(e) => setToolName(e.target.value)}
                  className="mt-1"
                />
              </div>
              
              <div>
                <Label htmlFor="tool-description">Description</Label>
                <Textarea 
                  id="tool-description"
                  placeholder="Describe what this tool does and when it should be used" 
                  value={toolDescription}
                  onChange={(e) => setToolDescription(e.target.value)}
                  className="mt-1 min-h-24"
                />
              </div>
              
              <div>
                <div className="flex justify-between items-center mb-2">
                  <Label>Parameters</Label>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={addParameter}
                    className="flex items-center gap-1"
                  >
                    <Plus className="h-4 w-4" />
                    Add Parameter
                  </Button>
                </div>
                
                <div className="space-y-4">
                  {parameters.map((param, index) => (
                    <div key={index} className="grid grid-cols-12 gap-4 items-start p-4 border rounded-md">
                      <div className="col-span-3">
                        <Label htmlFor={`param-name-${index}`}>Name</Label>
                        <Input 
                          id={`param-name-${index}`}
                          placeholder="e.g., query" 
                          value={param.name}
                          onChange={(e) => updateParameter(index, "name", e.target.value)}
                          className="mt-1"
                        />
                      </div>
                      
                      <div className="col-span-2">
                        <Label htmlFor={`param-type-${index}`}>Type</Label>
                        <Select 
                          value={param.type} 
                          onValueChange={(value) => updateParameter(index, "type", value)}
                        >
                          <SelectTrigger id={`param-type-${index}`} className="mt-1">
                            <SelectValue placeholder="Type" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="string">String</SelectItem>
                            <SelectItem value="number">Number</SelectItem>
                            <SelectItem value="boolean">Boolean</SelectItem>
                            <SelectItem value="array">Array</SelectItem>
                            <SelectItem value="object">Object</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      
                      <div className="col-span-5">
                        <Label htmlFor={`param-desc-${index}`}>Description</Label>
                        <Input 
                          id={`param-desc-${index}`}
                          placeholder="What this parameter is used for" 
                          value={param.description}
                          onChange={(e) => updateParameter(index, "description", e.target.value)}
                          className="mt-1"
                        />
                      </div>
                      
                      <div className="col-span-1 flex items-end justify-center mt-6">
                        <div className="flex items-center space-x-2">
                          <Switch 
                            id={`param-required-${index}`} 
                            checked={param.required}
                            onCheckedChange={(checked) => updateParameter(index, "required", checked)}
                          />
                          <Label htmlFor={`param-required-${index}`}>Required</Label>
                        </div>
                      </div>
                      
                      <div className="col-span-1 flex items-end justify-center mt-6">
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          onClick={() => removeParameter(index)}
                          disabled={parameters.length === 1}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              
              <div className="flex items-center space-x-2">
                <Switch 
                  id="mcp-compatible" 
                  checked={mcpCompatible}
                  onCheckedChange={setMcpCompatible}
                />
                <Label htmlFor="mcp-compatible">MCP Compatible</Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger>
                      <Info className="h-4 w-4 text-muted-foreground ml-1" />
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Make this tool compatible with the Message Control Protocol (MCP)</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              
              <div className="flex justify-end gap-4">
                <Button variant="outline">Cancel</Button>
                <Button onClick={generateJsonSchema}>Generate Schema</Button>
              </div>
            </div>
          </Card>
        </TabsContent>
        
        <TabsContent value="json">
          <Card className="p-6">
            <div className="space-y-6">
              <div>
                <Label htmlFor="json-schema">JSON Schema</Label>
                <Textarea 
                  id="json-schema"
                  value={jsonSchema}
                  onChange={(e) => setJsonSchema(e.target.value)}
                  className="mt-1 min-h-[400px] font-mono"
                />
              </div>
              
              <div className="flex justify-end gap-4">
                <Button variant="outline" onClick={() => setActiveTab("form")}>Back to Form</Button>
                <Button>Save Tool Specification</Button>
              </div>
            </div>
          </Card>
        </TabsContent>
        
        <TabsContent value="code">
          <Card className="p-6">
            <div className="space-y-6">
              <div>
                <Label htmlFor="code-implementation">Code Implementation</Label>
                <div className="mt-1 p-4 border rounded-md bg-muted">
                  <p className="text-muted-foreground mb-4">Implement your tool using one of the following methods:</p>
                  
                  <div className="space-y-4">
                    <div>
                      <h3 className="text-lg font-medium mb-2">Option 1: Upload Implementation</h3>
                      <Button variant="outline" className="flex items-center gap-2">
                        <Upload className="h-4 w-4" />
                        Upload Code File
                      </Button>
                    </div>
                    
                    <div>
                      <h3 className="text-lg font-medium mb-2">Option 2: Write Implementation</h3>
                      <Textarea 
                        id="code-implementation"
                        placeholder="// Write your tool implementation here"
                        className="min-h-[300px] font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex justify-end gap-4">
                <Button variant="outline" onClick={() => setActiveTab("json")}>Back to Schema</Button>
                <Button className="flex items-center gap-2">
                  <Save className="h-4 w-4" />
                  Save and Publish
                </Button>
              </div>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
} 