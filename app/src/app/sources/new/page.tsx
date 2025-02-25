"use client";

import React, { useState, useRef, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Globe,
  Database,
  Mail,
  MessageSquare,
  FileText,
  ChevronRight,
  ArrowLeft,
  CheckCircle2,
  Key,
  Upload,
  Link as LinkIcon,
  Loader2,
  AlertCircle,
  File
} from "lucide-react";
import { useRouter } from 'next/navigation';
import { sourcesApi, SourceCreate } from '@/api/sources';
import { SourceType } from '@/types/source';

interface SourceTypeUI {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  category: string;
  sourceType: SourceType;
}

const sourceTypesUI: SourceTypeUI[] = [
  {
    id: "shopify",
    name: "Shopify",
    description: "Connect your Shopify store to automate e-commerce operations",
    icon: <Globe className="h-6 w-6" />,
    category: "E-commerce",
    sourceType: SourceType.API
  },
  {
    id: "postgres",
    name: "PostgreSQL",
    description: "Connect to your PostgreSQL database for data processing",
    icon: <Database className="h-6 w-6" />,
    category: "Database",
    sourceType: SourceType.DATABASE
  },
  {
    id: "gmail",
    name: "Gmail",
    description: "Process emails and automate responses",
    icon: <Mail className="h-6 w-6" />,
    category: "Communication",
    sourceType: SourceType.API
  },
  {
    id: "slack",
    name: "Slack",
    description: "Integrate with Slack for team notifications and automation",
    icon: <MessageSquare className="h-6 w-6" />,
    category: "Communication",
    sourceType: SourceType.API
  },
  {
    id: "s3",
    name: "Amazon S3",
    description: "Connect to S3 buckets for document processing",
    icon: <FileText className="h-6 w-6" />,
    category: "Storage",
    sourceType: SourceType.STREAM
  },
  {
    id: "file",
    name: "File Upload",
    description: "Quickly upload and process files (CSV, Excel, JSON, etc.)",
    icon: <Upload className="h-6 w-6" />,
    category: "Quick Upload",
    sourceType: SourceType.FILE
  }
];

const categories = ["All", "Quick Upload", "E-commerce", "Database", "Communication", "Storage"];

export default function NewSourcePage() {
  const router = useRouter();
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [step, setStep] = useState(1);
  const [selectedSource, setSelectedSource] = useState<SourceTypeUI | null>(null);
  const [uploadMode, setUploadMode] = useState<"connect" | "upload">("connect");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectionName, setConnectionName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [dbName, setDbName] = useState("");
  const [autoSync, setAutoSync] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<{success: boolean, message: string} | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [processingType, setProcessingType] = useState("auto");
  const [saveAsTemplate, setSaveAsTemplate] = useState(false);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<{message: string, sourceId?: string} | null>(null);

  useEffect(() => {
    // Fetch source specifications when component mounts
    const fetchSourceSpecs = async () => {
      try {
        await sourcesApi.listSourceSpecifications();
        // We're not using the specs yet, but we're fetching them for future use
      } catch {
        console.error("Failed to fetch source specifications");
      }
    };

    fetchSourceSpecs();
  }, []);

  const filteredSources = selectedCategory === "All"
    ? sourceTypesUI
    : sourceTypesUI.filter(source => source.category === selectedCategory);

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
            className={`p-6 cursor-pointer transition-all hover:border-primary ${
              selectedSource?.id === source.id
                ? "ring-2 ring-primary border-primary"
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

  const handleTestConnection = async () => {
    if (!selectedSource) return;
    
    setTestingConnection(true);
    setConnectionStatus(null);
    
    try {
      // Create configuration object based on form inputs
      const configuration: Record<string, string> = {
        apiKey: apiKey,
      };
      
      if (selectedSource.id === "postgres") {
        configuration.host = host;
        configuration.port = port;
        configuration.database = dbName;
      }
      
      const result = await sourcesApi.testConnection(configuration, selectedSource.id);
      setConnectionStatus(result);
    } catch (testErr: unknown) {
      setConnectionStatus({
        success: false,
        message: "Connection test failed. Please check your credentials."
      });
      console.error("Connection test error:", testErr);
    } finally {
      setTestingConnection(false);
    }
  };

  const renderStep2 = () => (
    <div className="max-w-2xl mx-auto">
      <Card className="p-8 border-2 border-muted">
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
            <Input 
              placeholder="Enter a name for this connection" 
              value={connectionName}
              onChange={(e) => setConnectionName(e.target.value)}
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-2 block">API Key</label>
            <div className="relative">
              <Input 
                type="password" 
                placeholder="Enter your API key" 
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <Key className="absolute right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            </div>
          </div>

          {selectedSource?.id === "postgres" && (
            <>
              <div>
                <label className="text-sm font-medium mb-2 block">Host</label>
                <Input 
                  placeholder="database.example.com" 
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Port</label>
                <Input 
                  placeholder="5432" 
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">Database Name</label>
                <Input 
                  placeholder="Enter database name" 
                  value={dbName}
                  onChange={(e) => setDbName(e.target.value)}
                />
              </div>
            </>
          )}

          <div className="pt-6 border-t">
            <div className="flex items-center space-x-2">
              <input 
                type="checkbox" 
                id="autoSync" 
                className="rounded border-gray-300"
                checked={autoSync}
                onChange={(e) => setAutoSync(e.target.checked)}
              />
              <label htmlFor="autoSync" className="text-sm">Enable automatic sync</label>
            </div>
          </div>

          {connectionStatus && (
            <div className={`p-4 rounded-md ${connectionStatus.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
              {connectionStatus.message}
            </div>
          )}

          <div className="flex justify-end">
            <Button 
              variant="outline" 
              onClick={handleTestConnection}
              disabled={testingConnection}
              className="flex items-center gap-2"
            >
              {testingConnection ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Testing Connection...
                </>
              ) : (
                <>Test Connection</>
              )}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );

  const handleFileUpload = async () => {
    if (uploadedFiles.length === 0) {
      setUploadError("Please select at least one file to upload");
      return;
    }

    setUploadLoading(true);
    setUploadError(null);
    setUploadSuccess(null);

    try {
      const result = await sourcesApi.uploadFiles(uploadedFiles, {
        processingType: processingType === "auto" ? undefined : processingType,
        saveAsTemplate,
        templateName: saveAsTemplate ? `Template-${new Date().toISOString().slice(0, 10)}` : undefined
      });

      if (result.success) {
        setUploadSuccess({
          message: result.message,
          sourceId: result.sourceId
        });
        setStep(3);
      } else {
        setUploadError(result.message);
      }
    } catch (uploadErr: unknown) {
      const errorMessage = uploadErr instanceof Error ? uploadErr.message : "An unexpected error occurred during file upload";
      setUploadError(errorMessage);
      console.error("File upload error:", uploadErr);
    } finally {
      setUploadLoading(false);
    }
  };

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const filesArray = Array.from(e.dataTransfer.files);
      setUploadedFiles(prev => [...prev, ...filesArray]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const filesArray = Array.from(e.target.files);
      setUploadedFiles(prev => [...prev, ...filesArray]);
    }
  };

  const removeFile = (index: number) => {
    setUploadedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const renderFileUpload = () => (
    <div className="max-w-2xl mx-auto">
      <Card className="p-8 border-2 border-muted">
        <div 
          className="text-center p-8 border-2 border-dashed rounded-lg hover:border-primary transition-colors cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={handleFileDrop}
        >
          <Upload className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
          <div className="space-y-2">
            <h3 className="font-semibold">Drop your files here</h3>
            <p className="text-sm text-muted-foreground">
              Support for CSV, Excel, JSON, and text files
            </p>
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              multiple
              accept=".csv,.xlsx,.xls,.json,.txt"
              onChange={handleFileSelect}
            />
            <Button 
              variant="secondary"
              className="mt-4"
            >
              Browse Files
            </Button>
          </div>
        </div>

        {uploadedFiles.length > 0 && (
          <div className="mt-6 border rounded-md p-4">
            <h4 className="font-medium mb-2">Selected Files ({uploadedFiles.length})</h4>
            <ul className="space-y-2 max-h-40 overflow-y-auto">
              {uploadedFiles.map((file, index) => (
                <li key={index} className="flex items-center justify-between text-sm p-2 bg-secondary/50 rounded">
                  <div className="flex items-center">
                    <File className="h-4 w-4 mr-2" />
                    <span>{file.name}</span>
                    <span className="ml-2 text-muted-foreground">({(file.size / 1024).toFixed(1)} KB)</span>
                  </div>
                  <button 
                    onClick={() => removeFile(index)}
                    className="text-red-500 hover:text-red-700"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {uploadError && (
          <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-md flex items-center">
            <AlertCircle className="h-4 w-4 mr-2" />
            {uploadError}
          </div>
        )}

        <div className="mt-6">
          <h4 className="font-medium mb-4">Upload Settings</h4>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">File Processing Options</label>
              <select 
                className="w-full p-2 rounded-lg border"
                value={processingType}
                onChange={(e) => setProcessingType(e.target.value)}
              >
                <option value="auto">Automatic Detection</option>
                <option value="csv">CSV Processing</option>
                <option value="excel">Excel Processing</option>
                <option value="json">JSON Processing</option>
              </select>
            </div>
            <div className="pt-4 border-t">
              <div className="flex items-center space-x-2">
                <input 
                  type="checkbox" 
                  id="saveTemplate" 
                  className="rounded border-gray-300"
                  checked={saveAsTemplate}
                  onChange={(e) => setSaveAsTemplate(e.target.checked)}
                />
                <label htmlFor="saveTemplate" className="text-sm">Save upload settings as template</label>
              </div>
            </div>
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
        <h2 className="text-2xl font-bold mb-2">
          {uploadMode === "upload" ? "Files Uploaded Successfully!" : "Connection Successful!"}
        </h2>
        <p className="text-muted-foreground">
          {uploadMode === "upload" 
            ? `Your files have been uploaded and are being processed.${uploadSuccess?.sourceId ? ' Source ID: ' + uploadSuccess.sourceId : ''}`
            : `Your ${selectedSource?.name} connection has been set up successfully.`
          }
        </p>
      </div>

      <div className="flex justify-center gap-4">
        <Button
          onClick={() => router.push("/sources/browse")}
          className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-2"
        >
          View All Sources
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            setStep(1);
            setSelectedSource(null);
            setConnectionName("");
            setApiKey("");
            setHost("");
            setPort("");
            setDbName("");
            setAutoSync(false);
            setUploadedFiles([]);
            setProcessingType("auto");
            setSaveAsTemplate(false);
            setUploadSuccess(null);
            setUploadError(null);
          }}
          className="px-6 py-2"
        >
          {uploadMode === "upload" ? "Upload More Files" : "Connect Another Source"}
        </Button>
      </div>
    </div>
  );

  async function handleSubmit() {
    if (!selectedSource) return;
    
    setLoading(true);
    setError(null);
    
    // Create configuration object based on form inputs
    const configuration: Record<string, string> = {
      apiKey: apiKey,
    };
    
    if (selectedSource.id === "postgres") {
      configuration.host = host;
      configuration.port = port;
      configuration.database = dbName;
    }
    
    const sourceData: SourceCreate = {
      name: connectionName,
      type: selectedSource.sourceType,
      description: `${selectedSource.name} connection: ${connectionName}`,
      configuration: configuration,
      metadata: {
        autoSync: autoSync,
        sourceId: selectedSource.id
      },
      owner: 'current-user', // TODO: Get from auth context
    };

    try {
      await sourcesApi.createSource(sourceData);
      setStep(3);
    } catch (submitErr: unknown) {
      setError('Failed to create source');
      console.error("Source creation error:", submitErr);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 bg-background">
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
          <h1 className="text-4xl font-bold">Add New Data Source</h1>
          <p className="text-lg text-muted-foreground mt-2">
            {step === 1 ? "Choose how you want to add your data" :
             step === 2 ? (selectedSource?.id === "file" ? "Upload your files" : "Configure connection details") :
             "Setup complete"}
          </p>
        </div>
      </div>

      {step === 1 && (
        <div className="mb-8 flex gap-4">
          <Button
            onClick={() => setUploadMode("upload")}
            variant={uploadMode === "upload" ? "default" : "outline"}
            className="flex items-center gap-2 px-6 py-3"
          >
            <Upload className="h-5 w-5" />
            Quick Upload
          </Button>
          <Button
            onClick={() => setUploadMode("connect")}
            variant={uploadMode === "connect" ? "default" : "outline"}
            className="flex items-center gap-2 px-6 py-3"
          >
            <LinkIcon className="h-5 w-5" />
            Connect Source
          </Button>
        </div>
      )}

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

      {error && (
        <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-md">
          {error}
        </div>
      )}

      {step === 1 && uploadMode === "upload" && renderFileUpload()}
      {step === 1 && uploadMode === "connect" && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}

      {step === 1 && uploadMode === "upload" && (
        <div className="fixed bottom-8 right-8">
          <Button
            onClick={handleFileUpload}
            disabled={uploadLoading || uploadedFiles.length === 0}
            className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-3 rounded-lg flex items-center gap-2"
          >
            {uploadLoading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Processing Files...
              </>
            ) : (
              <>
                Process Files
                <ChevronRight className="h-5 w-5" />
              </>
            )}
          </Button>
        </div>
      )}

      {step === 1 && uploadMode === "connect" && selectedSource && (
        <div className="fixed bottom-8 right-8">
          <Button
            onClick={() => setStep(2)}
            className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-3 rounded-lg flex items-center gap-2"
          >
            Continue Setup
            <ChevronRight className="h-5 w-5" />
          </Button>
        </div>
      )}

      {step === 2 && (
        <div className="fixed bottom-8 right-8">
          <Button
            onClick={handleSubmit}
            disabled={loading}
            className="bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-3 rounded-lg flex items-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                Connect Source
                <ChevronRight className="h-5 w-5" />
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
} 