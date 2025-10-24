"use client";

import React, { useState, useRef, useEffect } from "react";
import AuthGuard from "@/components/auth/AuthGuard";
import { Card } from "@/components/ui/card";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { 
  Bot, 
  MessageSquare, 
  Send, 
  Bell, 
  CheckCircle2,
  Clock,
  AlertCircle,
  ChevronRight,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

interface Message {
  id: string;
  content: string;
  sender: "user" | "agent";
  timestamp: Date;
}

interface Task {
  id: string;
  title: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "needs_input";
  priority: "low" | "medium" | "high";
  assignedAgent: string;
  createdAt: string;
  hasUpdates?: boolean;
}

interface Notification {
  id: string;
  title: string;
  message: string;
  type: "info" | "warning" | "error" | "success";
  time: string;
  isRead: boolean;
}

export default function WorkplacePage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      content: "Hello! I'm your AgentMesh assistant. What tasks can I help you with today?",
      sender: "agent",
      timestamp: new Date(),
    },
  ]);
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  
  // Sample data for tasks and notifications
  const [tasks] = useState<Task[]>([
    {
      id: "task-1",
      title: "Analyze Q1 Sales Data",
      description: "Generate insights from Q1 sales data and create a summary report",
      status: "in_progress",
      priority: "high",
      assignedAgent: "Data Analytics Agent",
      createdAt: "2 hours ago",
      hasUpdates: true
    },
    {
      id: "task-2",
      title: "Update Customer FAQ",
      description: "Refresh the FAQ section with latest product information",
      status: "needs_input",
      priority: "medium",
      assignedAgent: "Content Management Agent",
      createdAt: "5 hours ago"
    },
    {
      id: "task-3",
      title: "Monitor Website Performance",
      description: "Track website metrics and alert on any performance issues",
      status: "pending",
      priority: "medium",
      assignedAgent: "Monitoring Agent",
      createdAt: "1 day ago"
    },
    {
      id: "task-4",
      title: "Generate Weekly Analytics Report",
      description: "Prepare the standard weekly analytics report for distribution",
      status: "completed",
      priority: "high",
      assignedAgent: "Reporting Agent",
      createdAt: "2 days ago",
      hasUpdates: true
    }
  ]);
  
  const [notifications, setNotifications] = useState<Notification[]>([
    {
      id: "notif-1",
      title: "Task Requires Input",
      message: "The Content Management Agent needs your input on FAQ updates",
      type: "warning",
      time: "30 minutes ago",
      isRead: false
    },
    {
      id: "notif-2",
      title: "Analysis Complete",
      message: "Weekly summary report has been generated and is ready for review",
      type: "info",
      time: "2 hours ago",
      isRead: false
    },
    {
      id: "notif-3",
      title: "System Alert",
      message: "Database connection issues detected. Some agents may experience delays",
      type: "error",
      time: "3 hours ago",
      isRead: true
    }
  ]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
  };

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;
    
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: "user",
      timestamp: new Date(),
    };
    
    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    
    // Simulate agent response
    setTimeout(() => {
      const agentMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `I'll help you with "${inputValue}". I'll set up the task and assign it to the appropriate agent.`,
        sender: "agent",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, agentMessage]);
    }, 1000);
  };

  const markNotificationAsRead = (id: string) => {
    setNotifications(notifications.map(notif => 
      notif.id === id ? { ...notif, isRead: true } : notif
    ));
  };

  const unreadCount = notifications.filter(n => !n.isRead).length;
  
  // Get tasks that need input
  const tasksNeedingInput = tasks.filter(task => task.status === "needs_input");
  
  // Get tasks with updates
  const tasksWithUpdates = tasks.filter(task => task.hasUpdates);

  const getStatusTagClasses = (status: string) => {
    switch(status) {
      case 'in_progress': return 'bg-blue-100 text-blue-800';
      case 'completed': return 'bg-green-100 text-green-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <AuthGuard>
      <ContentBlock
      header={{
        // title: "Workplace",
        breadcrumb: [
          {label: "Workplace", href: "/workplace"},
        ],
        description: "Your command center for managing agents and tasks"
      }}
    >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Task creation and chat section */}
          <div className="lg:col-span-2">
            <Card className="p-6 border border-gray-200 shadow-sm bg-white rounded-xl">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-5 w-5 text-indigo-500" />
                  <h2 className="text-lg font-semibold">New Task</h2>
                </div>
                <Badge variant="outline" className="flex gap-1 items-center border-gray-200">
                  <Bot className="h-3 w-3" />
                  <span>Agents Ready</span>
                </Badge>
              </div>
              
              <div className="mb-4">
                <div className="relative">
                  <Input
                    ref={inputRef}
                    placeholder="Describe a task for agents to perform..."
                    value={inputValue}
                    onChange={handleInputChange}
                    className="bg-white border-gray-200 pr-24 py-6 pl-4 rounded-lg"
                    onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  />
                  <Button 
                    onClick={handleSendMessage} 
                    className="absolute right-1 top-1/2 transform -translate-y-1/2 px-4 bg-indigo-500 hover:bg-indigo-600"
                  >
                    <Send className="h-4 w-4 mr-2" />
                    <span>Send</span>
                  </Button>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Describe what you want agents to do, or ask a question.
                </p>
              </div>
              
              {/* Recent messages */}
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-gray-700">Recent Messages</h3>
                <ScrollArea className="h-32">
                  <div className="space-y-2">
                    {messages.slice(-3).map((message) => (
                      <div
                        key={message.id}
                        className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-xs px-3 py-2 rounded-lg text-sm ${
                            message.sender === "user"
                              ? "bg-indigo-500 text-white"
                              : "bg-gray-100 text-gray-800"
                          }`}
                        >
                          {message.content}
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            </Card>
          </div>

          {/* Sidebar with tasks and notifications */}
          <div className="space-y-6">
            {/* Active Tasks */}
            <Card className="p-4 border border-gray-200 shadow-sm bg-white rounded-xl">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-700">Active Tasks</h3>
                <Badge variant="outline" className="text-xs border-gray-200">
                  {tasks.length}
                </Badge>
              </div>
              <div className="space-y-2">
                {tasks.slice(0, 3).map((task) => (
                  <div key={task.id} className="p-3 bg-gray-50 rounded-lg">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h4 className="text-sm font-medium text-gray-800 truncate">
                          {task.title}
                        </h4>
                        <p className="text-xs text-gray-600 mt-1 line-clamp-2">
                          {task.description}
                        </p>
                        <div className="flex items-center gap-2 mt-2">
                          <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${getStatusTagClasses(task.status)}`}>
                            {task.status.replace('_', ' ')}
                          </span>
                          <span className="text-xs text-gray-500">
                            {task.assignedAgent}
                          </span>
                        </div>
                      </div>
                      {task.hasUpdates && (
                        <div className="ml-2">
                          <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {tasks.length > 3 && (
                  <Button variant="ghost" size="sm" className="w-full text-xs text-gray-600 hover:text-gray-800">
                    View all {tasks.length} tasks
                    <ChevronRight className="h-3 w-3 ml-1" />
                  </Button>
                )}
              </div>
            </Card>

            {/* Notifications */}
            <Card className="p-4 border border-gray-200 shadow-sm bg-white rounded-xl">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-700">Notifications</h3>
                {unreadCount > 0 && (
                  <Badge variant="outline" className="text-xs border-gray-200">
                    {unreadCount} new
                  </Badge>
                )}
              </div>
              <div className="space-y-2">
                {notifications.slice(0, 3).map((notification) => (
                  <div
                    key={notification.id}
                    className={`p-3 rounded-lg cursor-pointer transition-colors ${
                      notification.isRead ? "bg-gray-50" : "bg-blue-50"
                    }`}
                    onClick={() => markNotificationAsRead(notification.id)}
                  >
                    <div className="flex items-start gap-2">
                      <div className={`mt-1 ${
                        notification.type === "error" ? "text-red-500" :
                        notification.type === "warning" ? "text-yellow-500" :
                        notification.type === "success" ? "text-green-500" :
                        "text-blue-500"
                      }`}>
                        {notification.type === "error" && <AlertCircle className="h-4 w-4" />}
                        {notification.type === "warning" && <AlertCircle className="h-4 w-4" />}
                        {notification.type === "success" && <CheckCircle2 className="h-4 w-4" />}
                        {notification.type === "info" && <Bell className="h-4 w-4" />}
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-medium text-gray-800">
                          {notification.title}
                        </h4>
                        <p className="text-xs text-gray-600 mt-1">
                          {notification.message}
                        </p>
                        <p className="text-xs text-gray-500 mt-1">
                          {notification.time}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
                {notifications.length > 3 && (
                  <Button variant="ghost" size="sm" className="w-full text-xs text-gray-600 hover:text-gray-800">
                    View all {notifications.length} notifications
                    <ChevronRight className="h-3 w-3 ml-1" />
                  </Button>
                )}
              </div>
            </Card>

            {/* Quick Actions */}
            <Card className="p-4 border border-gray-200 shadow-sm bg-white rounded-xl">
              <h3 className="text-sm font-medium text-gray-700 mb-3">Quick Actions</h3>
              <div className="space-y-2">
                <Button variant="outline" size="sm" className="w-full justify-start text-xs">
                  <Bot className="h-3 w-3 mr-2" />
                  Create New Agent
                </Button>
                <Button variant="outline" size="sm" className="w-full justify-start text-xs">
                  <MessageSquare className="h-3 w-3 mr-2" />
                  Start Chat Session
                </Button>
                <Button variant="outline" size="sm" className="w-full justify-start text-xs">
                  <Clock className="h-3 w-3 mr-2" />
                  Schedule Task
                </Button>
              </div>
            </Card>
          </div>
        </div>
    </ContentBlock>
    </AuthGuard>
  );
} 