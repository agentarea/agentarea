"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

interface FormData {
  name: string;
  description: string;
  tags: string;
  dockerImageUrl: string;
  isPublic: boolean;
}

export default function AddMCPServerPage() {
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    tags: "",
    dockerImageUrl: "",
    isPublic: true,
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSwitchChange = (checked: boolean) => {
    setFormData((prev) => ({ ...prev, isPublic: checked }));
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    console.log("Form data submitted:", formData);
    // Here you would send the data to your API
    alert("MCP server added successfully! (Demo only)");
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle>Add MCP Server</CardTitle>
          <CardDescription>
            Connect a Docker-based MCP server to your workspace
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Server Name</Label>
              <Input
                id="name"
                name="name"
                placeholder="e.g. File System MCP"
                value={formData.name}
                onChange={handleChange}
                required
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                name="description"
                placeholder="Describe what this MCP server does"
                value={formData.description}
                onChange={handleChange}
                required
                rows={3}
              />
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="dockerImageUrl">Docker Image URL</Label>
              <Input
                id="dockerImageUrl"
                name="dockerImageUrl"
                placeholder="e.g. ghcr.io/anthropic/mcp-file-server:latest"
                value={formData.dockerImageUrl}
                onChange={handleChange}
                required
              />
              <p className="text-sm text-muted-foreground">
                Enter the full URL to a Docker image that implements the Model Context Protocol. 
                The image should expose port 8999.
              </p>
            </div>
            
            <div className="space-y-2">
              <Label htmlFor="tags">Tags (comma separated)</Label>
              <Input
                id="tags"
                name="tags"
                placeholder="e.g. files, database, web"
                value={formData.tags}
                onChange={handleChange}
              />
            </div>
            
            <div className="flex items-center justify-between pt-4">
              <div className="space-y-0.5">
                <Label htmlFor="public-switch">Public Server</Label>
                <p className="text-sm text-muted-foreground">
                  Make this MCP server available to other users
                </p>
              </div>
              <Switch
                id="public-switch"
                checked={formData.isPublic}
                onCheckedChange={handleSwitchChange}
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button type="submit" className="w-full">Add Server</Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
} 