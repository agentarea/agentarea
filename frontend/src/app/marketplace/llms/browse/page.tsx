"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Cpu, Download, Plus } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

// Sample LLM models data (in a real app, this would come from an API)
const llmModels = [
  {
    id: "1",
    name: "Claude 3.5 Sonnet",
    description: "Balanced model for various tasks with strong reasoning capabilities",
    provider: "Anthropic",
    rating: 4.8,
    verified: true,
    tags: ["text", "reasoning", "general purpose"],
  },
  {
    id: "2",
    name: "GPT-4o",
    description: "Multi-modal model for text, vision, and reasoning",
    provider: "OpenAI",
    rating: 4.9,
    verified: true,
    tags: ["text", "vision", "reasoning"],
  },
  {
    id: "3",
    name: "Llama 3 70B",
    description: "Open source model with strong reasoning and chat capabilities",
    provider: "Meta",
    rating: 4.6,
    verified: true,
    tags: ["text", "open source", "fine-tunable"],
  },
];

export default function BrowseLLMsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  
  const filteredModels = llmModels.filter(model => 
    model.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    model.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    model.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()))
  );
  
  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <Input
          placeholder="Search LLM models..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="max-w-md"
        />
        <Button asChild>
          <Link href="/marketplace/llms/create" className="flex items-center gap-1">
            <Plus className="h-4 w-4" />
            Add Model
          </Link>
        </Button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredModels.map((model) => (
          <Card key={model.id} className="flex flex-col">
            <CardHeader>
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                  <Cpu className="h-5 w-5 text-primary" />
                  <CardTitle>{model.name}</CardTitle>
                </div>
                {model.verified && (
                  <Badge variant="secondary">Verified</Badge>
                )}
              </div>
              <CardDescription>{model.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex-grow">
              <div className="flex flex-wrap gap-2 mb-3">
                {model.tags.map((tag) => (
                  <Badge key={tag} variant="outline">{tag}</Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">By {model.provider} • {model.rating} rating</p>
            </CardContent>
            <CardFooter className="flex justify-between">
              <Button variant="outline" size="sm">View Details</Button>
              <Button size="sm" className="flex items-center gap-1">
                <Download className="h-4 w-4" />
                Install
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
} 