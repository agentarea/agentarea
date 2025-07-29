"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { 
  Bot, 
  Send, 
  MessageCircle, 
  Plus,
  Settings,
  User,
  Zap,
  Loader2,
  ArrowRight,
  Sparkles,
  FileText,
  Code,
  Database,
  Globe,
  Palette,
  Search,
  ChevronRight,
  Clock,
  CheckCircle2,
  AlertCircle,
  Briefcase,
  Calculator,
  Mail,
  Calendar,
  PenTool,
  Brain,
  Shield,
  Cpu,
  Network,
  Timer,
  BarChart3,
  Target,
  Lightbulb,
  Filter,
  SortDesc,
  Star,
  Activity,
  TrendingUp,
  Workflow,
  X
} from "lucide-react";
import Link from "next/link";
import { listAgents, sendMessage as sendChatMessage, getChatMessageStatus } from "@/lib/api";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

interface Agent {
  id: string;
  name: string;
  description?: string;
  status: string;
  capabilities?: string[];
  specialization?: string;
  performance_score?: number;
  tasks_completed?: number;
  avg_response_time?: number;
}

interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: string;
  agent_id?: string;
  status?: "sending" | "processing" | "completed" | "failed";
  progress?: number;
}

interface TaskTemplate {
  id: string;
  name: string;
  description: string;
  icon: React.ComponentType<any>;
  category: string;
  prompt: string;
  tags: string[];
  estimatedTime?: string;
  difficulty?: "easy" | "medium" | "hard";
  popular?: boolean;
}

interface QuickAction {
  id: string;
  name: string;
  icon: React.ComponentType<any>;
  prompt: string;
  color: string;
}

// Mock data for task templates
const TASK_TEMPLATES: TaskTemplate[] = [
  {
    id: "write-email",
    name: "Write Email",
    description: "Compose professional emails with proper tone and structure",
    icon: Mail,
    category: "Communication",
    prompt: "Help me write a professional email about: ",
    tags: ["communication", "writing", "business"],
    estimatedTime: "2-3 min",
    difficulty: "easy",
    popular: true
  },
  {
    id: "code-review",
    name: "Code Review",
    description: "Review code for bugs, performance, and best practices",
    icon: Code,
    category: "Development",
    prompt: "Please review this code and provide feedback on: ",
    tags: ["development", "programming", "quality"],
    estimatedTime: "5-10 min",
    difficulty: "medium",
    popular: true
  },
  {
    id: "data-analysis",
    name: "Data Analysis",
    description: "Analyze datasets and generate insights",
    icon: BarChart3,
    category: "Analytics",
    prompt: "Analyze this data and provide insights on: ",
    tags: ["analytics", "data science", "reporting"],
    estimatedTime: "10-15 min",
    difficulty: "hard"
  },
  {
    id: "content-writing",
    name: "Content Writing",
    description: "Create engaging content for blogs, social media, and marketing",
    icon: PenTool,
    category: "Content",
    prompt: "Help me create content about: ",
    tags: ["writing", "marketing", "creative"],
    estimatedTime: "5-8 min",
    difficulty: "medium",
    popular: true
  },
  {
    id: "research",
    name: "Research Task",
    description: "Conduct thorough research on any topic",
    icon: Search,
    category: "Research",
    prompt: "Research and summarize information about: ",
    tags: ["research", "analysis", "information"],
    estimatedTime: "8-12 min",
    difficulty: "medium"
  },
  {
    id: "schedule-planning",
    name: "Schedule Planning",
    description: "Plan schedules, meetings, and project timelines",
    icon: Calendar,
    category: "Planning",
    prompt: "Help me plan a schedule for: ",
    tags: ["planning", "organization", "productivity"],
    estimatedTime: "3-5 min",
    difficulty: "easy"
  },
  {
    id: "problem-solving",
    name: "Problem Solving",
    description: "Break down complex problems and find solutions",
    icon: Lightbulb,
    category: "Strategy",
    prompt: "Help me solve this problem: ",
    tags: ["strategy", "analysis", "solutions"],
    estimatedTime: "10-20 min",
    difficulty: "hard"
  },
  {
    id: "document-summary",
    name: "Document Summary",
    description: "Summarize long documents and extract key points",
    icon: FileText,
    category: "Productivity",
    prompt: "Summarize this document and highlight key points: ",
    tags: ["productivity", "analysis", "documentation"],
    estimatedTime: "4-6 min",
    difficulty: "easy"
  }
];

// Mock data for quick actions
const QUICK_ACTIONS: QuickAction[] = [
  {
    id: "explain",
    name: "Explain",
    icon: Brain,
    prompt: "Explain this concept in simple terms: ",
    color: "bg-blue-500"
  },
  {
    id: "improve",
    name: "Improve",
    icon: TrendingUp,
    prompt: "How can I improve this: ",
    color: "bg-green-500"
  },
  {
    id: "debug",
    name: "Debug",
    icon: AlertCircle,
    prompt: "Help me debug this issue: ",
    color: "bg-red-500"
  },
  {
    id: "optimize",
    name: "Optimize",
    icon: Zap,
    prompt: "Optimize this for better performance: ",
    color: "bg-yellow-500"
  }
];

export default function TaskCreationPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [selectedTemplate, setSelectedTemplate] = useState<TaskTemplate | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("All");
  const [sortBy, setSortBy] = useState<"popular" | "category" | "difficulty">("popular");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Enhanced agent selection with filtering
  const [agentFilter, setAgentFilter] = useState<"all" | "specialized" | "high-performance">("all");
  const [showAgentDetails, setShowAgentDetails] = useState(false);

  // Helper functions
  const getAgentCapabilityColor = (capability: string) => {
    const colors = {
      "coding": "bg-blue-100 text-blue-800",
      "writing": "bg-green-100 text-green-800",
      "analysis": "bg-purple-100 text-purple-800",
      "research": "bg-orange-100 text-orange-800",
      "design": "bg-pink-100 text-pink-800",
      "data": "bg-cyan-100 text-cyan-800",
      "communication": "bg-yellow-100 text-yellow-800",
      "strategy": "bg-indigo-100 text-indigo-800"
    };
    return colors[capability as keyof typeof colors] || "bg-gray-100 text-gray-800";
  };

  const getDifficultyColor = (difficulty?: string) => {
    switch (difficulty) {
      case "easy": return "text-green-600 bg-green-50 border-green-200";
      case "medium": return "text-yellow-600 bg-yellow-50 border-yellow-200";
      case "hard": return "text-red-600 bg-red-50 border-red-200";
      default: return "text-gray-600 bg-gray-50 border-gray-200";
    }
  };

  const getFilteredTemplates = () => {
    let filtered = TASK_TEMPLATES;
    
    if (searchQuery) {
      filtered = filtered.filter(template => 
        template.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        template.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        template.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()))
      );
    }
    
    if (selectedCategory !== "All") {
      filtered = filtered.filter(template => template.category === selectedCategory);
    }
    
    return filtered.sort((a, b) => {
      switch (sortBy) {
        case "popular":
          return (b.popular ? 1 : 0) - (a.popular ? 1 : 0);
        case "category":
          return a.category.localeCompare(b.category);
        case "difficulty":
          const difficultyOrder = { "easy": 1, "medium": 2, "hard": 3 };
          return (difficultyOrder[a.difficulty || "easy"]) - (difficultyOrder[b.difficulty || "easy"]);
        default:
          return 0;
      }
    });
  };

  const getFilteredAgents = () => {
    let filtered = agents;
    
    switch (agentFilter) {
      case "specialized":
        filtered = agents.filter(agent => agent.specialization);
        break;
      case "high-performance":
        filtered = agents.filter(agent => (agent.performance_score || 0) > 80);
        break;
      default:
        break;
    }
    
    return filtered;
  };

  const categories = ["All", ...Array.from(new Set(TASK_TEMPLATES.map(t => t.category)))];

  const handleTemplateSelect = (template: TaskTemplate) => {
    setSelectedTemplate(template);
    setInput(template.prompt);
    setShowTemplates(false);
    if (inputRef.current) {
      inputRef.current.focus();
      // Position cursor at the end
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.setSelectionRange(template.prompt.length, template.prompt.length);
        }
      }, 0);
    }
  };

  const handleQuickAction = (action: QuickAction) => {
    setInput(action.prompt);
    if (inputRef.current) {
      inputRef.current.focus();
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.setSelectionRange(action.prompt.length, action.prompt.length);
        }
      }, 0);
    }
  };

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when agent is selected
  useEffect(() => {
    if (selectedAgent && inputRef.current) {
      inputRef.current.focus();
    }
  }, [selectedAgent]);

  // Load agents on mount
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        setLoadingAgents(true);
        const { data: agentsData = [] } = await listAgents();
        
        // Enhance agents with mock capabilities and performance data
        const enhancedAgents = agentsData
          .filter((agent: Agent) => agent.status === "active")
          .map((agent: Agent, index: number) => ({
            ...agent,
            capabilities: getRandomCapabilities(),
            specialization: getRandomSpecialization(),
            performance_score: Math.floor(Math.random() * 30) + 70,
            tasks_completed: Math.floor(Math.random() * 500) + 50,
            avg_response_time: Math.floor(Math.random() * 5) + 2
          }));
        
        setAgents(enhancedAgents);
        
        // Auto-select first active agent if available
        if (enhancedAgents.length > 0) {
          setSelectedAgent(enhancedAgents[0]);
        }
      } catch (err) {
        console.error("Failed to load agents:", err);
      } finally {
        setLoadingAgents(false);
      }
    };

    // Helper functions for mock data
    const getRandomCapabilities = () => {
      const allCapabilities = ["coding", "writing", "analysis", "research", "design", "data", "communication", "strategy"];
      const count = Math.floor(Math.random() * 4) + 2;
      return allCapabilities.sort(() => 0.5 - Math.random()).slice(0, count);
    };

    const getRandomSpecialization = () => {
      const specializations = ["Full-Stack Development", "Data Analysis", "Content Creation", "Research Assistant", "Code Review", "UI/UX Design", "Business Strategy", "Technical Writing"];
      return specializations[Math.floor(Math.random() * specializations.length)];
    };

    fetchAgents();
  }, []);

  // Load welcome message when agent is selected
  useEffect(() => {
    if (selectedAgent) {
      setMessages([
        {
          id: "welcome",
          content: `Hi! I'm ${selectedAgent.name}. ${selectedAgent.description ? selectedAgent.description + " " : ""}What task can I help you with today?`,
          role: "assistant",
          timestamp: new Date().toISOString(),
          agent_id: selectedAgent.id,
        },
      ]);
    }
  }, [selectedAgent]);

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading || !selectedAgent) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      role: "user",
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      // Send to chat API
      const { data: responseData, error } = await sendChatMessage({
        content: userMessage.content,
        agent_id: selectedAgent.id,
        user_id: "frontend_user",
      });

      if (error) {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: `Sorry, I encountered an error: ${error}`,
          role: "assistant",
          timestamp: new Date().toISOString(),
          agent_id: selectedAgent.id,
        };
        setMessages((prev) => [...prev, errorMessage]);
        setIsLoading(false);
      } else if (responseData) {
        // Add placeholder message while agent processes
        const placeholderMessage: Message = {
          id: responseData.task_id || (Date.now() + 1).toString(),
          content: "🤔 Working on your task...",
          role: "assistant",
          timestamp: responseData.timestamp || new Date().toISOString(),
          agent_id: selectedAgent.id,
          status: "processing",
          progress: 0
        };

        setMessages((prev) => [...prev, placeholderMessage]);
        
        // Start polling for the real response
        if (responseData.task_id) {
          pollForResponse(responseData.task_id);
        } else {
          setMessages((prev) => prev.map(msg => 
            msg.id === placeholderMessage.id 
              ? { ...msg, content: responseData.content || "Task completed", status: "completed", progress: 100 }
              : msg
          ));
          setIsLoading(false);
        }
      }
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I couldn't process your task. Error: ${error}`,
        role: "assistant",
        timestamp: new Date().toISOString(),
        agent_id: selectedAgent.id,
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const pollForResponse = async (taskId: string) => {
    const maxPolls = 60; // Poll for up to 5 minutes
    let pollCount = 0;

    const poll = async () => {
      try {
        const { data: status, error } = await getChatMessageStatus(taskId);
        
        if (error) {
          throw new Error("Failed to check task status");
        }
        
        // Update progress based on poll count
        const progress = Math.min((pollCount / maxPolls) * 90, 90);
        
        if (status?.status === "completed") {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: status.content, timestamp: status.timestamp, status: "completed", progress: 100 }
              : msg
          ));
          setIsLoading(false);
        } else if (status?.status === "failed") {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: `I apologize, but I encountered an error: ${status.error || "Unknown error"}`, status: "failed", progress: 0 }
              : msg
          ));
          setIsLoading(false);
        } else if (pollCount < maxPolls) {
          // Update progress while processing
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, progress: progress }
              : msg
          ));
          pollCount++;
          setTimeout(poll, 5000); // Poll every 5 seconds
        } else {
          setMessages((prev) => prev.map(msg => 
            msg.id === taskId 
              ? { ...msg, content: "Task timeout. Please try again.", status: "failed", progress: 0 }
              : msg
          ));
          setIsLoading(false);
        }
      } catch (error) {
        setMessages((prev) => prev.map(msg => 
          msg.id === taskId 
            ? { ...msg, content: "Failed to get response. Please try again.", status: "failed", progress: 0 }
            : msg
        ));
        setIsLoading(false);
      }
    };

    poll();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(e as any);
    }
  };

  return (
    <TooltipProvider>
      <ContentBlock
        header={{
          title: "AI Task Assistant",
          description: "Choose templates, select specialized agents, and get things done efficiently",
          controls: (
            <div className="flex gap-2">
              <Sheet open={showTemplates} onOpenChange={setShowTemplates}>
                <SheetTrigger asChild>
                  <Button variant="outline" className="gap-2">
                    <Workflow className="h-4 w-4" />
                    Templates
                  </Button>
                </SheetTrigger>
                <SheetContent side="right" className="w-[600px] sm:w-[800px]">
                  <SheetHeader>
                    <SheetTitle className="flex items-center gap-2">
                      <Workflow className="h-5 w-5" />
                      Task Templates
                    </SheetTitle>
                    <SheetDescription>
                      Choose from pre-built templates to get started quickly
                    </SheetDescription>
                  </SheetHeader>
                  
                  {/* Template search and filters */}
                  <div className="space-y-4 mt-6">
                    <div className="flex gap-3">
                      <div className="relative flex-1">
                        <Search className="h-4 w-4 absolute left-3 top-3 text-muted-foreground" />
                        <Input
                          placeholder="Search templates..."
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          className="pl-10"
                        />
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => setSortBy(sortBy === "popular" ? "category" : "popular")}
                        className="gap-2"
                      >
                        <SortDesc className="h-4 w-4" />
                        {sortBy === "popular" ? "Popular" : "Category"}
                      </Button>
                    </div>
                    
                    {/* Category tabs */}
                    <Tabs value={selectedCategory} onValueChange={setSelectedCategory}>
                      <TabsList className="grid w-full grid-cols-4">
                        {categories.slice(0, 4).map((category) => (
                          <TabsTrigger key={category} value={category} className="text-xs">
                            {category}
                          </TabsTrigger>
                        ))}
                      </TabsList>
                    </Tabs>
                    
                    {/* Templates grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[600px] overflow-y-auto">
                      {getFilteredTemplates().map((template) => {
                        const IconComponent = template.icon;
                        return (
                          <Card 
                            key={template.id} 
                            className="cursor-pointer hover:shadow-md transition-all border-2 hover:border-primary/50"
                            onClick={() => handleTemplateSelect(template)}
                          >
                            <CardHeader className="pb-3">
                              <div className="flex items-start gap-3">
                                <div className="p-2 rounded-lg bg-primary/10 flex-shrink-0">
                                  <IconComponent className="h-5 w-5 text-primary" />
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2 mb-1">
                                    <CardTitle className="text-sm font-medium">{template.name}</CardTitle>
                                    {template.popular && (
                                      <Badge variant="secondary" className="scale-75">
                                        <Star className="h-2.5 w-2.5 mr-1" />
                                        Popular
                                      </Badge>
                                    )}
                                  </div>
                                  <p className="text-xs text-muted-foreground line-clamp-2">
                                    {template.description}
                                  </p>
                                </div>
                              </div>
                            </CardHeader>
                            <CardContent className="pt-0">
                              <div className="flex items-center justify-between text-xs">
                                <div className="flex items-center gap-2">
                                  <Badge variant="outline" className={`${getDifficultyColor(template.difficulty)} text-xs`}>
                                    {template.difficulty}
                                  </Badge>
                                  {template.estimatedTime && (
                                    <span className="flex items-center gap-1 text-muted-foreground">
                                      <Timer className="h-3 w-3" />
                                      {template.estimatedTime}
                                    </span>
                                  )}
                                </div>
                                <Badge variant="secondary" className="text-xs">
                                  {template.category}
                                </Badge>
                              </div>
                            </CardContent>
                          </Card>
                        );
                      })}
                    </div>
                  </div>
                </SheetContent>
              </Sheet>
              
              <Link href="/agents/browse">
                <Button variant="outline" className="gap-2">
                  <Settings className="h-4 w-4" />
                  Manage Agents
                </Button>
              </Link>
              <Link href="/agents/create">
                <Button className="gap-2">
                  <Plus className="h-4 w-4" />
                  New Agent
                </Button>
              </Link>
            </div>
          ),
        }}
      >
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-200px)]">
          {/* Enhanced Agent Selection Sidebar */}
          <div className="lg:col-span-1">
            <Card className="h-full">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Bot className="h-5 w-5" />
                    AI Agents
                  </CardTitle>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowAgentDetails(!showAgentDetails)}
                      >
                        <Filter className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Toggle agent details</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                
                {/* Agent filter tabs */}
                <Tabs value={agentFilter} onValueChange={(value) => setAgentFilter(value as any)}>
                  <TabsList className="grid w-full grid-cols-3">
                    <TabsTrigger value="all" className="text-xs">All</TabsTrigger>
                    <TabsTrigger value="specialized" className="text-xs">Specialized</TabsTrigger>
                    <TabsTrigger value="high-performance" className="text-xs">Top Rated</TabsTrigger>
                  </TabsList>
                </Tabs>
              </CardHeader>
              
              <CardContent className="space-y-3 p-4 overflow-y-auto">
                {loadingAgents ? (
                  <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="p-3 rounded-lg border animate-pulse">
                        <div className="h-4 bg-muted rounded w-3/4 mb-2"></div>
                        <div className="h-3 bg-muted rounded w-full mb-2"></div>
                        <div className="flex gap-1">
                          <div className="h-4 bg-muted rounded w-12"></div>
                          <div className="h-4 bg-muted rounded w-12"></div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : getFilteredAgents().length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                    <p className="mb-2">No agents match your filter</p>
                    <Link href="/agents/create">
                      <Button size="sm" className="gap-2">
                        <Plus className="h-4 w-4" />
                        Create Agent
                      </Button>
                    </Link>
                  </div>
                ) : (
                  getFilteredAgents().map((agent) => (
                    <div
                      key={agent.id}
                      className={`p-3 rounded-lg border cursor-pointer transition-all hover:shadow-md hover:scale-[1.02] ${
                        selectedAgent?.id === agent.id
                          ? "border-primary bg-gradient-to-br from-primary/10 to-primary/5 shadow-md ring-1 ring-primary/20"
                          : "border-border hover:border-primary/50"
                      }`}
                      onClick={() => setSelectedAgent(agent)}
                    >
                      <div className="flex items-start gap-3">
                        <div className="relative">
                          <div className="h-10 w-10 bg-gradient-to-br from-primary/20 to-primary/10 rounded-full flex items-center justify-center flex-shrink-0">
                            <Bot className="h-5 w-5 text-primary" />
                          </div>
                          {agent.performance_score && agent.performance_score > 90 && (
                            <div className="absolute -top-1 -right-1 h-3 w-3 bg-yellow-500 rounded-full flex items-center justify-center">
                              <Star className="h-2 w-2 text-white" />
                            </div>
                          )}
                        </div>
                        
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className="font-medium text-sm truncate">{agent.name}</h3>
                            <Badge variant="default" className="scale-75">
                              <Zap className="h-2.5 w-2.5 mr-1" />
                              Active
                            </Badge>
                          </div>
                          
                          {agent.specialization && (
                            <p className="text-xs font-medium text-primary mb-1">
                              {agent.specialization}
                            </p>
                          )}
                          
                          <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                            {agent.description || "Ready to help with tasks"}
                          </p>
                          
                          {/* Agent capabilities */}
                          {agent.capabilities && agent.capabilities.length > 0 && (
                            <div className="flex flex-wrap gap-1 mb-2">
                              {agent.capabilities.slice(0, 3).map((capability) => (
                                <Badge
                                  key={capability}
                                  variant="outline"
                                  className={`text-xs px-1.5 py-0 ${getAgentCapabilityColor(capability)}`}
                                >
                                  {capability}
                                </Badge>
                              ))}
                              {agent.capabilities.length > 3 && (
                                <Badge variant="outline" className="text-xs px-1.5 py-0">
                                  +{agent.capabilities.length - 3}
                                </Badge>
                              )}
                            </div>
                          )}
                          
                          {/* Performance indicators */}
                          {showAgentDetails && agent.performance_score && (
                            <div className="space-y-1">
                              <div className="flex items-center justify-between text-xs">
                                <span className="text-muted-foreground">Performance</span>
                                <span className="font-medium">{agent.performance_score}%</span>
                              </div>
                              <Progress value={agent.performance_score} className="h-1.5" />
                              
                              <div className="flex items-center justify-between text-xs text-muted-foreground">
                                <span className="flex items-center gap-1">
                                  <CheckCircle2 className="h-3 w-3" />
                                  {agent.tasks_completed || 0} tasks
                                </span>
                                <span className="flex items-center gap-1">
                                  <Clock className="h-3 w-3" />
                                  {agent.avg_response_time || 2}s avg
                                </span>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                      
                      {selectedAgent?.id === agent.id && (
                        <div className="mt-3 flex items-center justify-between">
                          <div className="flex items-center gap-1 text-xs text-primary font-medium">
                            <Activity className="h-3 w-3" />
                            Currently selected
                          </div>
                          <ChevronRight className="h-4 w-4 text-primary" />
                        </div>
                      )}
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          {/* Enhanced Chat Interface */}
          <div className="lg:col-span-3">
            {selectedAgent ? (
              <Card className="h-full flex flex-col">
                <CardHeader className="pb-4 border-b">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <div className="h-12 w-12 bg-gradient-to-br from-primary/20 to-primary/10 rounded-full flex items-center justify-center">
                          <Bot className="h-6 w-6 text-primary" />
                        </div>
                        <div className="absolute -bottom-1 -right-1 h-4 w-4 bg-green-500 rounded-full border-2 border-background flex items-center justify-center">
                          <div className="h-2 w-2 bg-white rounded-full"></div>
                        </div>
                      </div>
                      <div>
                        <CardTitle className="flex items-center gap-2">
                          <MessageCircle className="h-5 w-5" />
                          {selectedAgent.name}
                        </CardTitle>
                        <div className="flex items-center gap-2 mt-1">
                          <p className="text-sm text-muted-foreground">
                            {selectedAgent.specialization || "AI Assistant"}
                          </p>
                          {selectedAgent.performance_score && (
                            <Badge variant="secondary" className="text-xs">
                              <TrendingUp className="h-2.5 w-2.5 mr-1" />
                              {selectedAgent.performance_score}% rating
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <Badge variant="default" className="gap-1 animate-pulse">
                        <Zap className="h-3 w-3" />
                        Online
                      </Badge>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm">
                            <Target className="h-4 w-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Agent capabilities: {selectedAgent.capabilities?.join(", ") || "General tasks"}</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                  
                  {/* Quick Actions Bar */}
                  <div className="flex gap-2 mt-4">
                    {QUICK_ACTIONS.map((action) => {
                      const IconComponent = action.icon;
                      return (
                        <Tooltip key={action.id}>
                          <TooltipTrigger asChild>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleQuickAction(action)}
                              className="gap-2 hover:scale-105 transition-transform"
                            >
                              <div className={`h-2 w-2 rounded-full ${action.color}`} />
                              <IconComponent className="h-4 w-4" />
                              {action.name}
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>{action.prompt}</p>
                          </TooltipContent>
                        </Tooltip>
                      );
                    })}
                  </div>
                </CardHeader>
              
                <CardContent className="flex-1 flex flex-col min-h-0 px-6">
                  {/* Enhanced Messages */}
                  <div className="flex-1 overflow-y-auto space-y-6 mb-4 min-h-0 pr-2">
                    {messages.map((message, index) => (
                      <div
                        key={message.id}
                        className={`flex gap-4 ${
                          message.role === "user" ? "justify-end" : "justify-start"
                        } group`}
                      >
                        {message.role === "assistant" && (
                          <Avatar className="h-10 w-10 flex-shrink-0 ring-2 ring-primary/20">
                            <AvatarFallback className="bg-gradient-to-br from-primary/20 to-primary/10">
                              <Bot className="h-5 w-5 text-primary" />
                            </AvatarFallback>
                          </Avatar>
                        )}
                        
                        <div className={`max-w-[85%] ${message.role === "user" ? "order-2" : ""}`}>
                          <div
                            className={`rounded-2xl px-5 py-4 shadow-sm ${
                              message.role === "user"
                                ? "bg-gradient-to-br from-primary to-primary/90 text-primary-foreground"
                                : "bg-white border border-border/60 shadow-sm"
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3 mb-2">
                              <p className="whitespace-pre-wrap text-sm leading-relaxed flex-1">
                                {message.content}
                              </p>
                              
                              {/* Status indicator */}
                              {message.role === "assistant" && message.status && (
                                <div className="flex-shrink-0">
                                  {message.status === "processing" && (
                                    <div className="flex items-center gap-2">
                                      <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                                      <span className="text-xs text-muted-foreground">Processing...</span>
                                    </div>
                                  )}
                                  {message.status === "completed" && (
                                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                                  )}
                                  {message.status === "failed" && (
                                    <AlertCircle className="h-4 w-4 text-red-500" />
                                  )}
                                </div>
                              )}
                            </div>
                            
                            {/* Progress bar for processing messages */}
                            {message.role === "assistant" && message.status === "processing" && message.progress !== undefined && (
                              <div className="mb-3">
                                <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                                  <span>Progress</span>
                                  <span>{Math.round(message.progress)}%</span>
                                </div>
                                <Progress value={message.progress} className="h-2" />
                              </div>
                            )}
                            
                            <div className="flex items-center justify-between">
                              <p className={`text-xs ${
                                message.role === "user" ? "text-primary-foreground/70" : "text-muted-foreground"
                              }`}>
                                {new Date(message.timestamp).toLocaleTimeString()}
                              </p>
                              
                              {/* Message actions (visible on hover) */}
                              <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                                {message.role === "assistant" && message.status === "completed" && (
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                                        <Sparkles className="h-3 w-3" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      <p>Improve this response</p>
                                    </TooltipContent>
                                  </Tooltip>
                                )}
                              </div>
                            </div>
                          </div>
                          
                          {/* Template indicator */}
                          {index === 1 && selectedTemplate && (
                            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                              <div className="h-1 w-1 bg-primary rounded-full"></div>
                              <span>Using template: {selectedTemplate.name}</span>
                            </div>
                          )}
                        </div>
                        
                        {message.role === "user" && (
                          <Avatar className="h-10 w-10 flex-shrink-0 ring-2 ring-muted/50 order-1">
                            <AvatarFallback className="bg-gradient-to-br from-muted to-muted/80">
                              <User className="h-5 w-5 text-muted-foreground" />
                            </AvatarFallback>
                          </Avatar>
                        )}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* Enhanced Input Section */}
                  <div className="border-t bg-gradient-to-r from-background to-muted/20 pt-6">
                    <form onSubmit={sendMessage} className="space-y-4">
                      {/* Template indicator */}
                      {selectedTemplate && (
                        <div className="flex items-center gap-2 px-3 py-2 bg-primary/5 border border-primary/20 rounded-lg">
                          <selectedTemplate.icon className="h-4 w-4 text-primary" />
                          <span className="text-sm font-medium text-primary">Using template: {selectedTemplate.name}</span>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedTemplate(null);
                              setInput("");
                            }}
                            className="ml-auto h-6 w-6 p-0"
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                      
                      <div className="relative">
                        <Textarea
                          ref={inputRef}
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={handleKeyDown}
                          placeholder={selectedTemplate 
                            ? `Continue your ${selectedTemplate.category.toLowerCase()} task...`
                            : `Describe your task for ${selectedAgent.name}... (or use templates & quick actions above)`
                          }
                          disabled={isLoading}
                          className="min-h-[100px] pr-16 resize-none text-sm border-2 focus:border-primary/50 rounded-xl bg-white/80 backdrop-blur-sm"
                          rows={4}
                        />
                        
                        <div className="absolute bottom-3 right-3 flex items-center gap-2">
                          {!isLoading && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setShowTemplates(true)}
                                  className="h-8 w-8 p-0 hover:bg-primary/10"
                                >
                                  <Workflow className="h-4 w-4 text-muted-foreground" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p>Browse templates</p>
                              </TooltipContent>
                            </Tooltip>
                          )}
                          
                          <Button 
                            type="submit" 
                            size="sm"
                            disabled={isLoading || !input.trim()}
                            className="h-8 px-4 rounded-lg font-medium shadow-sm hover:shadow-md transition-all hover:scale-105"
                          >
                            {isLoading ? (
                              <>
                                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                Sending...
                              </>
                            ) : (
                              <>
                                <Send className="h-4 w-4 mr-2" />
                                Send
                              </>
                            )}
                          </Button>
                        </div>
                      </div>
                      
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-4 text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Sparkles className="h-3 w-3" />
                            AI-powered task execution
                          </span>
                          <span className="hidden sm:inline">Enter to send • Shift+Enter for new line</span>
                          {selectedAgent.avg_response_time && (
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              ~{selectedAgent.avg_response_time}s response time
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <span className={`${input.length > 1800 ? 'text-orange-500' : 'text-muted-foreground'}`}>
                            {input.length}/2000
                          </span>
                          {selectedAgent.capabilities && (
                            <div className="flex items-center gap-1">
                              <Shield className="h-3 w-3 text-green-500" />
                              <span className="text-green-600 font-medium">Optimized</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </form>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card className="h-full flex items-center justify-center">
                <CardContent className="text-center py-12">
                  <div className="h-20 w-20 bg-gradient-to-br from-primary/20 to-primary/10 rounded-full flex items-center justify-center mx-auto mb-6">
                    <MessageCircle className="h-10 w-10 text-primary" />
                  </div>
                  <h3 className="text-xl font-semibold mb-3">Ready to get started?</h3>
                  <p className="text-muted-foreground mb-8 max-w-md leading-relaxed">
                    Select an AI agent from the sidebar to begin your task. Use templates for quick starts or create custom requests.
                  </p>
                  
                  <div className="space-y-4">
                    {agents.length === 0 ? (
                      <Link href="/agents/create">
                        <Button className="gap-2 h-11 px-6">
                          <Plus className="h-5 w-5" />
                          Create Your First Agent
                        </Button>
                      </Link>
                    ) : (
                      <div className="flex flex-col sm:flex-row gap-3 justify-center">
                        <Button
                          variant="outline"
                          onClick={() => setShowTemplates(true)}
                          className="gap-2 h-11 px-6"
                        >
                          <Workflow className="h-5 w-5" />
                          Browse Templates
                        </Button>
                        <Link href="/agents/create">
                          <Button className="gap-2 h-11 px-6">
                            <Plus className="h-5 w-5" />
                            New Agent
                          </Button>
                        </Link>
                      </div>
                    )}
                    
                    {/* Feature highlights */}
                    <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl mx-auto">
                      <div className="flex flex-col items-center p-4 rounded-lg bg-muted/30">
                        <Sparkles className="h-6 w-6 text-primary mb-2" />
                        <h4 className="font-medium text-sm mb-1">Smart Templates</h4>
                        <p className="text-xs text-muted-foreground text-center">Pre-built task templates for common workflows</p>
                      </div>
                      <div className="flex flex-col items-center p-4 rounded-lg bg-muted/30">
                        <Bot className="h-6 w-6 text-primary mb-2" />
                        <h4 className="font-medium text-sm mb-1">Specialized Agents</h4>
                        <p className="text-xs text-muted-foreground text-center">AI agents with specific capabilities and expertise</p>
                      </div>
                      <div className="flex flex-col items-center p-4 rounded-lg bg-muted/30">
                        <TrendingUp className="h-6 w-6 text-primary mb-2" />
                        <h4 className="font-medium text-sm mb-1">Real-time Progress</h4>
                        <p className="text-xs text-muted-foreground text-center">Live updates and progress tracking for all tasks</p>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </ContentBlock>
    </TooltipProvider>
  );
}