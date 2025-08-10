"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  Bot, 
  ArrowLeft, 
  MessageCircle, 
  Settings, 
  Send,
  Zap,
  Plus,
  FileText
} from "lucide-react";
import Link from "next/link";
import { AgentChat } from "@/components/Chat";

interface Agent {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

interface Props {
  agent: Agent;
}

export default function NewTaskClient({ agent }: Props) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("chat");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [taskParameters, setTaskParameters] = useState("{}");
  const [isCreating, setIsCreating] = useState(false);

  const handleTaskCreated = (taskId: string) => {
    // Navigate to the task detail page
    router.push(`/tasks/${taskId}`);
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskDescription.trim() || isCreating) return;

    setIsCreating(true);
    try {
      // Parse parameters
      let parsedParameters = {};
      try {
        parsedParameters = JSON.parse(taskParameters);
      } catch (e) {
        console.warn('Invalid JSON parameters, using empty object');
      }

      // Create task using API
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${baseUrl}/v1/agents/${agent.id}/tasks/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          description: taskDescription,
          parameters: {
            title: taskTitle || taskDescription,
            ...parsedParameters,
            task_type: "form_created",
          },
          user_id: "frontend_user",
          enable_agent_communication: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const task = await response.json();
      
      // Navigate to the created task
      router.push(`/tasks/${task.id}`);
      
    } catch (error) {
      console.error('Failed to create task:', error);
      // You could show an error toast here
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header with navigation */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href={`/agents/${agent.id}`}>
            <Button variant="ghost" size="sm" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back to Agent
            </Button>
          </Link>
          <div className="h-6 w-px bg-border" />
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 bg-gradient-to-br from-primary/20 to-primary/10 rounded-full flex items-center justify-center shadow-sm border border-primary/20">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold">New Task for {agent.name}</h1>
              <div className="flex items-center gap-2">
                <Badge 
                  variant={agent.status === "active" ? "default" : "destructive"}
                  className="gap-1 text-xs"
                >
                  {agent.status === "active" && <Zap className="h-3 w-3" />}
                  {agent.status}
                </Badge>
                {agent.description && (
                  <span className="text-sm text-muted-foreground">
                    {agent.description}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs for different creation modes */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-2 bg-muted/50 p-1 rounded-lg">
          <TabsTrigger 
            value="chat" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <MessageCircle className="h-4 w-4" />
            Chat Mode
          </TabsTrigger>
          <TabsTrigger 
            value="form" 
            className="gap-2 data-[state=active]:bg-background data-[state=active]:shadow-sm transition-all duration-200"
          >
            <FileText className="h-4 w-4" />
            Form Mode
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chat" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Chat Interface */}
            <div className="lg:col-span-2">
              <AgentChat
                agent={agent}
                onTaskCreated={handleTaskCreated}
                className="w-full"
                height="500px"
              />
            </div>

            {/* Quick Actions */}
            <div className="space-y-4">
              <Card className="shadow-sm border-0 bg-gradient-to-br from-background to-muted/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Settings className="h-5 w-5 text-primary" />
                    Chat Tips
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">💡 Be Specific</p>
                    <p className="text-muted-foreground">Provide clear instructions and context for better results.</p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">🔧 Tool Usage</p>
                    <p className="text-muted-foreground">This agent can use various tools to complete your tasks.</p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">⏱️ Real-time</p>
                    <p className="text-muted-foreground">You'll see progress updates as the agent works.</p>
                  </div>
                </CardContent>
              </Card>

              <Card className="shadow-sm border-0 bg-gradient-to-br from-background to-muted/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Plus className="h-5 w-5 text-primary" />
                    Quick Actions
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <Link href={`/agents/${agent.id}`}>
                    <Button variant="outline" className="w-full gap-2 justify-start">
                      <Bot className="h-4 w-4" />
                      View Agent Details
                    </Button>
                  </Link>
                  <Link href="/tasks">
                    <Button variant="outline" className="w-full gap-2 justify-start">
                      <FileText className="h-4 w-4" />
                      View All Tasks
                    </Button>
                  </Link>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="form" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Form Interface */}
            <div className="lg:col-span-2">
              <Card className="shadow-sm border-0 bg-gradient-to-b from-background to-muted/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <FileText className="h-5 w-5 text-primary" />
                    Create Task
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <form onSubmit={handleFormSubmit} className="space-y-6">
                    <div className="space-y-2">
                      <Label htmlFor="title">Task Title (Optional)</Label>
                      <Input
                        id="title"
                        value={taskTitle}
                        onChange={(e) => setTaskTitle(e.target.value)}
                        placeholder="Give your task a descriptive title..."
                        className="transition-colors duration-200"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="description">Task Description *</Label>
                      <Textarea
                        id="description"
                        value={taskDescription}
                        onChange={(e) => setTaskDescription(e.target.value)}
                        placeholder="Describe what you want the agent to do in detail..."
                        className="min-h-[120px] transition-colors duration-200"
                        required
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="parameters">Parameters (JSON, Optional)</Label>
                      <Textarea
                        id="parameters"
                        value={taskParameters}
                        onChange={(e) => setTaskParameters(e.target.value)}
                        placeholder='{"key": "value", "setting": true}'
                        className="font-mono text-sm transition-colors duration-200"
                      />
                      <p className="text-xs text-muted-foreground">
                        Additional parameters to pass to the agent (JSON format)
                      </p>
                    </div>

                    <div className="flex gap-3">
                      <Button 
                        type="submit" 
                        disabled={isCreating || !taskDescription.trim()}
                        className="gap-2 flex-1 shadow-sm hover:shadow-md transition-all duration-200"
                      >
                        {isCreating ? (
                          <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <Send className="h-4 w-4" />
                        )}
                        Create Task
                      </Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            </div>

            {/* Form Help */}
            <div className="space-y-4">
              <Card className="shadow-sm border-0 bg-gradient-to-br from-background to-muted/20">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Settings className="h-5 w-5 text-primary" />
                    Form Tips
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">📝 Description</p>
                    <p className="text-muted-foreground">Be as detailed as possible about what you want accomplished.</p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">⚙️ Parameters</p>
                    <p className="text-muted-foreground">Use JSON format for additional settings and context.</p>
                  </div>
                  <div className="p-3 bg-muted/50 rounded-lg">
                    <p className="font-medium text-primary mb-1">🎯 Goal</p>
                    <p className="text-muted-foreground">Define success criteria and expected outcomes.</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}