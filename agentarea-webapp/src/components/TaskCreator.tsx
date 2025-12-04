"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle, Loader2, Send } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { createTask, getAgents } from "./actions";

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
  const [result, setResult] = useState<{
    success: boolean;
    message: string;
    taskId?: string;
  } | null>(null);

  // Load agents on mount
  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoadingAgents(true);
      const { data: agentsData, error } = await getAgents();

      if (error) {
        console.error("Failed to load agents:", error);
        setResult({ success: false, message: "Failed to load agents" });
      } else {
        const transformedAgents = (agentsData || []).map((agent) => ({
          ...agent,
          description: agent.description || undefined,
          instruction: agent.instruction || undefined,
          model_id: agent.model_id || undefined,
          tools_config: agent.tools_config || undefined,
          events_config: agent.events_config || undefined,
          planning: agent.planning ?? undefined,
        }));
        setAgents(transformedAgents);
        if (transformedAgents.length > 0) {
          setSelectedAgentId(transformedAgents[0].id);
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
      setResult({
        success: false,
        message: "Please select an agent and enter a task description",
      });
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const taskData = {
        description: taskDescription,
        parameters: {
          created_via: "task_creator_ui",
          timestamp: new Date().toISOString(),
        },
        enable_agent_communication: true,
      };

      const { data: task, error } = await createTask(selectedAgentId, taskData);

      if (error) {
        setResult({
          success: false,
          message: `Failed to create task: ${error.detail?.[0]?.msg || "Unknown error"}`,
        });
      } else {
        setResult({
          success: true,
          message: `Task created successfully!`,
        });
        setTaskDescription(""); // Clear the form
      }
    } catch (err) {
      console.error("Error creating task:", err);
      setResult({
        success: false,
        message: `Error creating task: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleViewTask = () => {
    if (result?.taskId) {
      window.open(`/tasks/${result.taskId}`, "_blank");
    }
  };

  const handleViewAllTasks = () => {
    window.open("/tasks", "_blank");
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
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Creating Task...
            </>
          ) : (
            <>
              <Send className="mr-2 h-4 w-4" />
              Create Task
            </>
          )}
        </Button>

        {/* Result Display */}
        {result && (
          <div
            className={`rounded-lg p-4 ${result.success ? "border border-green-200 bg-green-50" : "border border-red-200 bg-red-50"}`}
          >
            <div className="flex items-start gap-2">
              {result.success ? (
                <CheckCircle className="mt-0.5 h-5 w-5 text-green-600" />
              ) : (
                <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs text-white">
                  !
                </div>
              )}
              <div className="flex-1">
                <p
                  className={`text-sm ${result.success ? "text-green-800" : "text-red-800"}`}
                >
                  {result.message}
                </p>
                {result.success && result.taskId && (
                  <div className="mt-3 flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleViewTask}
                    >
                      View Task Details
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleViewAllTasks}
                    >
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
              "Help me with a simple calculation: 15 * 23",
            ].map((example, index) => (
              <Button
                key={index}
                variant="outline"
                size="sm"
                onClick={() => setTaskDescription(example)}
                className="h-auto justify-start px-3 py-2 text-left"
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
