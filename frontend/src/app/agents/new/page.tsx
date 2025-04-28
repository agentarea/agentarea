import React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default function AddNewAgentPage() {
  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Create New Agent</h1>
      
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Agent Details</CardTitle>
          <CardDescription>
            Define the basic information for your new agent
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium">Agent Name</label>
              <Input placeholder="Enter agent name" />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Agent Goal (Prompt)</label>
              <Textarea 
                placeholder="Describe what this agent should accomplish..."
                className="min-h-[120px]"
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Skills & Capabilities</label>
              <Textarea 
                placeholder="List the skills and capabilities this agent will have..."
                className="min-h-[100px]"
              />
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-sm font-medium">Choose Language Model</label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select LLM" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gpt-4">GPT-4</SelectItem>
                    <SelectItem value="claude-3">Claude 3</SelectItem>
                    <SelectItem value="llama-3">Llama 3</SelectItem>
                    <SelectItem value="mistral-large">Mistral Large</SelectItem>
                    <SelectItem value="custom">Custom Model</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">MCP Integration</label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select MCP Server" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Default MCP</SelectItem>
                    <SelectItem value="custom">Custom MCP Server</SelectItem>
                    <SelectItem value="none">No MCP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Additional Configuration (Optional)</label>
              <Textarea 
                placeholder="Any additional configuration parameters..."
                className="min-h-[80px]"
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-sm font-medium">Tags</label>
              <Input placeholder="Enter tags separated by commas" />
            </div>
          </form>
        </CardContent>
        <CardFooter className="flex justify-between">
          <Button variant="outline">Cancel</Button>
          <Button>Create Agent</Button>
        </CardFooter>
      </Card>
    </div>
  );
} 