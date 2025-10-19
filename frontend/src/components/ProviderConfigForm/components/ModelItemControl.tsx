import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, XCircle, Loader2, TestTube } from "lucide-react";
import { useState } from "react";
import { testModelInstance } from "@/lib/browser-api";
import type { ModelSpec } from "@/types/provider";

type ModelItemControlProps = {
  model: ModelSpec;
  isSelected: boolean;
  onSelect: (isSelected: boolean) => void;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
  providerConfigId?: string;
  canTest?: boolean;
}

type TestResult = {
  success: boolean;
  message: string;
  error_type?: string;
  response_content?: string;
  cost?: number;
  tokens_used?: number;
}

export const ModelItemControl = ({ 
  model, 
  isSelected, 
  onSelect, 
  providerConfigId, 
  canTest = false 
}: ModelItemControlProps) => {
    const [isTestingLLM, setIsTestingLLM] = useState(false);
    const [testResult, setTestResult] = useState<TestResult | null>(null);

    const handleTestLLM = async (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        
        if (!providerConfigId) return;
        
        setIsTestingLLM(true);
        setTestResult(null);
        
        try {
            const { data, error } = await testModelInstance({
                provider_config_id: providerConfigId,
                model_spec_id: model.id,
                test_message: "Hello, this is a test message to verify the LLM configuration."
            });
            
            if (error || !data) {
                const errorMessage = error?.detail?.[0]?.msg || (error as any)?.message || "Test failed";
                setTestResult({
                    success: false,
                    message: errorMessage,
                    error_type: "TestError"
                });
            } else {
                setTestResult(data);
            }
        } catch (err) {
            setTestResult({
                success: false,
                message: "Network error during test",
                error_type: "NetworkError"
            });
        } finally {
            setIsTestingLLM(false);
        }
    };

    return (
        <div className="card-item px-3 py-2 space-y-2">
            <div className="flex gap-2">
                <Checkbox
                    checked={isSelected}
                    onCheckedChange={onSelect}
                    aria-label="Toggle model"
                    className="mt-1 min-w-[16px]"
                    id={`model-${model.id}`}
                />
                <Label className="
                    flex gap-2 justify-between w-full cursor-pointer
                    flex-col sm:flex-row md:flex-col lg:flex-row   
                    items-start sm:items-center md:items-start lg:items-center "
                    htmlFor={`model-${model.id}`}
                >
                    <div className="flex flex-col gap-1">
                        <div className="text-sm font-medium">{model.display_name}</div>
                        <div className="text-xs text-muted-foreground/50">{model.description}</div>
                    </div>
                    <div className="flex items-center justify-start gap-2 sm:gap-3">
                        <div className="note">{model.context_window.toLocaleString()} tokens</div>
                        <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
                        <div className="note">$0/M input tokens</div>
                        <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
                        <div className="note">$0/M output tokens</div>
                    </div>
                </Label>
            </div>
            
            {/* Test Section */}
            {canTest && providerConfigId && (
                <div className="ml-6 space-y-2">
                    <div className="flex items-center gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={handleTestLLM}
                            disabled={isTestingLLM}
                            className="gap-2"
                        >
                            {isTestingLLM ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                                <TestTube className="h-3 w-3" />
                            )}
                            {isTestingLLM ? "Testing..." : "Test"}
                        </Button>
                        
                        {testResult && (
                            <Badge 
                                variant={testResult.success ? "default" : "destructive"}
                                className="gap-1"
                            >
                                {testResult.success ? (
                                    <CheckCircle className="h-3 w-3" />
                                ) : (
                                    <XCircle className="h-3 w-3" />
                                )}
                                {testResult.success ? "Success" : "Failed"}
                            </Badge>
                        )}
                    </div>
                    
                    {testResult && (
                        <div className={`text-xs p-2 rounded ${
                            testResult.success 
                                ? "bg-green-50 text-green-700 border border-green-200" 
                                : "bg-red-50 text-red-700 border border-red-200"
                        }`}>
                            <div className="font-medium">{testResult.message}</div>
                            {testResult.success && testResult.response_content && (
                                <div className="mt-1 text-green-600">
                                    Response: &quot;{testResult.response_content.slice(0, 100)}...&quot;
                                </div>
                            )}
                            {testResult.success && testResult.cost && (
                                <div className="mt-1 text-green-600">
                                    Cost: ${testResult.cost.toFixed(6)} ({testResult.tokens_used} tokens)
                                </div>
                            )}
                            {!testResult.success && testResult.error_type && (
                                <div className="mt-1 text-red-600">
                                    Error type: {testResult.error_type}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};