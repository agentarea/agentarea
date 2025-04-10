"use client";

import React, { useState, useRef, useEffect } from "react";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Bot, Send, User, Zap, Code, Settings, Sparkles, Loader2, Database, Activity, ChevronDown, Clock } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

// Message types
type MessageType = "user" | "agent" | "system";
type AgentType = "system" | "event" | "background" | "specific";

interface Tool {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
}

// Updated Agent interface to better reflect the implementation of a specification
interface Agent {
  id: string;
  name: string;
  description: string;
  type: AgentType;
  avatar?: string;
  status: "online" | "offline" | "busy";
  tools: string[]; // Tool IDs that this agent can use
  lastActive?: Date;
  metrics?: {
    tasksCompleted: number;
    uptime: string;
    successRate: number;
  };
  // New fields to better represent an agent as an implementation of a specification
  specId: string; // ID of the specification this agent implements
  specVersion: string; // Version of the specification
  instanceId: string; // Unique instance ID for this running agent
  events: AgentEvent[]; // Flow of events for this agent
}

// New interface for agent events
interface AgentEvent {
  id: string;
  timestamp: Date;
  type: "start" | "stop" | "error" | "action" | "message" | "tool_use";
  description: string;
  details?: Record<string, unknown>; // Replace 'any' with a more specific type
}

// Track conversation history by agent
interface ConversationHistory {
  agentId: string;
  messages: Message[];
}

interface Message {
  id: string;
  content: string;
  type: MessageType;
  timestamp: Date;
  tools?: Tool[];
  thinking?: boolean;
  agentId?: string;
  executionFlow?: ExecutionStep[]; // Add execution flow to messages
}

// New interface for execution steps
interface ExecutionStep {
  id: string;
  description: string;
  toolsRequired: string[]; // Tool IDs required for this step
  estimatedTime?: string; // Optional estimated time to complete
  status: "pending" | "in-progress" | "completed" | "failed";
}

// Sample tools
const availableTools: Tool[] = [
  {
    id: "search",
    name: "Web Search",
    description: "Search the web for information",
    icon: <Zap className="h-4 w-4" />,
  },
  {
    id: "code",
    name: "Code Execution",
    description: "Execute code in a sandbox environment",
    icon: <Code className="h-4 w-4" />,
  },
  {
    id: "settings",
    name: "Settings Manager",
    description: "Manage agent settings and configurations",
    icon: <Settings className="h-4 w-4" />,
  },
  {
    id: "database",
    name: "Database Query",
    description: "Query databases and retrieve information",
    icon: <Database className="h-4 w-4" />,
  },
  {
    id: "monitor",
    name: "System Monitor",
    description: "Monitor system metrics and performance",
    icon: <Activity className="h-4 w-4" />,
  },
];

// Sample agents with updated fields
const availableAgents: Agent[] = [
  {
    id: "system",
    name: "AgentMesh System",
    description: "Main system agent that can orchestrate other agents and perform system-wide operations",
    type: "system",
    status: "online",
    tools: ["search", "code", "settings", "database", "monitor"],
    specId: "system-agent-spec",
    specVersion: "1.0.0",
    instanceId: "system-1",
    events: [
      {
        id: "evt-001",
        timestamp: new Date(Date.now() - 5 * 60000),
        type: "start",
        description: "Agent started"
      },
      {
        id: "evt-002",
        timestamp: new Date(Date.now() - 4 * 60000),
        type: "action",
        description: "Initialized system resources"
      }
    ]
  },
  {
    id: "inventory",
    name: "Inventory Monitor",
    description: "Event-based agent that monitors inventory levels and alerts on low stock",
    type: "event",
    status: "online",
    tools: ["database", "monitor"],
    specId: "inventory-monitor-spec",
    specVersion: "1.2.0",
    instanceId: "inventory-1",
    events: [
      {
        id: "evt-101",
        timestamp: new Date(Date.now() - 30 * 60000),
        type: "start",
        description: "Agent started"
      },
      {
        id: "evt-102",
        timestamp: new Date(Date.now() - 10 * 60000),
        type: "action",
        description: "Alert: Low stock detected for SKU-123"
      }
    ]
  },
  {
    id: "support",
    name: "Customer Support",
    description: "Background agent that processes support tickets and provides responses",
    type: "background",
    status: "online",
    tools: ["search", "database"],
    specId: "support-agent-spec",
    specVersion: "0.9.5",
    instanceId: "support-2",
    events: [
      {
        id: "evt-201",
        timestamp: new Date(Date.now() - 120 * 60000),
        type: "start",
        description: "Agent started"
      },
      {
        id: "evt-202",
        timestamp: new Date(Date.now() - 60 * 60000),
        type: "action",
        description: "Processed 25 support tickets"
      }
    ]
  },
  {
    id: "analytics",
    name: "Analytics Agent",
    description: "Specific agent that analyzes data and generates reports",
    type: "specific",
    status: "offline",
    tools: ["database", "code"],
    specId: "analytics-agent-spec",
    specVersion: "1.1.0",
    instanceId: "analytics-1",
    events: [
      {
        id: "evt-301",
        timestamp: new Date(Date.now() - 240 * 60000),
        type: "start",
        description: "Agent started"
      },
      {
        id: "evt-302",
        timestamp: new Date(Date.now() - 120 * 60000),
        type: "action",
        description: "Generated daily marketing report"
      },
      {
        id: "evt-303",
        timestamp: new Date(Date.now() - 60 * 60000),
        type: "stop",
        description: "Agent stopped"
      }
    ]
  },
];

export default function ChatPage() {
  const [activeAgent, setActiveAgent] = useState<Agent>(availableAgents[0]);
  const [conversationHistories, setConversationHistories] = useState<ConversationHistory[]>(
    availableAgents.map(agent => ({
      agentId: agent.id,
      messages: agent.id === availableAgents[0].id ? [
        {
          id: "welcome",
          content: `Hello! I'm the ${availableAgents[0].name} assistant. How can I help you today?`,
          type: "agent",
          timestamp: new Date(),
          agentId: availableAgents[0].id,
        }
      ] : []
    }))
  );
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      content: `Hello! I'm the ${availableAgents[0].name} assistant. How can I help you today?`,
      type: "agent",
      timestamp: new Date(),
      agentId: availableAgents[0].id,
    },
  ]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [agentHistory, setAgentHistory] = useState<{agentId: string, action: string, timestamp: Date}[]>([
    { agentId: "inventory", action: "Alert: Low stock detected for SKU-123", timestamp: new Date(Date.now() - 10 * 60000) },
    { agentId: "support", action: "Processed 25 support tickets", timestamp: new Date(Date.now() - 60 * 60000) },
    { agentId: "analytics", action: "Generated daily marketing report", timestamp: new Date(Date.now() - 120 * 60000) },
  ]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Load conversation history when active agent changes
  useEffect(() => {
    if (activeAgent) {
      const agentHistory = conversationHistories.find(h => h.agentId === activeAgent.id);
      
      if (agentHistory && agentHistory.messages.length > 0) {
        setMessages(agentHistory.messages);
      } else {
        // Create a welcome message if no history exists
        const welcomeMessage = {
          id: "welcome",
          content: `Hello! I'm the ${activeAgent.name} assistant. How can I help you today?`,
          type: "agent" as MessageType,
          timestamp: new Date(),
          agentId: activeAgent.id,
        };
        
        setMessages([welcomeMessage]);
        
        // Update conversation histories
        setConversationHistories(prev => {
          const newHistories = [...prev];
          const index = newHistories.findIndex(h => h.agentId === activeAgent.id);
          
          if (index >= 0) {
            newHistories[index].messages = [welcomeMessage];
          } else {
            newHistories.push({
              agentId: activeAgent.id,
              messages: [welcomeMessage]
            });
          }
          
          return newHistories;
        });
      }
      
      // Update agent's last active time - removed unused variable
      availableAgents.forEach(agent => {
        if (agent.id === activeAgent.id) {
          agent.lastActive = new Date();
        }
      });
    }
  // Remove conversationHistories from dependencies to prevent circular updates
  }, [activeAgent]);

  // Save messages to conversation history when they change
  // Use a ref to track if this is an initial render or a message update triggered by the user
  const isInitialRender = useRef(true);
  const prevActiveAgentRef = useRef<string>(activeAgent.id);
  
  useEffect(() => {
    // Skip the first render or when the active agent changes
    if (isInitialRender.current) {
      isInitialRender.current = false;
      return;
    }
    
    // Skip if this update was triggered by switching agents
    if (prevActiveAgentRef.current !== activeAgent.id) {
      prevActiveAgentRef.current = activeAgent.id;
      return;
    }
    
    // Only update conversation history for user-triggered message changes
    if (activeAgent && messages.length > 0) {
      setConversationHistories(prev => {
        const newHistories = [...prev];
        const index = newHistories.findIndex(h => h.agentId === activeAgent.id);
        
        if (index >= 0) {
          newHistories[index].messages = messages;
        } else {
          newHistories.push({
            agentId: activeAgent.id,
            messages
          });
        }
        
        return newHistories;
      });
    }
    
    // Update the previous agent ref
    prevActiveAgentRef.current = activeAgent.id;
  }, [messages, activeAgent]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() === "") return;

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      type: "user",
      timestamp: new Date(),
    };
    
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsThinking(true);

    // Simulate agent response after a delay
    setTimeout(() => {
      const agentMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: "I'm analyzing your task and planning the execution flow...",
        type: "agent",
        timestamp: new Date(),
        thinking: true,
        agentId: activeAgent.id,
      };
      
      setMessages((prev) => [...prev, agentMessage]);
      
      // Get tools that this agent can use
      const agentTools = availableTools.filter(tool => 
        activeAgent.tools.includes(tool.id)
      );
      
      // Simulate task analysis and execution flow planning
      setTimeout(() => {
        // Create a sample execution flow based on the user's input
        // In a real implementation, this would be generated by an AI or based on task analysis
        const executionFlow = generateExecutionFlow(input, agentTools);
        
        // Update the agent message with the execution flow
        setMessages((prev) => 
          prev.map(msg => 
            msg.id === agentMessage.id 
              ? {
                  ...msg,
                  content: `I've analyzed your task and created a proposed execution flow:`,
                  thinking: false,
                  tools: getRequiredTools(executionFlow, agentTools),
                  executionFlow: executionFlow,
                }
              : msg
          )
        );
        setIsThinking(false);
        
        // Add to agent history and events
        const newEvent = {
          id: `evt-${Date.now()}`,
          timestamp: new Date(),
          type: "action" as const,
          description: `Created execution flow for task: "${input.substring(0, 30)}${input.length > 30 ? '...' : ''}"`,
        };
        
        // Update agent events
        setActiveAgent(prev => ({
          ...prev,
          events: [newEvent, ...(prev.events || [])],
          lastActive: new Date()
        }));
        
        // Add to global history for the history tab
        const newHistoryItem = {
          agentId: activeAgent.id,
          action: newEvent.description,
          timestamp: newEvent.timestamp
        };
        
        setAgentHistory(prev => [newHistoryItem, ...prev]);
      }, 2000);
    }, 1000);
  };

  // Helper function to generate execution flow based on user input
  const generateExecutionFlow = (userInput: string, availableTools: Tool[]): ExecutionStep[] => {
    // This is a simplified example - in a real implementation, 
    // this would use AI to analyze the task and create appropriate steps
    
    // Simple keyword matching for demo purposes
    const input = userInput.toLowerCase();
    const steps: ExecutionStep[] = [];
    
    // Get available tool IDs
    const availableToolIds = availableTools.map(tool => tool.id);
    
    // Step 1: Always analyze the task
    if (availableToolIds.includes("search")) {
      steps.push({
        id: `step-${Date.now()}-1`,
        description: "Analyze task requirements and constraints",
        toolsRequired: ["search"],
        estimatedTime: "1-2 minutes",
        status: "pending"
      });
    }
    
    // Add steps based on keywords in the input
    if (input.includes("data") || input.includes("database") || input.includes("query")) {
      if (availableToolIds.includes("database")) {
        steps.push({
          id: `step-${Date.now()}-2`,
          description: "Query relevant databases for required information",
          toolsRequired: ["database"],
          estimatedTime: "2-3 minutes",
          status: "pending"
        });
      }
    }
    
    if (input.includes("code") || input.includes("script") || input.includes("program")) {
      if (availableToolIds.includes("code")) {
        steps.push({
          id: `step-${Date.now()}-3`,
          description: "Generate and execute code to process the task",
          toolsRequired: ["code"],
          estimatedTime: "3-5 minutes",
          status: "pending"
        });
      }
    }
    
    if (input.includes("monitor") || input.includes("track") || input.includes("performance")) {
      if (availableToolIds.includes("monitor")) {
        steps.push({
          id: `step-${Date.now()}-4`,
          description: "Monitor system performance during execution",
          toolsRequired: ["monitor"],
          estimatedTime: "ongoing",
          status: "pending"
        });
      }
    }
    
    if (input.includes("settings") || input.includes("config") || input.includes("configure")) {
      if (availableToolIds.includes("settings")) {
        steps.push({
          id: `step-${Date.now()}-5`,
          description: "Update system configurations as needed",
          toolsRequired: ["settings"],
          estimatedTime: "1-2 minutes",
          status: "pending"
        });
      }
    }
    
    // If no specific steps were added, add a generic processing step
    if (steps.length === 0 || (steps.length === 1 && availableToolIds.includes("search"))) {
      const genericTools = ["search", "code"].filter(toolId => availableToolIds.includes(toolId));
      if (genericTools.length > 0) {
        steps.push({
          id: `step-${Date.now()}-2`,
          description: "Process the task using available tools",
          toolsRequired: genericTools,
          estimatedTime: "2-4 minutes",
          status: "pending"
        });
      }
    }
    
    // Final step: Always provide a summary
    if (availableToolIds.includes("search")) {
      steps.push({
        id: `step-${Date.now()}-${steps.length + 1}`,
        description: "Generate summary report of task execution",
        toolsRequired: ["search"],
        estimatedTime: "1 minute",
        status: "pending"
      });
    }
    
    // If no steps were created (unlikely), add a fallback step
    if (steps.length === 0) {
      steps.push({
        id: `step-${Date.now()}-1`,
        description: "Process task with available system resources",
        toolsRequired: [],
        estimatedTime: "Unknown",
        status: "pending"
      });
    }
    
    return steps;
  };

  // Helper function to get all required tools for an execution flow
  const getRequiredTools = (executionFlow: ExecutionStep[], availableTools: Tool[]): Tool[] => {
    // Get unique tool IDs from all steps
    const uniqueToolIds = Array.from(new Set(
      executionFlow.flatMap(step => step.toolsRequired)
    ));
    
    // Return the actual tool objects
    return availableTools.filter(tool => uniqueToolIds.includes(tool.id));
  };

  // Get agent by ID
  const getAgentById = (id: string): Agent | undefined => {
    return availableAgents.find(agent => agent.id === id);
  };

  // Get agent icon based on type
  const getAgentIcon = (type: AgentType) => {
    switch (type) {
      case "event":
        return <Activity className="h-4 w-4" />;
      case "background":
        return <Database className="h-4 w-4" />;
      case "specific":
        return <Code className="h-4 w-4" />;
      default:
        return <Bot className="h-4 w-4" />;
    }
  };

  // Get status color
  const getStatusColor = (status: string) => {
    switch (status) {
      case "online":
        return "bg-green-500";
      case "offline":
        return "bg-gray-500";
      case "busy":
        return "bg-yellow-500";
      default:
        return "bg-gray-500";
    }
  };

  // Add this function to handle execution of the flow
  const handleExecuteFlow = (messageId: string, executionFlow: ExecutionStep[]) => {
    // Update the message to show execution has started
    setMessages(prev => 
      prev.map(msg => 
        msg.id === messageId 
          ? {
              ...msg,
              executionFlow: executionFlow.map((step, index) => ({
                ...step,
                status: index === 0 ? "in-progress" : "pending"
              }))
            }
          : msg
      )
    );
    
    // Simulate execution of each step with delays
    let currentStepIndex = 0;
    
    const executeNextStep = () => {
      if (currentStepIndex >= executionFlow.length) {
        // All steps completed
        const completionMessage: Message = {
          id: Date.now().toString(),
          content: "Task execution completed successfully!",
          type: "system",
          timestamp: new Date(),
        };
        
        setMessages(prev => [...prev, completionMessage]);
        return;
      }
      
      // Mark current step as in-progress
      setMessages(prev => 
        prev.map(msg => 
          msg.id === messageId 
            ? {
                ...msg,
                executionFlow: msg.executionFlow!.map((step, index) => ({
                  ...step,
                  status: index < currentStepIndex ? "completed" : 
                           index === currentStepIndex ? "in-progress" : "pending"
                }))
              }
            : msg
        )
      );
      
      // Simulate step execution time (random between 1-3 seconds for demo)
      const executionTime = Math.floor(Math.random() * 2000) + 1000;
      
      setTimeout(() => {
        // Mark current step as completed
        setMessages(prev => 
          prev.map(msg => 
            msg.id === messageId 
              ? {
                  ...msg,
                  executionFlow: msg.executionFlow!.map((step, index) => ({
                    ...step,
                    status: index <= currentStepIndex ? "completed" : 
                             index === currentStepIndex + 1 ? "in-progress" : "pending"
                  }))
                }
              : msg
          )
        );
        
        // Add event for step completion
        const newEvent = {
          id: `evt-${Date.now()}`,
          timestamp: new Date(),
          type: "action" as const,
          description: `Completed execution step: "${executionFlow[currentStepIndex].description}"`,
        };
        
        // Update agent events
        setActiveAgent(prev => ({
          ...prev,
          events: [newEvent, ...(prev.events || [])],
          lastActive: new Date()
        }));
        
        // Add to global history
        const newHistoryItem = {
          agentId: activeAgent.id,
          action: newEvent.description,
          timestamp: newEvent.timestamp
        };
        
        setAgentHistory(prev => [newHistoryItem, ...prev]);
        
        // Move to next step
        currentStepIndex++;
        executeNextStep();
      }, executionTime);
    };
    
    // Start execution
    executeNextStep();
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] p-4">
      <Card className="flex flex-col h-full border-none shadow-lg">
        <CardHeader className="px-6 py-4 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <Avatar className="h-10 w-10 bg-primary/10">
                <AvatarImage src={activeAgent.avatar} />
                <AvatarFallback>
                  {getAgentIcon(activeAgent.type)}
                </AvatarFallback>
              </Avatar>
              <div>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-xl">{activeAgent.name}</CardTitle>
                  <Badge variant="outline" className="ml-2 text-xs">
                    {activeAgent.type}
                  </Badge>
                </div>
                <div className="flex items-center mt-1">
                  <span className={`h-2 w-2 rounded-full ${getStatusColor(activeAgent.status)} mr-2`}></span>
                  <span className="text-sm text-muted-foreground">{activeAgent.status}</span>
                </div>
              </div>
            </div>
            
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="flex items-center gap-2">
                  <span>Switch Agent</span>
                  <ChevronDown className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[240px]">
                {availableAgents.map((agent) => (
                  <DropdownMenuItem 
                    key={agent.id}
                    onClick={() => setActiveAgent(agent)}
                    className="flex items-center gap-2 py-2 cursor-pointer"
                  >
                    <div className="h-6 w-6 rounded-full bg-primary/10 flex items-center justify-center">
                      {getAgentIcon(agent.type)}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-medium">{agent.name}</p>
                      <p className="text-xs text-muted-foreground truncate">{agent.description}</p>
                    </div>
                    <span className={`h-2 w-2 rounded-full ${getStatusColor(agent.status)}`}></span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </CardHeader>
        
        <CardContent className="flex-1 overflow-y-auto p-6 space-y-4">
          <Tabs defaultValue="chat">
            <TabsList className="grid w-[400px] grid-cols-4 mb-6">
              <TabsTrigger value="chat">Chat</TabsTrigger>
              <TabsTrigger value="tools">Tools</TabsTrigger>
              <TabsTrigger value="running">Instances</TabsTrigger>
              <TabsTrigger value="history">Events</TabsTrigger>
            </TabsList>
            
            <TabsContent value="chat" className="h-full mt-0">
              <div className="space-y-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex ${
                      message.type === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    <div
                      className={`flex max-w-[80%] ${
                        message.type === "user" ? "flex-row-reverse" : "flex-row"
                      }`}
                    >
                      {message.type !== "user" && (
                        <Avatar className="h-8 w-8 mt-1 mx-2">
                          <AvatarFallback>
                            {message.agentId && getAgentById(message.agentId) 
                              ? getAgentIcon(getAgentById(message.agentId)!.type)
                              : <Bot className="h-4 w-4" />
                            }
                          </AvatarFallback>
                        </Avatar>
                      )}
                      
                      <div
                        className={`rounded-lg p-4 ${
                          message.type === "user"
                            ? "bg-primary text-primary-foreground"
                            : message.type === "system"
                            ? "bg-muted text-muted-foreground"
                            : "bg-card border"
                        }`}
                      >
                        <div className="flex flex-col space-y-2">
                          {message.agentId && message.type !== "user" && (
                            <div className="flex items-center mb-1">
                              <span className="text-xs text-muted-foreground">
                                {getAgentById(message.agentId)?.name || "Unknown Agent"}
                              </span>
                            </div>
                          )}
                          
                          <div className="flex items-center">
                            {message.thinking && (
                              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            )}
                            <p>{message.content}</p>
                          </div>
                          
                          {/* Display execution flow if available */}
                          {message.executionFlow && message.executionFlow.length > 0 && (
                            <div className="mt-4 pt-3 border-t">
                              <p className="text-sm font-medium mb-2">Proposed Execution Flow:</p>
                              <div className="space-y-3">
                                {message.executionFlow.map((step, index) => (
                                  <div key={step.id} className="bg-accent/10 rounded-md p-3">
                                    <div className="flex items-start">
                                      <div className="bg-accent/30 rounded-full h-6 w-6 flex items-center justify-center mr-3 mt-0.5 flex-shrink-0">
                                        <span className="text-xs font-medium">{index + 1}</span>
                                      </div>
                                      <div className="flex-1">
                                        <p className="text-sm font-medium">{step.description}</p>
                                        <div className="flex flex-wrap gap-2 mt-2">
                                          <div className="flex items-center text-xs text-muted-foreground">
                                            <Clock className="h-3 w-3 mr-1" />
                                            <span>{step.estimatedTime || "Unknown"}</span>
                                          </div>
                                          <div className="flex items-center text-xs">
                                            <Badge variant="outline" className={
                                              step.status === "completed" ? "bg-green-500/10 text-green-500 border-green-500/20" :
                                              step.status === "in-progress" ? "bg-blue-500/10 text-blue-500 border-blue-500/20" :
                                              step.status === "failed" ? "bg-red-500/10 text-red-500 border-red-500/20" :
                                              "bg-accent/10 text-muted-foreground border-accent/20"
                                            }>
                                              {step.status.charAt(0).toUpperCase() + step.status.slice(1)}
                                            </Badge>
                                          </div>
                                        </div>
                                        {step.toolsRequired && step.toolsRequired.length > 0 && (
                                          <div className="mt-2">
                                            <p className="text-xs text-muted-foreground mb-1">Tools required:</p>
                                            <div className="flex flex-wrap gap-1">
                                              {step.toolsRequired.map(toolId => {
                                                const tool = availableTools.find(t => t.id === toolId);
                                                return tool ? (
                                                  <TooltipProvider key={`${step.id}-${tool.id}`}>
                                                    <Tooltip>
                                                      <TooltipTrigger asChild>
                                                        <Badge variant="secondary" className="flex items-center gap-1 px-2 py-0.5 text-xs">
                                                          {tool.icon}
                                                          <span>{tool.name}</span>
                                                        </Badge>
                                                      </TooltipTrigger>
                                                      <TooltipContent>
                                                        <p>{tool.description}</p>
                                                      </TooltipContent>
                                                    </Tooltip>
                                                  </TooltipProvider>
                                                ) : null;
                                              })}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                              <div className="mt-4 flex justify-end">
                                <Button 
                                  onClick={() => handleExecuteFlow(message.id, message.executionFlow!)}
                                  className="flex items-center gap-2"
                                >
                                  <Zap className="h-4 w-4" />
                                  Execute Flow
                                </Button>
                              </div>
                            </div>
                          )}
                          
                          {message.tools && message.tools.length > 0 && (
                            <div className="mt-2 pt-2 border-t">
                              <p className="text-sm text-muted-foreground mb-2">Tools used:</p>
                              <div className="flex flex-wrap gap-2">
                                {message.tools.map((tool) => (
                                  <TooltipProvider key={tool.id}>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <Badge variant="outline" className="flex items-center gap-1 px-2 py-1">
                                          {tool.icon}
                                          <span>{tool.name}</span>
                                        </Badge>
                                      </TooltipTrigger>
                                      <TooltipContent>
                                        <p>{tool.description}</p>
                                      </TooltipContent>
                                    </Tooltip>
                                  </TooltipProvider>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                      
                      {message.type === "user" && (
                        <Avatar className="h-8 w-8 mt-1 mx-2">
                          <AvatarFallback>
                            <User className="h-4 w-4" />
                          </AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            </TabsContent>
            
            <TabsContent value="tools" className="h-full mt-0">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-medium">Available Tools for {activeAgent.name}</h3>
                  <Badge variant="outline">{activeAgent.tools.length} tools</Badge>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {availableTools
                    .filter(tool => activeAgent.tools.includes(tool.id))
                    .map((tool) => (
                      <Card key={tool.id} className="p-4 hover:bg-accent/50 transition-colors cursor-pointer">
                        <div className="flex items-start space-x-3">
                          <div className="h-8 w-8 rounded-md bg-primary/10 flex items-center justify-center">
                            {tool.icon}
                          </div>
                          <div>
                            <h4 className="font-medium">{tool.name}</h4>
                            <p className="text-sm text-muted-foreground">{tool.description}</p>
                          </div>
                        </div>
                      </Card>
                    ))}
                </div>
                
                <div className="mt-8">
                  <h3 className="text-lg font-medium mb-4">Recent Tool Usage</h3>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between p-3 rounded-md bg-accent/50">
                      <div className="flex items-center space-x-3">
                        <Zap className="h-4 w-4 text-primary" />
                        <span>Web Search</span>
                      </div>
                      <span className="text-xs text-muted-foreground">2 minutes ago</span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-md bg-accent/50">
                      <div className="flex items-center space-x-3">
                        <Code className="h-4 w-4 text-primary" />
                        <span>Code Execution</span>
                      </div>
                      <span className="text-xs text-muted-foreground">5 minutes ago</span>
                    </div>
                  </div>
                </div>
                
                <div className="mt-8">
                  <h3 className="text-lg font-medium mb-4">Agent Information</h3>
                  <Card className="p-4">
                    <div className="space-y-3">
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">Agent Type</p>
                        <p>{activeAgent.type}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">Description</p>
                        <p className="text-sm">{activeAgent.description}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-muted-foreground">Status</p>
                        <div className="flex items-center">
                          <span className={`h-2 w-2 rounded-full ${getStatusColor(activeAgent.status)} mr-2`}></span>
                          <span>{activeAgent.status}</span>
                        </div>
                      </div>
                    </div>
                  </Card>
                </div>
              </div>
            </TabsContent>
            
            <TabsContent value="running" className="h-full mt-0">
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-medium">Running Agent Instances</h3>
                  <div className="flex gap-2">
                    <Badge variant="outline">
                      {availableAgents.filter(a => a.status === "online").length} active
                    </Badge>
                    <Button variant="outline" size="sm" className="flex items-center gap-1">
                      <span>View All</span>
                      <ChevronDown className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {availableAgents
                    .filter(agent => agent.status === "online" || agent.status === "busy")
                    .map((agent) => (
                      <Card key={agent.id} className="overflow-hidden">
                        <div className={`h-1.5 ${agent.status === "busy" ? "bg-yellow-500" : "bg-green-500"}`}></div>
                        <div className="p-4">
                          <div className="flex items-start justify-between">
                            <div className="flex items-start space-x-3">
                              <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center">
                                {getAgentIcon(agent.type)}
                              </div>
                              <div>
                                <h4 className="font-medium">{agent.name}</h4>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className={`h-2 w-2 rounded-full ${getStatusColor(agent.status)} mr-1`}></span>
                                  <span className="text-xs text-muted-foreground">{agent.status}</span>
                                  <span className="text-xs text-muted-foreground">|</span>
                                  <span className="text-xs text-muted-foreground">Instance: {agent.instanceId}</span>
                                </div>
                              </div>
                            </div>
                            <Button 
                              variant="ghost" 
                              size="sm"
                              onClick={() => setActiveAgent(agent)}
                            >
                              Connect
                            </Button>
                          </div>
                          
                          <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                            <div className="bg-accent/50 rounded-md p-2">
                              <p className="text-xs text-muted-foreground">Uptime</p>
                              <p className="font-medium">{agent.metrics?.uptime || "2h 45m"}</p>
                            </div>
                            <div className="bg-accent/50 rounded-md p-2">
                              <p className="text-xs text-muted-foreground">Tasks</p>
                              <p className="font-medium">{agent.metrics?.tasksCompleted || "24"}</p>
                            </div>
                            <div className="bg-accent/50 rounded-md p-2">
                              <p className="text-xs text-muted-foreground">Success</p>
                              <p className="font-medium">{agent.metrics?.successRate || "98%"}</p>
                            </div>
                          </div>
                          
                          <div className="mt-4">
                            <div className="flex items-center justify-between">
                              <p className="text-xs text-muted-foreground">Specification</p>
                              <Badge variant="outline" className="text-xs">{agent.specVersion}</Badge>
                            </div>
                            <p className="text-sm mt-1">{agent.specId}</p>
                          </div>
                          
                          <div className="mt-4">
                            <p className="text-xs text-muted-foreground">Latest Event</p>
                            {agent.events && agent.events.length > 0 ? (
                              <div className="flex items-center justify-between mt-1 text-sm">
                                <span>{agent.events[0].description}</span>
                                <span className="text-xs text-muted-foreground">
                                  {formatTimeAgo(agent.events[0].timestamp)}
                                </span>
                              </div>
                            ) : (
                              <p className="text-sm mt-1">No events recorded</p>
                            )}
                          </div>
                        </div>
                      </Card>
                    ))}
                </div>
                
                <div className="mt-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-medium mb-4">Offline Instances</h3>
                    <Button variant="outline" size="sm">Launch New Instance</Button>
                  </div>
                  <div className="space-y-2">
                    {availableAgents
                      .filter(agent => agent.status === "offline")
                      .map((agent) => (
                        <div key={agent.id} className="flex items-center justify-between p-3 rounded-md border">
                          <div className="flex items-center space-x-3">
                            <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                              {getAgentIcon(agent.type)}
                            </div>
                            <div>
                              <p className="font-medium">{agent.name}</p>
                              <div className="flex items-center gap-2">
                                <p className="text-xs text-muted-foreground">{agent.instanceId}</p>
                                <span className="text-xs text-muted-foreground">|</span>
                                <p className="text-xs text-muted-foreground">Spec: {agent.specId}</p>
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <Button variant="outline" size="sm">Start</Button>
                            <Button variant="ghost" size="sm">View</Button>
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </TabsContent>
            
            <TabsContent value="history" className="h-full mt-0">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-medium">Agent Event Flow</h3>
                  <div className="flex gap-2">
                    <Badge variant="outline">{agentHistory.length} events</Badge>
                    <Button variant="outline" size="sm">View All Events</Button>
                  </div>
                </div>
                
                {/* Events for the current active agent */}
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="font-medium text-sm">Events for {activeAgent.name}</h4>
                    <Badge variant="secondary">{activeAgent.events?.length || 0} events</Badge>
                  </div>
                  
                  {activeAgent.events && activeAgent.events.length > 0 ? (
                    <div className="relative pl-6 border-l-2 border-accent space-y-4">
                      {activeAgent.events.map((event) => (
                        <div key={event.id} className="relative">
                          <div className="absolute -left-[25px] h-4 w-4 rounded-full bg-background border-2 border-accent"></div>
                          <div className="bg-accent/20 rounded-md p-3">
                            <div className="flex items-center justify-between">
                              <Badge variant="outline" className="capitalize">{event.type}</Badge>
                              <span className="text-xs text-muted-foreground">
                                {formatTimeAgo(event.timestamp)}
                              </span>
                            </div>
                            <p className="mt-2">{event.description}</p>
                            {event.details && (
                              <div className="mt-2 pt-2 border-t text-sm text-muted-foreground">
                                <pre className="text-xs overflow-x-auto">
                                  {JSON.stringify(event.details, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">No events recorded for this agent</p>
                  )}
                </div>
                
                {/* System-wide event history */}
                <div>
                  <h4 className="font-medium text-sm mb-3">System-wide Event History</h4>
                  <div className="space-y-2">
                    {agentHistory.map((item, index) => {
                      const agent = getAgentById(item.agentId);
                      return (
                        <div key={index} className="flex items-start space-x-3 p-3 rounded-md border">
                          <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center mt-1">
                            {agent ? getAgentIcon(agent.type) : <Bot className="h-4 w-4" />}
                          </div>
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <p className="font-medium">{agent?.name || "Unknown Agent"}</p>
                                <Badge variant="outline" className="text-xs">{agent?.instanceId || "unknown"}</Badge>
                              </div>
                              <span className="text-xs text-muted-foreground">
                                {formatTimeAgo(item.timestamp)}
                              </span>
                            </div>
                            <p className="text-sm text-muted-foreground mt-1">{item.action}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
        
        <CardFooter className="p-4 border-t">
          <form onSubmit={handleSend} className="flex w-full items-center space-x-2">
            <Input
              ref={inputRef}
              type="text"
              placeholder={`Message ${activeAgent.name}...`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              className="flex-1"
              disabled={isThinking || activeAgent.status === "offline"}
            />
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button 
                    type="submit" 
                    size="icon" 
                    disabled={isThinking || input.trim() === "" || activeAgent.status === "offline"}
                  >
                    {isThinking ? (
                      <Loader2 className="h-5 w-5 animate-spin" />
                    ) : (
                      <Send className="h-5 w-5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Send message</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button 
                    variant="outline" 
                    size="icon"
                    disabled={activeAgent.status === "offline"}
                  >
                    <Sparkles className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Use AI suggestions</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </form>
        </CardFooter>
      </Card>
    </div>
  );
}

// Helper function to format time ago
function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  
  if (diffInSeconds < 60) {
    return `${diffInSeconds} seconds ago`;
  }
  
  const diffInMinutes = Math.floor(diffInSeconds / 60);
  if (diffInMinutes < 60) {
    return `${diffInMinutes} minute${diffInMinutes > 1 ? 's' : ''} ago`;
  }
  
  const diffInHours = Math.floor(diffInMinutes / 60);
  if (diffInHours < 24) {
    return `${diffInHours} hour${diffInHours > 1 ? 's' : ''} ago`;
  }
  
  const diffInDays = Math.floor(diffInHours / 24);
  return `${diffInDays} day${diffInDays > 1 ? 's' : ''} ago`;
} 