"use client";

import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listAgents, createAgentTask } from "@/lib/api";
import { Loader2, Send, CheckCircle } from "lucide-react";
import { LoadingSpinner } from '@/components/LoadingSpinner';

interface Agent {
  id: string;
  name: string;
  description?: string;
}

export default function TaskCreator() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [taskDescription, setTaskDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [result, setResult] = useState<{ success: boolean; message: string; taskId?: string } | null>(null);

  // Load agents on mount
  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoadingAgents(true);
      const { data: agentsData, error } = await listAgents();
      
      if (error) {
        console.error("Failed to load agents:", error);
        setResult({ success: false, message: "Failed to load agents" });
      } else {
        setAgents(agentsData || []);
        if (agentsData && agentsData.length > 0) {
          setSelectedAgentId(agentsData[0].id);
        }
      }
    } catch (err) {
      console.error("Error loading agents:", err);
      setResult({ success: false, message: "Error loading agents" });
    } finally {
      setLoadingAgents(false);
    }
  };

  const handleCreateTask = async () => {
    if (!selectedAgentId || !taskDescription.trim()) {
      setResult({ success: false, message: "Please select an agent and enter a task description" });
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const taskData = {
        description: taskDescription,
        parameters: {
          created_via: "task_creator_ui",
          timestamp: new Date().toISOString()
        },
        user_id: "ui_test_user",
        enable_agent_communication: true
      };

      const { data: task, error } = await createAgentTask(selectedAgentId, taskData);

      if (error) {
        setResult({ 
          success: false, 
          message: `Failed to create task: ${error.message || 'Unknown error'}` 
        });
      } else {
        setResult({ 
          success: true, 
          message: `Task created successfully! Task ID: ${task?.id}`,
          taskId: task?.id?.toString()
        });
        setTaskDescription(""); // Clear the form
      }
    } catch (err) {
      console.error("Error creating task:", err);
      setResult({ 
        success: false, 
        message: `Error creating task: ${err instanceof Error ? err.message : 'Unknown error'}` 
      });
    } finally {
      setLoading(false);
    }
  };

  const handleViewTask = () => {
    if (result?.taskId) {
      window.open(`/tasks/${result.taskId}`, '_blank');
    }
  };

  const handleViewAllTasks = () => {
    window.open('/tasks', '_blank');
  };

  if (loadingAgents) {
    return (
      <Card className="w-full max-w-2xl">
        <CardContent className="pt-6">
          <LoadingSpinner />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Create Test Task</CardTitle>
        <p className="text-sm text-muted-foreground">
          Send a task to an agent and test the task creation functionality
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Agent Selection */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Select Agent</label>
          <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
            <SelectTrigger>
              <SelectValue placeholder="Choose an agent" />
            </SelectTrigger>
            <SelectContent>
              {agents.map((agent) => (
                <SelectItem key={agent.id} value={agent.id}>
                  {agent.name} {agent.description && `- ${agent.description}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Task Description */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Task Description</label>
          <Textarea
            placeholder="Enter your task description here... (e.g., 'What is the current time?', 'Analyze this data', etc.)"
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            rows={4}
          />
        </div>

        {/* Create Task Button */}
        <Button 
          onClick={handleCreateTask} 
          disabled={loading || !selectedAgentId || !taskDescription.trim()}
          className="w-full"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Creating Task...
            </>
          ) : (
            <>
              <Send className="h-4 w-4 mr-2" />
              Create Task
            </>
          )}
        </Button>

        {/* Result Display */}
        {result && (
          <div className={`p-4 rounded-lg ${result.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
            <div className="flex items-start gap-2">
              {result.success ? (
                <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
              ) : (
                <div className="h-5 w-5 rounded-full bg-red-600 text-white text-xs flex items-center justify-center mt-0.5">!</div>
              )}
              <div className="flex-1">
                <p className={`text-sm ${result.success ? 'text-green-800' : 'text-red-800'}`}>
                  {result.message}
                </p>
                {result.success && result.taskId && (
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" variant="outline" onClick={handleViewTask}>
                      View Task Details
                    </Button>
                    <Button size="sm" variant="outline" onClick={handleViewAllTasks}>
                      View All Tasks
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Quick Test Examples */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Quick Test Examples</label>
          <div className="grid grid-cols-1 gap-2">
            {[
              "What is the current time and date?",
              "Tell me a joke",
              "Explain what you can do",
              "Help me with a simple calculation: 15 * 23"
            ].map((example, index) => (
              <Button
                key={index}
                variant="outline"
                size="sm"
                onClick={() => setTaskDescription(example)}
                className="text-left justify-start h-auto py-2 px-3"
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}