import { Card } from "@/components/ui/card";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ModelSpec } from "../ProviderConfigForm";  

interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

export default function ModelInstances({ selectedProvider, availableModels }: { selectedProvider: any, availableModels: ModelSpec[] }) {
    const [selectedModels, setSelectedModels] = useState<SelectedModel[]>([]);
    const [expandedModels, setExpandedModels] = useState<Set<string>>(new Set());

    // Auto-select all models when component loads or availableModels changes
    useEffect(() => {
        if (selectedProvider && availableModels.length > 0) {
            const allModels = availableModels.map((model: ModelSpec) => ({
                modelSpecId: model.id,
                instanceName: `${selectedProvider?.name} ${model.display_name}`,
                description: model.description || '',
                isPublic: false
            }));
            setSelectedModels(allModels);
        }
    }, [selectedProvider, availableModels]);

    const handleModelToggle = (modelSpec: ModelSpec, checked: boolean) => {
        if (checked) {
          setSelectedModels(prev => [...prev, {
            modelSpecId: modelSpec.id,
            instanceName: `${selectedProvider?.name} ${modelSpec.display_name}`,
            description: modelSpec.description || '',
            isPublic: false
          }]);
        } else {
          setSelectedModels(prev => prev.filter(m => m.modelSpecId !== modelSpec.id));
        }
      };

    const toggleModelExpanded = (modelId: string) => {
        setExpandedModels(prev => {
          const newSet = new Set(prev);
          if (newSet.has(modelId)) {
            newSet.delete(modelId);
          } else {
            newSet.add(modelId);
          }
          return newSet;
        });
      };

    const updateSelectedModel = (modelSpecId: string, updates: Partial<SelectedModel>) => {
        setSelectedModels(prev => prev.map(model => 
          model.modelSpecId === modelSpecId ? { ...model, ...updates } : model
        ));
      };

    return (
        <motion.div
          initial={{ 
            height: 0, 
            opacity: 0,
            scale: 0.95,
            overflow: "hidden"
          }}
          animate={{ 
            height: "auto", 
            opacity: 1,
            scale: 1,
            overflow: "visible"
          }}
          transition={{ 
            duration: 0.6, 
            ease: [0.4, 0, 0.2, 1],
            opacity: { duration: 0.4, delay: 0.2 }
          }}
        >
          <Card className="grid grid-cols-1 gap-6">
            <motion.div 
              className="space-y-1"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.3 }}
            >
              <FormLabel icon={Brain}>Model Instances</FormLabel>
              <p className="note">
                Select models to create instances for this provider configuration
              </p>
            </motion.div>
            
            <motion.div 
              className="space-y-4"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.4 }}
            >
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">
                  Available Models for {selectedProvider.name}:
                </div>
                {availableModels.length > 0 && (
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        // Select all models
                        const allModels = availableModels.map((model: ModelSpec) => ({
                          modelSpecId: model.id,
                          instanceName: `${selectedProvider?.name} ${model.display_name}`,
                          description: model.description || '',
                          isPublic: false
                        }));
                        setSelectedModels(allModels);
                      }}
                      disabled={selectedModels.length === availableModels.length}
                    >
                      Select All
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedModels([])}
                      disabled={selectedModels.length === 0}
                    >
                      Clear All
                    </Button>
                  </div>
                )}
              </div>
              
              {availableModels.length === 0 ? (
                <motion.div 
                  className="text-sm text-muted-foreground bg-gray-50 p-4 rounded-lg text-center"
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.3 }}
                >
                  No models available for this provider.
                </motion.div>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {availableModels.map((model: ModelSpec, index: number) => {
                    const isSelected = selectedModels.some(m => m.modelSpecId === model.id);
                    const selectedModel = selectedModels.find(m => m.modelSpecId === model.id);
                    const isExpanded = expandedModels.has(model.id);
                    
                    return (
                      <motion.div 
                        key={model.id} 
                        className="border rounded-lg p-4 space-y-3 hover:bg-gray-50 transition-colors"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, delay: 0.5 + index * 0.1 }}
                      >
                        <div className="flex items-start space-x-3">
                          <Checkbox
                            id={`model-${model.id}`}
                            checked={isSelected}
                            onCheckedChange={(checked) => handleModelToggle(model, checked as boolean)}
                          />
                          <div className="flex-1 space-y-1">
                            <div className="flex items-center gap-2">
                              <Label htmlFor={`model-${model.id}`} className="font-medium cursor-pointer">
                                {model.display_name}
                              </Label>
                              {model.context_window && (
                                <Badge variant="outline">
                                  {model.context_window.toLocaleString()} tokens
                                </Badge>
                              )}
                            </div>
                            <div className="text-sm text-muted-foreground">
                              {model.description || 'No description available'}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              Model: {model.model_name}
                            </div>
                          </div>
                        </div>
                        
                        <AnimatePresence>
                          {isSelected && selectedModel && (
                            <motion.div
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: "auto" }}
                              exit={{ opacity: 0, height: 0 }}
                              transition={{ duration: 0.3 }}
                            >
                              <Button 
                                type="button"
                                variant="ghost" 
                                size="sm" 
                                className="ml-6 w-full justify-start"
                                onClick={() => toggleModelExpanded(model.id)}
                              >
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4 mr-2" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 mr-2" />
                                )}
                                Configure Instance Settings
                              </Button>
                              
                              <AnimatePresence>
                                {isExpanded && (
                                  <motion.div 
                                    className="ml-6 space-y-3 bg-blue-50 p-3 rounded border-l-2 border-blue-200 mt-2"
                                    initial={{ opacity: 0, height: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, height: "auto", scale: 1 }}
                                    exit={{ opacity: 0, height: 0, scale: 0.95 }}
                                    transition={{ duration: 0.3 }}
                                  >
                                    <div className="text-sm font-medium text-blue-900">
                                      Instance Configuration
                                    </div>
                                    <div className="space-y-2">
                                      <Label htmlFor={`name-${model.id}`}>Instance Name</Label>
                                      <Input
                                        id={`name-${model.id}`}
                                        value={selectedModel.instanceName}
                                        onChange={(e) => updateSelectedModel(model.id, { instanceName: e.target.value })}
                                        placeholder="Model instance name"
                                      />
                                    </div>
                                    <div className="space-y-2">
                                      <Label htmlFor={`desc-${model.id}`}>Description (Optional)</Label>
                                      <Textarea
                                        id={`desc-${model.id}`}
                                        value={selectedModel.description}
                                        onChange={(e) => updateSelectedModel(model.id, { description: e.target.value })}
                                        placeholder="Describe this model instance..."
                                        rows={2}
                                      />
                                    </div>
                                    <div className="flex items-center space-x-2">
                                      <Switch
                                        id={`public-${model.id}`}
                                        checked={selectedModel.isPublic}
                                        onCheckedChange={(checked) => updateSelectedModel(model.id, { isPublic: checked })}
                                      />
                                      <Label htmlFor={`public-${model.id}`}>
                                        Make this instance public
                                      </Label>
                                    </div>
                                  </motion.div>
                                )}
                              </AnimatePresence>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </motion.div>
                    );
                  })}
                </div>
              )}
              
              <AnimatePresence>
                {selectedModels.length > 0 && (
                  <motion.div 
                    className="bg-green-50 p-3 rounded-lg border border-green-200"
                    initial={{ opacity: 0, height: 0, scale: 0.95 }}
                    animate={{ opacity: 1, height: "auto", scale: 1 }}
                    exit={{ opacity: 0, height: 0, scale: 0.95 }}
                    transition={{ duration: 0.3 }}
                  >
                    <div className="text-sm font-medium text-green-900">
                      {selectedModels.length} model{selectedModels.length === 1 ? '' : 's'} selected
                    </div>
                    <div className="text-xs text-green-700 mt-1">
                      These model instances will be created along with your provider configuration.
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </Card>
        </motion.div>
    )
}