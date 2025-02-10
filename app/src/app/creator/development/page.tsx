"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import {
  Play,
  Code2,
  Terminal,
  MessageSquare,
  Settings,
  Save,
  Download,
  Upload,
  RefreshCw,
  ChevronDown,
  FileCode,
  Database,
  Workflow,
  TestTube2
} from "lucide-react";

const sampleCode = `# Agent Configuration
name: "Custom Data Processor"
version: "1.0.0"
description: "Process and analyze custom data formats"

# Capabilities
capabilities:
  - data_processing
  - pattern_matching
  - report_generation

# Input Schema
input:
  type: object
  properties:
    data_source:
      type: string
      description: "Source of the data to process"
    format:
      type: string
      enum: ["csv", "json", "xml"]
    options:
      type: object

# Processing Logic
async def process(input_data):
    # Initialize processing
    source = input_data.data_source
    format = input_data.format
    
    # Load and validate data
    data = await load_data(source, format)
    
    # Process the data
    results = await analyze_data(data)
    
    # Generate report
    return {
        "status": "success",
        "results": results,
        "summary": generate_summary(results)
    }`;

const testCases = [
  {
    name: "Basic CSV Processing",
    input: {
      data_source: "s3://data/sample.csv",
      format: "csv",
      options: { header: true }
    },
    status: "passed",
    duration: "1.2s"
  },
  {
    name: "Large JSON File",
    input: {
      data_source: "s3://data/large.json",
      format: "json",
      options: { batch_size: 1000 }
    },
    status: "failed",
    duration: "2.5s"
  },
  {
    name: "XML Validation",
    input: {
      data_source: "s3://data/config.xml",
      format: "xml",
      options: { validate: true }
    },
    status: "running",
    duration: "-"
  }
];

export default function DevelopmentPage() {
  const [activeTab, setActiveTab] = useState("code");
  const [isRunning, setIsRunning] = useState(false);

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Agent Development</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Build and test your automation agents
          </p>
        </div>
        <div className="flex gap-4">
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Upload className="h-4 w-4" />
            Import
          </button>
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Download className="h-4 w-4" />
            Export
          </button>
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Save className="h-4 w-4" />
            Save
          </button>
          <button
            className={`bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2 ${
              isRunning ? "opacity-50 cursor-not-allowed" : ""
            }`}
            onClick={() => setIsRunning(!isRunning)}
            disabled={isRunning}
          >
            {isRunning ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}
            {isRunning ? "Running..." : "Run Agent"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2">
          <Card className="h-[calc(100vh-12rem)]">
            <div className="border-b">
              <div className="flex items-center gap-4 p-2">
                <button
                  className={`px-3 py-1.5 rounded flex items-center gap-2 ${
                    activeTab === "code" ? "bg-secondary" : "hover:bg-secondary/50"
                  }`}
                  onClick={() => setActiveTab("code")}
                >
                  <Code2 className="h-4 w-4" />
                  Code
                </button>
                <button
                  className={`px-3 py-1.5 rounded flex items-center gap-2 ${
                    activeTab === "config" ? "bg-secondary" : "hover:bg-secondary/50"
                  }`}
                  onClick={() => setActiveTab("config")}
                >
                  <Settings className="h-4 w-4" />
                  Configuration
                </button>
                <button
                  className={`px-3 py-1.5 rounded flex items-center gap-2 ${
                    activeTab === "test" ? "bg-secondary" : "hover:bg-secondary/50"
                  }`}
                  onClick={() => setActiveTab("test")}
                >
                  <TestTube2 className="h-4 w-4" />
                  Tests
                </button>
              </div>
            </div>
            <div className="p-4 h-full bg-secondary/5 font-mono text-sm overflow-auto">
              <pre>{sampleCode}</pre>
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <div className="p-4 border-b">
              <h2 className="font-semibold flex items-center gap-2">
                <Terminal className="h-4 w-4" />
                Console Output
              </h2>
            </div>
            <div className="p-4 h-48 bg-secondary/5 font-mono text-sm overflow-auto">
              <div className="text-green-600">[INFO] Agent initialized successfully</div>
              <div className="text-blue-600">[DEBUG] Loading configuration...</div>
              <div className="text-yellow-600">[WARN] Resource usage above 75%</div>
              <div className="text-red-600">[ERROR] Failed to connect to database</div>
            </div>
          </Card>

          <Card>
            <div className="p-4 border-b">
              <h2 className="font-semibold flex items-center gap-2">
                <TestTube2 className="h-4 w-4" />
                Test Results
              </h2>
            </div>
            <div className="divide-y">
              {testCases.map((test, index) => (
                <div key={index} className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium">{test.name}</span>
                    <span className={`text-sm px-2 py-1 rounded-full ${
                      test.status === "passed" ? "bg-green-100 text-green-700" :
                      test.status === "failed" ? "bg-red-100 text-red-700" :
                      "bg-yellow-100 text-yellow-700"
                    }`}>
                      {test.status.charAt(0).toUpperCase() + test.status.slice(1)}
                    </span>
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Duration: {test.duration}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <div className="p-4 border-b">
              <h2 className="font-semibold flex items-center gap-2">
                <Workflow className="h-4 w-4" />
                Dependencies
              </h2>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileCode className="h-4 w-4 text-blue-500" />
                  <span className="text-sm">data-processor</span>
                </div>
                <span className="text-sm text-muted-foreground">v2.1.0</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-green-500" />
                  <span className="text-sm">storage-client</span>
                </div>
                <span className="text-sm text-muted-foreground">v1.5.2</span>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
} 