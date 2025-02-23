"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Globe,
  Database,
  Mail,
  MessageSquare,
  FileText,
  ChevronRight,
  ArrowLeft,
  CheckCircle2,
  Key
} from "lucide-react";

interface SourceType {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  category: string;
}

const sourceTypes: SourceType[] = [
  {
    id: "shopify",
    name: "Shopify",
    description: "Connect your Shopify store to automate e-commerce operations",
    icon: <Globe className="h-6 w-6" />,
    category: "E-commerce"
  },
  {
    id: "postgres",
    name: "PostgreSQL",
    description: "Connect to your PostgreSQL database for data processing",
    icon: <Database className="h-6 w-6" />,
    category: "Database"
  },
  {
    id: "gmail",
    name: "Gmail",
    description: "Process emails and automate responses",
    icon: <Mail className="h-6 w-6" />,
    category: "Communication"
  },
  {
    id: "slack",
    name: "Slack",
    description: "Integrate with Slack for team notifications and automation",
    icon: <MessageSquare className="h-6 w-6" />,
    category: "Communication"
  },
  {
    id: "s3",
    name: "Amazon S3",
    description: "Connect to S3 buckets for document processing",
    icon: <FileText className="h-6 w-6" />,
    category: "Storage"
  }
];

const categories = ["All", "E-commerce", "Database", "Communication", "Storage"];

export default function NewSourcePage() {
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [step, setStep] = useState(1);
  const [selectedSource, setSelectedSource] = useState<SourceType | null>(null);

  const filteredSources = selectedCategory === "All"
    ? sourceTypes
    : sourceTypes.filter(source => source.category === selectedCategory);

  const renderStep1 = () => (
    <div>
      <div className="flex gap-4 mb-6 overflow-x-auto pb-2">
        {categories.map((category) => (
          <button
            key={category}
            onClick={() => setSelectedCategory(category)}
            className={`px-4 py-2 rounded-full whitespace-nowrap ${
              selectedCategory === category
                ? "bg-primary text-primary-foreground"
                : "bg-secondary hover:bg-secondary/80"
            }`}
          >
            {category}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredSources.map((source) => (
          <Card
            key={source.id}
            className={`p-6 cursor-pointer transition-all ${
              selectedSource?.id === source.id
                ? "ring-2 ring-primary"
                : "hover:shadow-lg"
            }`}
            onClick={() => setSelectedSource(source)}
          >
            <div className="flex items-center gap-4 mb-4">
              <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                {source.icon}
              </div>
              <div>
                <h3 className="font-semibold">{source.name}</h3>
                <span className="text-sm text-muted-foreground">{source.category}</span>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{source.description}</p>
          </Card>
        ))}
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="max-w-2xl mx-auto">
      <Card className="p-8">
        <div className="flex items-center gap-4 mb-6">
          <div className="h-16 w-16 bg-primary/10 rounded-lg flex items-center justify-center">
            {selectedSource?.icon}
          </div>
          <div>
            <h2 className="text-2xl font-bold">{selectedSource?.name}</h2>
            <p className="text-muted-foreground">{selectedSource?.description}</p>
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <label className="text-sm font-medium mb-2 block">Connection Name</label>
            <Input placeholder="Enter a name for this connection" />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">API Key</label>
            <div className="relative">
              <Input type="password" placeholder="Enter your API key" />
              <Key className="absolute right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            </div>
          </div>

          {selectedSource?.id === "postgres" && (
            <>
              <div>
                <label className="text-sm font-medium mb-2 block">Host</label>
                <Input placeholder="database.example.com" />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Port</label>
                <Input placeholder="5432" />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Database Name</label>
                <Input placeholder="Enter database name" />
              </div>
            </>
          )}

          <div className="pt-6 border-t">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="rounded border-gray-300" />
              Enable automatic sync
            </label>
          </div>
        </div>
      </Card>
    </div>
  );

  const renderStep3 = () => (
    <div className="max-w-2xl mx-auto text-center">
      <div className="mb-8">
        <div className="h-20 w-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <CheckCircle2 className="h-10 w-10 text-green-500" />
        </div>
        <h2 className="text-2xl font-bold mb-2">Connection Successful!</h2>
        <p className="text-muted-foreground">
          Your {selectedSource?.name} connection has been set up successfully.
        </p>
      </div>

      <div className="flex justify-center gap-4">
        <button
          onClick={() => window.location.href = "/sources/browse"}
          className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-2 rounded-lg"
        >
          View All Sources
        </button>
        <button
          onClick={() => {
            setStep(1);
            setSelectedSource(null);
          }}
          className="px-6 py-2 border rounded-lg hover:bg-secondary"
        >
          Connect Another Source
        </button>
      </div>
    </div>
  );

  return (
    <div className="p-8">
      <div className="flex items-center gap-4 mb-8">
        {step > 1 && (
          <button
            onClick={() => setStep(step - 1)}
            className="p-2 hover:bg-secondary rounded-lg"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
        )}
        <div>
          <h1 className="text-4xl font-bold">Connect New Source</h1>
          <p className="text-lg text-muted-foreground mt-2">
            {step === 1 ? "Select a data source to connect" :
             step === 2 ? "Configure connection details" :
             "Connection complete"}
          </p>
        </div>
      </div>

      <div className="mb-8">
        <div className="flex items-center">
          <div className={`h-10 w-10 rounded-full flex items-center justify-center ${
            step >= 1 ? "bg-primary text-primary-foreground" : "bg-secondary"
          }`}>
            1
          </div>
          <div className={`h-1 w-20 ${step > 1 ? "bg-primary" : "bg-secondary"}`} />
          <div className={`h-10 w-10 rounded-full flex items-center justify-center ${
            step >= 2 ? "bg-primary text-primary-foreground" : "bg-secondary"
          }`}>
            2
          </div>
          <div className={`h-1 w-20 ${step > 2 ? "bg-primary" : "bg-secondary"}`} />
          <div className={`h-10 w-10 rounded-full flex items-center justify-center ${
            step >= 3 ? "bg-primary text-primary-foreground" : "bg-secondary"
          }`}>
            3
          </div>
        </div>
      </div>

      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}

      {step === 1 && selectedSource && (
        <div className="fixed bottom-8 right-8">
          <button
            onClick={() => setStep(2)}
            className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-3 rounded-lg flex items-center gap-2"
          >
            Continue Setup
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="fixed bottom-8 right-8">
          <button
            onClick={() => setStep(3)}
            className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-3 rounded-lg flex items-center gap-2"
          >
            Connect Source
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      )}
    </div>
  );
} 