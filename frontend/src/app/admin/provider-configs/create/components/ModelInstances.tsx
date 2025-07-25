import { Card } from "@/components/ui/card";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Brain } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { ModelSpec } from "../ProviderConfigForm";  
import { ModelItemControl } from "./ModelItemControl";
import { Label } from "@/components/ui/label";

interface SelectedModel {
  modelSpecId: string;
  instanceName: string;
  description: string;
  isPublic: boolean;
}

type ModelInstancesProps = {    
  selectedProvider: any;
  availableModels: ModelSpec[];
  selectedModels: SelectedModel[];
  setSelectedModels: (models: SelectedModel[]) => void;
}

export default function ModelInstances({ selectedProvider, availableModels, selectedModels, setSelectedModels }: ModelInstancesProps) {
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
          const newModel: SelectedModel = {
            modelSpecId: modelSpec.id,
            instanceName: `${selectedProvider?.name} ${modelSpec.display_name}`,
            description: modelSpec.description || '',
            isPublic: false
          };
          setSelectedModels([...selectedModels, newModel]);
        } else {
          setSelectedModels(selectedModels.filter((m: SelectedModel) => m.modelSpecId !== modelSpec.id));
        }
      };

    const handleSelectAllToggle = (checked: boolean) => {
        if (checked) {
            // Select all models
            const allModels = availableModels.map((model: ModelSpec) => ({
                modelSpecId: model.id,
                instanceName: `${selectedProvider?.name} ${model.display_name}`,
                description: model.description || '',
                isPublic: false
            }));
            setSelectedModels(allModels);
        } else {
            // Clear all models
            setSelectedModels([]);
        }
    };

    const isAllSelected = selectedModels.length === availableModels.length && availableModels.length > 0;

    return (
        <motion.div
          initial={{ height: 0, opacity: 0, overflow: "hidden"}}
          animate={{ height: "auto", opacity: 1, overflow: "visible"}}
          transition={{ duration: 0.4, ease: "easeOut"}}
        >
          <Card className="grid grid-cols-1 gap-4">
            <div className="space-y-1">
              <FormLabel icon={Brain}>Model Instances</FormLabel>
              <p className="note">
                Select models to create instances for this <span className="font-semibold">{selectedProvider.name}</span> configuration
              </p>
            </div>
            
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                {/* <div className="text-sm font-medium">
                  Available Models for {selectedProvider.name}:
                </div> */}
                {availableModels.length > 0 && (
                  <div className="flex items-center space-x-2 mx-3">
                    <Switch
                      size="xs"
                      checked={isAllSelected}
                      onCheckedChange={handleSelectAllToggle}
                      aria-label="Select all models"
                      id="select-all-models"
                    />
                    <Label className="note font-normal text-xs cursor-pointer" htmlFor="select-all-models">
                        selected{" "}
                        <span className="text-sm">{selectedModels.length}</span>
                        {" "}of {availableModels.length}
                    </Label>
                  </div>
                )}
              </div>
              
              {availableModels.length === 0 ? (
                <div className="text-sm text-muted-foreground bg-gray-50 p-4 rounded-lg text-center">
                  No models available for this provider.
                </div>
              ) : (
                <div className="space-y-3 overflow-y-auto">
                  {availableModels.map((model: ModelSpec, key) => {
                    return (
                        <ModelItemControl 
                            key={model.id}
                            model={model}
                            isSelected={selectedModels.some(m => m.modelSpecId === model.id)}
                            onSelect={(checked) => handleModelToggle(model, checked as boolean)}
                        />
                    );
                  })}
                </div>
              )}
            </div>
          </Card>
        </motion.div>
    )
}